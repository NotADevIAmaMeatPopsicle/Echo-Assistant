"""Silently interrupt only the local API and verify board controls recover without reconnecting."""
import json
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import time
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.lifecycle import request_stop
from backend.voice_status import voice_status
from backend.settings import speech_settings

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = ('thermostat', 'soundbar', 'weather', 'timers')


def wait_for(predicate, seconds, message):
    until = time.monotonic()+seconds
    while time.monotonic() < until:
        if predicate(): return
        time.sleep(.2)
    raise RuntimeError(message)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--during-speech',action='store_true',help='Stop during an explicit silent neural voice check')
    args=parser.parse_args()
    baseline = voice_status(ROOT)
    if baseline.get('device', {}).get('volume') != '0':
        raise SystemExit('This silent recovery check requires the board already muted at 0%')
    if baseline.get('speaker', {}).get('active') or baseline.get('music', {}).get('status') == 'playing':
        raise SystemExit('Stop playback before the recovery check')
    if not all(baseline.get('display', {}).get(name) == 1 for name in CONTROLS):
        raise SystemExit('Firmware 0.8.1+ and available home/timer controls are required')
    connection = baseline['connection_id']
    api_record = ROOT/'local/api-process.json'
    api_stopped = False; restarted = None; checking = None; check_result = None
    requests = ThreadPoolExecutor(1)
    def intact():
        state = voice_status(ROOT)
        if state.get('connection_id') != connection: raise RuntimeError('Board bridge disconnected')
        if state.get('device', {}).get('volume') != '0': raise RuntimeError('Silent setting changed')
        return state
    def start_api():
        nonlocal restarted
        with (ROOT/'local/api-output.log').open('ab') as output, (ROOT/'local/api-health.log').open('ab') as errors:
            restarted = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'backend.app'], cwd=ROOT,
                stdout=output, stderr=errors, creationflags=subprocess.CREATE_NO_WINDOW)
        def ready():
            if restarted.poll() is not None: raise RuntimeError('API restart exited; inspect its health log')
            try:
                response = httpx.get('http://127.0.0.1:8768/health', timeout=1, trust_env=False)
                return response.status_code == 200 and response.json().get('product') == 'round-voice'
            except (httpx.HTTPError, ValueError): return False
        wait_for(ready, 15, 'API did not become ready')
    try:
        if args.during_speech:
            settings=speech_settings(ROOT)
            if settings.tts_engine not in {'pocket','kokoro'}: raise RuntimeError('Select an installed neural voice first')
            api_pid=int(json.loads(api_record.read_text(encoding='utf-8'))['pid'])
            token=(ROOT/'local/api-token').read_text(encoding='utf-8').strip()
            def voice_check():
                try:
                    return httpx.post('http://127.0.0.1:8768/v1/settings/check-voice',timeout=70,trust_env=False,
                        headers={'Authorization':'Bearer '+token},json={key:getattr(settings,key) for key in
                        ('tts_engine','tts_voice','tts_rate')}).status_code
                except httpx.HTTPError: return 'connection_closed'
            checking=requests.submit(voice_check)
            def child_started():
                # Read only the known API's child PIDs, never command text or credentials.
                command=f"@(Get-CimInstance Win32_Process -Filter 'ParentProcessId={api_pid}' | Where-Object {{ $_.Name -eq 'python.exe' -and $_.CommandLine -match 'backend.tts_worker' }}).Count"
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
                return result.returncode==0 and int(result.stdout.strip() or b'0')>0 and not checking.done()
            wait_for(child_started,15,'No running API speech child was observed')
        stopped_at=time.monotonic()
        if not request_stop(ROOT, 'api'): raise RuntimeError('No running API to test')
        api_stopped = True
        wait_for(lambda: not api_record.exists(), 15, 'API has not stopped; it was not force-killed')
        stop_seconds=round(time.monotonic()-stopped_at,3)
        if checking:
            check_result=checking.result(timeout=3)
            if check_result not in (503,'connection_closed'): raise RuntimeError('Voice check completed before cancellation was verified')
        wait_for(lambda: all(intact().get('display', {}).get(name) == 0 for name in CONTROLS),
                 25, 'Board did not mark unavailable controls')
        print('Board marked home and timer controls unavailable; voice connection stayed live', flush=True)
        start_api()
        wait_for(lambda: all(intact().get('display', {}).get(name) == 1 for name in CONTROLS),
                 25, 'Board controls did not recover after API restart')
        final = intact()
        for name in ('usb_errors', 'usb_gaps', 'playback_errors', 'connection_failures'):
            if final.get(name, 0) != baseline.get(name, 0): raise RuntimeError(name+' changed')
        result={'result':'PASS', 'controls_unavailable_then_restored':list(CONTROLS),
            'connection_changed':False, 'volume':0, 'playback_started':False, 'home_actions_sent':False,
            'cancelled_voice_check':bool(checking),'voice_check_result':check_result,'api_stop_seconds':stop_seconds}
        print(json.dumps(result))
        (ROOT/'local/service-recovery-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    finally:
        # Restore the service even if a display assertion failed, but never
        # start over an API that has not finished the requested shutdown.
        if api_stopped and restarted is None and not api_record.exists(): start_api()
        requests.shutdown(wait=True,cancel_futures=True)


if __name__ == '__main__': main()
