"""Observe live voice transport health without saving audio, text, or media metadata."""
import argparse
import json
from pathlib import Path
import time
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.doctor import fetch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 3600: raise SystemExit('Observation must be 10–3600 seconds')
    target=ROOT/'local/host-target.json'
    remote=json.loads(target.read_text()).get('mode') if target.exists() else None
    if remote=='migrating':raise SystemExit('Wait for the host transfer to finish')
    if remote=='remote':
        from tools.remote_device import client
        api=client()
        token=None
        def read(path,token=None):
            response=api.get(path,timeout=5);response.raise_for_status();return response.json()
    else:
        read=fetch
        token = (ROOT/'local/api-token').read_text(encoding='utf-8').strip()
    first = read('/v1/voice', token)
    if first.get('status') in {'connecting', 'disconnected'} or not first.get('connection_id'):
        raise SystemExit('No connected voice session to observe')
    # A new bridge publishes its phase before the first device STATUS reply.
    # Do not mistake a previously accumulated hardware counter for a new drop.
    ready_until = time.monotonic()+5
    while not {'usb_drops', 'stream_drops'}.issubset(first.get('device', {})):
        if time.monotonic() >= ready_until: raise SystemExit('No complete device status to baseline')
        time.sleep(.1); first = read('/v1/voice', token)
    connection, started = first['connection_id'], time.monotonic()
    maximum = {name: int(first.get(name, 0)) for name in ('usb_errors', 'usb_gaps', 'playback_errors', 'connection_failures')}
    device_baseline = {name: int(first.get('device', {}).get(name) or 0) for name in ('usb_drops', 'stream_drops')}
    network_baseline = {name: int(first.get('network', {}).get(name) or 0) for name in ('disconnects', 'tx_full', 'write_errors')}
    recognition_baseline = {name: int(first.get('recognition', {}).get(name) or 0) for name in ('dropped', 'errors')}
    last_frames, last_progress = first.get('pcm_frames', 0), started
    observations = 0
    def fail(reason, state):
        # Replace an older passing receipt when a later observation fails.
        # Keep only health metadata, never media titles, speech or PCM.
        result={'result':'FAIL', 'reason':reason, 'transport':first.get('transport'),
                'firmware':first.get('device', {}).get('version'),
                'seconds':round(time.monotonic()-started,1), 'observations':observations,
                'framing':{name:state.get('framing', {}).get(name) for name in ('header','checksum','noise','console_interference')}}
        (ROOT/'local/voice-endurance.json').write_text(json.dumps(result,indent=2), encoding='utf-8')
        print(json.dumps(result)); raise SystemExit(1)
    while time.monotonic()-started < args.seconds:
        time.sleep(1)
        try: state = read('/v1/voice', token)
        except (OSError, ValueError): fail('Health endpoint unavailable', {})
        observations += 1
        if state.get('connection_id') != connection or state.get('status') in {'connecting', 'disconnected'}:
            fail('Transport disconnected during observation', state)
        for name in maximum:
            if int(state.get(name, 0)) > maximum[name]: fail(name+' increased', state)
        for section, baseline in (('device', device_baseline), ('network', network_baseline), ('recognition', recognition_baseline)):
            for name, initial in baseline.items():
                if int(state.get(section, {}).get(name) or 0) > initial:
                    fail(section+'.'+name+' increased', state)
        if int(state.get('device', {}).get('audio_errors', 0)):
            fail('Device audio error', state)
        if not state.get('recognition', {}).get('alive'):
            fail('Recognition worker is not running', state)
        frames = state.get('pcm_frames', 0)
        if frames > last_frames: last_progress = time.monotonic()
        # Capture is intentionally paused during local output or software mute.
        if state.get('phase') not in {'armed', 'listening', 'thinking'} or state.get('muted'):
            last_progress = time.monotonic()
        if time.monotonic()-last_progress > 4: fail('Microphone frames stopped', state)
        last_frames = frames
    result = {'result': 'PASS', 'transport': state.get('transport'), 'observations': observations,
              'firmware':state.get('device', {}).get('version'),
              'speaker_volume':state.get('device', {}).get('volume'), 'microphone_muted':state.get('muted'),
              'framing':state.get('framing', {}),
              'seconds': round(time.monotonic()-started, 1), 'microphone_frames': last_frames-first.get('pcm_frames', 0),
              'error_increases': 0, 'connection_changed': False,
              'recognition': state.get('recognition', {})}
    print(json.dumps(result))
    (ROOT/'local/voice-endurance.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
