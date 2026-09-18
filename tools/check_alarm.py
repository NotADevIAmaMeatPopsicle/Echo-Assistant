"""Create one short setup timer and verify acknowledged delivery through the live board."""
import json
from pathlib import Path
import time
import httpx


def main():
    root = Path(__file__).resolve().parents[1]
    token = (root/'local/api-token').read_text(encoding='utf-8').strip()
    with httpx.Client(base_url='http://127.0.0.1:8768', trust_env=False, timeout=5,
                      headers={'Authorization': 'Bearer '+token}) as client:
        voice = client.get('/v1/voice'); voice.raise_for_status(); before = voice.json()
        if before.get('status') not in {'armed', 'muted'}:
            raise SystemExit('The live bridge must be armed or muted before the alarm test')
        response = client.post('/v1/timers', json={'seconds': 3, 'label': 'Setup check'})
        response.raise_for_status(); timer_id = response.json()['id']
        try:
            deadline = time.monotonic()+40
            while time.monotonic() < deadline:
                response = client.get('/v1/state'); response.raise_for_status()
                timer = next((t for t in response.json()['timers'] if t['id'] == timer_id), None)
                if not timer: raise RuntimeError('Setup timer was removed before delivery')
                if timer['notified']:
                    settled = time.monotonic()+3
                    while True:
                        response = client.get('/v1/voice'); response.raise_for_status(); after = response.json()
                        if not after.get('speaker', {}).get('active'): break
                        if time.monotonic() >= settled: raise RuntimeError('Speaker did not settle after alarm')
                        time.sleep(.1)
                    assert after.get('playback_errors') == before.get('playback_errors'), 'Playback failed'
                    assert after.get('speaker', {}).get('underruns') == 0, 'Audio underrun'
                    assert after.get('speaker', {}).get('frames', 0) > 0, 'No speaker completion receipt'
                    print(json.dumps({'result': 'PASS', 'alarm_acknowledged': True,
                        'speaker': after['speaker'], 'playback_errors': after['playback_errors']}))
                    return
                time.sleep(.25)
            raise RuntimeError('No alarm delivery acknowledgement within forty seconds')
        finally:
            response = client.delete('/v1/timers/'+timer_id)
            response.raise_for_status()


if __name__ == '__main__': main()
