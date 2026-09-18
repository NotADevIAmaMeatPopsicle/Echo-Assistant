"""Quiet regression check: repeated idle Pause followed by native Spotify Play.

The native control pipe deliberately bypasses Music.command('play'), just as an
incoming phone Play event does, so this cannot conceal a stale host audio gate.
Uses only echo-api, its one receiver process, and a verified idle board at 2%.
This is receiver/board verification, not acceptance of a phone's chooser UI.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import deployment
from tools.remote_device import client

NATIVE_PLAY=r'''
import json,os,stat,sys,time
from pathlib import Path
expected=json.load(sys.stdin)
state=json.loads(Path('/opt/echo/local/voice-status.json').read_text())
assert 0<=time.time()-state['updated_at']<5
assert state['connection_id']==expected['connection_id']
assert state['status']=='armed' and state['device']['volume']=='2' and not state['speaker']['active']
assert state['music']['status']=='paused'
receivers=[]
for item in Path('/proc').iterdir():
    if not item.name.isdigit():continue
    try:
        if (item/'cmdline').read_bytes().split(b'\0')[0]==b'/usr/local/bin/echo-librespot': receivers.append(item)
    except (FileNotFoundError,PermissionError,ProcessLookupError):pass
assert len(receivers)==1
fd=os.open(receivers[0]/'fd/0',os.O_WRONLY|os.O_NONBLOCK)
try:
    assert stat.S_ISFIFO(os.fstat(fd).st_mode), 'Expected the existing receiver control pipe'
    assert os.write(fd,b'play\n')==5
finally:os.close(fd)
print(json.dumps({'native_play_sent':True}))
'''


def main():
    with client() as api:
        def state():
            response=api.get('/v1/voice',timeout=5);response.raise_for_status();return response.json()
        def command(action):
            response=api.post('/v1/music/control',json={'action':action});response.raise_for_status()
        first=state()
        assert first['status']=='armed' and first['device']['volume']=='2' and not first['speaker']['active']
        assert first['music']['status'] in {'connected','paused','stopped'}
        requested=False
        def wait_for(predicate,seconds=15):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                current=state()
                assert current['connection_id']==first['connection_id'] and current['device']['volume']=='2'
                assert current['playback_errors']==first['playback_errors']
                if predicate(current):return current
                time.sleep(.1)
            raise AssertionError('Expected receiver/speaker state did not arrive')
        try:
            # Load the existing Spotify context before exercising a fresh idle Pause.
            command('play');requested=True
            wait_for(lambda s:s['status']=='music' and s['speaker']['active'] and s['speaker']['frames']>100)
            command('pause')
            idle=wait_for(lambda s:s['status']=='armed' and s['music']['status']=='paused' and not s['speaker']['active'])
            command('pause')
            # Observe a newer owner snapshot after the second Pause was consumed.
            after_request=state()['updated_at']
            idle=wait_for(lambda s:s['updated_at']>after_request and s['status']=='armed')
            assert not idle['music']['pause_pending'] and not idle['music']['pause_after_transfer']
            completed=subprocess.run(['docker','--context',deployment.docker_context(),'exec','-i','echo-api','python','-c',NATIVE_PLAY],
                input=json.dumps({'connection_id':first['connection_id']}).encode(),capture_output=True,timeout=10)
            assert completed.returncode==0, 'Native receiver control check failed'
            assert json.loads(completed.stdout)['native_play_sent']
            # This regression asks whether the audio gate opens at all. Endurance
            # is measured separately by check_music_session.py, with wake pauses.
            resumed=wait_for(lambda s:s['status']=='music' and s['speaker']['active'] and s['speaker']['frames']>100)
            assert resumed['speaker']['underruns']==0
            assert resumed['music']['nonzero_frames']>idle['music']['nonzero_frames']
            receipt={'version':api.get('/health').json()['version'],'idle_pause_then_native_resume':True,
                     'speaker_frames':resumed['speaker']['frames'],
                     'nonzero_pcm_frames':resumed['music']['nonzero_frames']-idle['music']['nonzero_frames'],
                     'volume':'2','underruns':0,'playback_error_increases':0,'connection_preserved':True,
                     'phone_ui_tested':False,'sustained_playback_tested':False,
                     'receiver_error_increases':resumed['music']['errors']-first['music']['errors']}
        finally:
            if requested:
                command('pause')
                wait_for(lambda s:s['music']['status']=='paused' and not s['speaker']['active'])
        receipt['output_stopped']=True
        (ROOT/'local/idle-pause-resume.json').write_text(json.dumps(receipt,indent=2))
        print(json.dumps(receipt))


if __name__=='__main__':main()
