"""Observe real Spotify-to-board playback; never start tracks or store listening history."""
import argparse
import json
from pathlib import Path
import time
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx

ROOT = Path(__file__).resolve().parents[1]


def target_client():
    target = ROOT/'local/host-target.json'
    mode = json.loads(target.read_text()).get('mode') if target.exists() else None
    if mode == 'migrating': raise SystemExit('Wait for the host transfer to finish')
    if mode == 'remote':
        from tools.remote_device import client
        return client()
    token = (ROOT/'local/api-token').read_text(encoding='utf-8').strip()
    return httpx.Client(base_url='http://127.0.0.1:8768', trust_env=False, timeout=5,
                        headers={'Authorization':'Bearer '+token})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=1800, help='Required seconds of actual playback')
    parser.add_argument('--wait-seconds', type=int, default=600, help='Time allowed for the user to select the receiver')
    args = parser.parse_args()
    if not 10 <= args.seconds <= 7200 or not 1 <= args.wait_seconds <= 1800:
        raise SystemExit('Invalid observation duration')
    receipt = ROOT/'local/music-endurance.json'
    def record(result):
        receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
    record({'result':'RUNNING', 'required_music_seconds':args.seconds})
    with target_client() as client:
        start = last = report_at = time.monotonic()
        playing = 0.
        began = False
        baseline = None
        previous_frames = None
        progressed = False
        connection = None
        last_progress = start
        voice_interrupted = False
        def fail(reason):
            record({'result':'FAIL', 'reason':reason,
                    'actual_music_seconds':round(playing,1),
                    'firmware':state.get('device',{}).get('version')})
            raise SystemExit(1)
        while True:
            now = time.monotonic()
            try:
                response = client.get('/v1/voice',timeout=5); response.raise_for_status(); state = response.json()
            except httpx.HTTPError:
                if began: fail('Local API unavailable during playback observation')
                state = {'status': 'disconnected'}
            if state.get('status') == 'disconnected' and began:
                fail('Bridge health became unavailable during playback observation')
            speaker = state.get('speaker', {})
            audible_path = (state.get('phase') == 'music' and state.get('music', {}).get('status') == 'playing'
                            and speaker.get('active') and speaker.get('kind') == 'M')
            counters = {key: int(state.get(key, 0)) for key in ('usb_errors', 'usb_gaps', 'playback_errors', 'connection_failures')}
            counters['audio_errors'] = int(state.get('device', {}).get('audio_errors', 0))
            for section, names in (('device', ('stream_drops','usb_drops')),
                                   ('recognition', ('dropped','errors'))):
                for name in names:
                    counters[section+'.'+name] = int(state.get(section, {}).get(name, 0))
            if audible_path and not began:
                baseline = counters; began = True
                connection = state.get('connection_id'); last_progress = now
                print('Actual Spotify playback started; observing delivered frames and audio health', flush=True)
            if began:
                if state.get('connection_id') != connection:
                    fail('Board connection changed during music observation')
                if any(counters[key] > baseline[key] for key in counters) or speaker.get('underruns', 0):
                    changed = [key for key in counters if counters[key] > baseline[key]]
                    fail('Speaker underrun' if speaker.get('underruns',0) else 'Counters increased: '+', '.join(changed))
                if audible_path:
                    # An active session without consumed frames does not count as playback.
                    frames = speaker.get('frames', 0)
                    if previous_frames is not None and frames > previous_frames:
                        # Count delivered audio duration as well as elapsed time.
                        # A slowly increasing counter is not continuous music.
                        playing += min(2, now-last, (frames-previous_frames)*256/48000); progressed = True
                        last_progress = now
                    if now-last_progress > 5:
                        fail('Music selected but speaker frames stopped advancing')
                    previous_frames = frames
                else:
                    previous_frames = None; last_progress = now
                    if state.get('phase') in {'activation','listening','thinking','speaking'}:
                        voice_interrupted = True
            if playing >= args.seconds and progressed:
                result = {'result': 'PASS', 'actual_music_seconds': round(playing, 1),
                          'audio_errors': 0, 'underruns': 0, 'physical_audio_acceptance': 'requires_user'}
                record(result)
                return
            if not began and now-start >= args.wait_seconds:
                record({'result':'WAITING', 'reason':'No real Spotify playback began'})
                return
            if began and now-start > args.wait_seconds+args.seconds*2:
                if voice_interrupted:
                    record({'result':'INCOMPLETE','reason':'Voice interaction interrupted the required music observation',
                            'actual_music_seconds':round(playing,1),'voice_interrupted':True,
                            'firmware':state.get('device',{}).get('version')})
                    raise SystemExit(2)
                fail('Not enough continuous delivered music for the required observation')
            if now-report_at >= 60:
                print(json.dumps({'observing': 'music' if began else 'waiting_for_phone', 'delivered_music_seconds': round(playing, 1)}), flush=True)
                report_at = now
            last = now
            time.sleep(1)


if __name__ == '__main__': main()
