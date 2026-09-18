"""Play one approved quiet Echo sample and pause music while speech is busy.

Uses the existing sample/voice owner at exactly 2%; never changes output volume.
This checks real API admission and uninterrupted speech output. Deferred music
resumption is exercised separately by the synthetic conversation-loop tests.
"""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.remote_device import client


def main():
    with client() as api:
        def read(path):
            response=api.get(path,timeout=5); response.raise_for_status(); return response.json()
        first=read('/v1/voice')
        assert first['status']=='armed' and first['device']['volume']=='2' and not first['speaker']['active']
        assert first['music']['status'] in {'connected','paused','stopped'}
        response=api.post('/v1/settings/speaker-check');response.raise_for_status()
        identifier=response.json()['id']; pause_phase=None; completed=False; result={}
        try:
            deadline=time.monotonic()+45
            while time.monotonic()<deadline:
                state=read('/v1/voice')
                assert state['connection_id']==first['connection_id'] and state['device']['volume']=='2'
                assert state['playback_errors']==first['playback_errors']
                if pause_phase is None and state['status'] in {'thinking','speaking'}:
                    response=api.post('/v1/music/control',json={'action':'pause'});response.raise_for_status()
                    assert response.json()['status']=='queued'
                    pause_phase=state['status']
                result=read('/v1/settings/speaker-check')
                assert result.get('id')==identifier
                if result['status']=='complete': completed=True; break
                assert result['status'] not in {'failed','cancelled'}
                time.sleep(.1)
            assert completed and pause_phase is not None
            assert result['frames']>0
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                state=read('/v1/voice')
                if state['status']=='armed' and not state['speaker']['active']:break
                time.sleep(.1)
            assert state['status']=='armed' and not state['speaker']['active']
            assert not state['music_resume_pending']
            assert state['music']['status'] in {'connected','paused','stopped'}
            assert state['playback_errors']==first['playback_errors'] and state['speaker']['underruns']==0
            receipt={'version':read('/health')['version'],'pause_accepted_during':pause_phase,
                     'speech_sample_completed':True,'speaker_frames':result['frames'],
                     'volume':'2','underruns':0,'playback_error_increases':0,
                     'music_resume_pending':False,'speaker_active':False,'connection_preserved':True}
            (ROOT/'local/pause-during-speech.json').write_text(json.dumps(receipt,indent=2))
            print(json.dumps(receipt))
        finally:
            if not completed:
                response=api.delete('/v1/settings/speaker-check/'+identifier)
                response.raise_for_status()


if __name__=='__main__':main()
