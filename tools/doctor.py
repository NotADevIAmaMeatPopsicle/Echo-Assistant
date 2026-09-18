"""Read-only Round Voice readiness; no recording, home actions or credential output."""
import importlib.metadata
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fetch(path, token=None):
    headers = {'Authorization': 'Bearer '+token} if token else {}
    request = urllib.request.Request('http://127.0.0.1:8768'+path, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=5) as response:
        return json.load(response)


def main():
    report = {'runtime': {}, 'model': 'missing', 'device': 'not_detected', 'api': 'offline'}
    for name in ('fastapi', 'uvicorn', 'httpx', 'vosk', 'soxr', 'numpy', 'pyserial'):
        try: report['runtime'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: report['runtime'][name] = 'missing'
    if (ROOT/'local/models/vosk-model-small-en-us-0.15/am/final.mdl').is_file(): report['model'] = 'present'
    try:
        from serial.tools import list_ports
        ports = [port.device for port in list_ports.comports() if (port.vid, port.pid) == (0x303A, 0x1001)
                 and (not __import__('os').environ.get('ECHO_DEVICE_MAC') or (port.serial_number or '').lower() == __import__('os').environ['ECHO_DEVICE_MAC'].lower())]
        if len(ports) == 1: report['device'] = ports[0]
    except ImportError: pass
    try:
        health = fetch('/health')
        report['api'] = 'ready' if health.get('product') == 'round-voice' else 'unexpected_service'
        if report['api'] == 'ready':
            report['api_version'] = health.get('version')
            report['capabilities'] = {key: health.get(key) for key in ('device_transport', 'wake_word', 'speech_to_text', 'text_to_speech', 'speech_worker', 'spotify_connect', 'speaker_muted', 'music_wake')}
            token = (ROOT/'local/api-token').read_text(encoding='utf-8').strip()
            voice = fetch('/v1/voice', token)
            report['audio'] = {key: voice.get(key) for key in ('usb_errors', 'usb_gaps', 'playback_errors', 'speaker')}
            report['board'] = {key: voice.get('device', {}).get(key) for key in ('version', 'volume', 'network', 'rssi')}
            report['recognition'] = voice.get('recognition', {})
            report['display'] = voice.get('display', {})
            report['recovery'] = {key: voice.get(key) for key in ('connection_failures', 'last_disconnect_reason')}
            report['music_receiver'] = voice.get('music', {})
            home = fetch('/v1/home', token)
            report['home'] = {'status': home.get('status'), 'devices': {key: value.get('status') for key, value in home.get('devices', {}).items()}}
    except (OSError, ValueError, KeyError): report['details'] = 'Some live checks unavailable'
    firewall = ROOT/'local/firewall-result.json'
    if firewall.exists():
        try: report['firewall_script'] = json.loads(firewall.read_text(encoding='utf-8-sig')).get('status')
        except (OSError, ValueError): report['firewall_script'] = 'invalid_result'
    else: report['firewall_script'] = 'not_applied'
    report['next_steps'] = []
    if 'missing' in report['runtime'].values() or report['model'] == 'missing':
        report['next_steps'].append('Run tools/setup.ps1 to install the project runtime and verified voice model.')
    if not (ROOT/'local/aec-python/Scripts/python.exe').is_file():
        report['next_steps'].append('For wake during music, run tools/setup.ps1 -Echo with an existing Python 3.13 available.')
    if report['api'] == 'offline':
        report['next_steps'].append('Run tools/run.ps1 start, then tools/run.ps1 status.')
    elif report.get('capabilities', {}).get('device_transport') == 'not_connected':
        report['next_steps'].append('Check board power and paired Wi-Fi; use tools/run.ps1 stop then start -Usb for recovery.')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
