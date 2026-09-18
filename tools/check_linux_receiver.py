"""Silent native receiver check: no account, cache reuse, playback or microphone."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
from tempfile import TemporaryDirectory
import urllib.request


def main():
    binary=os.environ.get('ECHO_RECEIVER_BINARY','/usr/local/bin/echo-librespot')
    address=socket.gethostbyname(socket.gethostname())
    # Use an ephemeral port so the check can never replace the user's receiver.
    with socket.socket() as probe:
        probe.bind(('0.0.0.0',0)); port=probe.getsockname()[1]
    with TemporaryDirectory(prefix='echo-receiver-') as folder, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as events:
        events.bind(('127.0.0.1',0));events.settimeout(10)
        key=secrets.token_urlsafe(32)
        env=dict(os.environ,ROUND_VOICE_EVENT_KEY=key,ROUND_VOICE_EVENT_PORT=str(events.getsockname()[1]),RUST_LOG='error')
        child=subprocess.Popen([binary,'--name','Echo validation','--backend','pipe','--format','S16',
            '--disable-audio-cache','--autoplay','off','--system-cache',folder,'--tmp',folder,
            '--zeroconf-interface',address,'--zeroconf-port',str(port),'--onevent','round-voice-events'],
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
        try:
            event=json.loads(events.recv(8192));assert event.get('key')==key and event.get('event')=='receiver_ready'
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline=time.monotonic()+10
            while True:
                try:
                    with opener.open(f'http://127.0.0.1:{port}/?action=getInfo',timeout=1) as response: info=json.load(response)
                    break
                except OSError:
                    if time.monotonic()>deadline: raise
                    time.sleep(.1)
            assert info.get('status')==101 and info.get('remoteName')=='Echo validation'
            assert not info.get('activeUser')
            child.communicate(b'shutdown\n',timeout=8)
            assert child.returncode==0
            print(json.dumps({'native_event':'receiver_ready','get_info':101,'account_connected':False,'shutdown_exit':0,'played_audio':False}))
        finally:
            if child.poll() is None: child.kill();child.wait(timeout=3)


if __name__=='__main__': main()
