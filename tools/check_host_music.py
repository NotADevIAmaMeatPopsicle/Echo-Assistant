"""Explicit short Spotify playback check on the migrated speaker, at 1-3% only."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.remote_device import client

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=8,choices=range(5,31),metavar='5-30')
    args=parser.parse_args()
    if json.loads((ROOT/'local/host-target.json').read_text()).get('mode')!='remote':
        raise RuntimeError('Use only after the physical host transfer')
    result={'result':'FAIL','audio_requested':False}
    with client() as api:
        def state():
            response=api.get('/v1/voice');response.raise_for_status();return response.json()
        first=state()
        assert 0<int(first.get('device',{}).get('volume',99))<=3, 'Set an approved quiet volume first'
        assert first.get('music',{}).get('status') in {'connected','paused','stopped'}, 'Spotify is not idle and connected'
        baseline={key:int(first.get(key,0)) for key in ('playback_errors','usb_errors','usb_gaps','connection_failures')}
        before=int(first['music']['nonzero_frames'])
        maximum_underruns=0;peak=0;played=0;last=first
        failure=None
        try:
            response=api.post('/v1/music/control',json={'action':'play'});response.raise_for_status()
            result['audio_requested']=True
            deadline=time.monotonic()+20;started=None
            while time.monotonic()<deadline:
                last=state()
                assert int(last.get('device',{}).get('volume',99))<=3, 'Volume exceeded the test ceiling'
                assert last.get('connection_id')==first.get('connection_id'), 'The device reconnected'
                for key,value in baseline.items():assert int(last.get(key,0))==value, key+' increased'
                maximum_underruns=max(maximum_underruns,int(last.get('speaker',{}).get('underruns',0)))
                peak=max(peak,int(last.get('device',{}).get('peak',0)))
                played=max(played,int(last.get('speaker',{}).get('frames',0)))
                if last.get('music',{}).get('status')=='playing' and int(last['music']['nonzero_frames'])>before and played>0:
                    if started is None:started=time.monotonic();deadline=started+args.seconds+2
                    if time.monotonic()-started>=args.seconds:break
                time.sleep(.2)
            assert started is not None and time.monotonic()-started>=args.seconds, 'Sustained playback was not confirmed'
            assert maximum_underruns==0, 'Playback underruns occurred'
            assert int(last.get('music',{}).get('errors',0))==int(first['music'].get('errors',0)), 'Receiver errors increased'
            result.update(result='PASS',volume=last['device']['volume'],seconds=round(time.monotonic()-started,1),
                nonzero_pcm_frames=int(last['music']['nonzero_frames'])-before,speaker_frames=played,
                underruns=maximum_underruns,microphone_peak=peak,error_increases=0)
        except Exception as error:
            failure=error
            result['failure_type']=type(error).__name__
        finally:
            if result['audio_requested']:
                response=api.post('/v1/music/control',json={'action':'pause'});response.raise_for_status()
                deadline=time.monotonic()+12
                while time.monotonic()<deadline:
                    paused=state()
                    if (paused.get('music',{}).get('status') in {'connected','paused','stopped'}
                            and not paused.get('speaker',{}).get('active')):break
                    time.sleep(.2)
                else:
                    failure=RuntimeError('Playback pause was not confirmed')
                    result['result']='FAIL'
                result['output_stopped']=not paused.get('speaker',{}).get('active')
            (ROOT/'local/remote-physical-music-check.json').write_text(json.dumps(result,indent=2))
            print(json.dumps(result))
        if failure:raise failure

if __name__=='__main__':main()
