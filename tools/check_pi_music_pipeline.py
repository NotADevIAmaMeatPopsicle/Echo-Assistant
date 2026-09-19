"""Exercise Linux pipe transport with synthetic child processes, never ALSA/audio."""
from array import array
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from spotify import Spotify


def main():
    if sys.platform!='linux':raise SystemExit('This pipe check requires Linux')
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);record=root/'synthetic.pcm';commands=[]
        producer='''import os,socket,json,sys,time
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
s.sendto(json.dumps({'key':os.environ['ROUND_VOICE_EVENT_KEY'],'event':'playing','position_ms':'0'}).encode(),('127.0.0.1',int(os.environ['ROUND_VOICE_EVENT_PORT'])))
time.sleep(.1)
while True:
 sys.stdout.buffer.write(b'\\x10\\x27\\xf0\\xd8'*1024);sys.stdout.buffer.flush();time.sleep(.02)
'''
        sink="import sys\nfrom pathlib import Path\nf=Path(sys.argv[1]).open('wb',buffering=0)\nwhile block:=sys.stdin.buffer.read(4096):f.write(block)\n"
        def popen(command,**kwargs):
            commands.append(command)
            if command[0]=='aplay':return subprocess.Popen([sys.executable,'-c',sink,str(record)],**kwargs)
            assert command[0].endswith('echo-librespot')
            return subprocess.Popen([sys.executable,'-c',producer],**kwargs)
        receiver=Spotify(root,devices=lambda:[{'id':'synthetic','name':'No hardware'}],popen=popen)
        # A CI/container user has no desktop login's /run/user/<uid>. Keep this
        # synthetic receiver's volatile cache inside its temporary test home.
        temporary_directory=tempfile.TemporaryDirectory
        with patch('spotify.tempfile.TemporaryDirectory',side_effect=lambda **kw:temporary_directory(prefix=kw['prefix'],dir=root)):
            receiver.config.update(enabled=True,output='synthetic');receiver.start()
            try:
                deadline=time.monotonic()+5
                while not record.exists() or record.stat().st_size<4096:
                    if time.monotonic()>deadline:raise AssertionError('Synthetic PCM did not reach the output pipe')
                    time.sleep(.02)
                receiver.focus('a'*32,True);assert receiver.player is None;assert receiver.silenced
            finally:receiver.close()
        samples=array('h',record.read_bytes());assert samples and set(samples)=={200,-200}
        assert len(commands)==2;assert '--disable-credential-cache' in commands[0]
        assert not receiver.thread.is_alive()
        print('Linux receiver → gain → output pipe and focus shutdown passed. Synthetic processes only; no audio hardware.')


if __name__=='__main__':main()
