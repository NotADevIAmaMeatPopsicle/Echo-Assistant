"""Isolated LiveKit token/room rehearsal. No published ports, real accounts or media.

Requires Docker and an existing Echo host image. The server image is digest-pinned.
The companion container shares only the rehearsal server's isolated network stack.
"""
import argparse
import base64
import json
import re
from pathlib import Path
import secrets
import subprocess
import uuid

SERVER='livekit/livekit-server@sha256:6fd3b7088874c4d119160dd688798dfec852bc014786d392caad15f6f63912a3'
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--context',required=True);p.add_argument('--host-image',required=True)
    args=p.parse_args();prefix=['docker','--context',args.context]
    name='echo-call-check-'+uuid.uuid4().hex[:12];key='test-'+secrets.token_hex(12);secret=secrets.token_hex(32)
    def docker(*argv,**kw):return subprocess.run(prefix+list(argv),check=True,capture_output=True,text=True,**kw)
    source=base64.b64encode((ROOT/'backend/calling.py').read_bytes()).decode()
    code=r'''
import base64,httpx,json,os,socket,sys,time,types
from urllib.parse import urlencode
module=types.ModuleType('synthetic_calling');sys.modules[module.__name__]=module
exec(base64.b64decode(SOURCE),module.__dict__)
s=module.CallSettings(revision=0,enabled=True,url='wss://calls.example.com',api_key=KEY,api_secret=SECRET)
api=httpx.Client(base_url='http://127.0.0.1:7880',trust_env=False,timeout=5)
admin=module.jwt(s,'test-admin',{'roomCreate':True},time.time())
def rpc(method,body,token):
 return api.post('/twirp/livekit.RoomService/'+method,json=body,headers={'Authorization':'Bearer '+token})
for attempt in range(30):
 try:
  r=rpc('CreateRoom',{'name':'echo-synthetic','max_participants':2,'empty_timeout':120,'departure_timeout':10},admin)
  if r.status_code==200:break
 except httpx.TransportError:pass
 time.sleep(.25)
else:raise AssertionError('Rehearsal LiveKit did not start')
assert r.json()['name']=='echo-synthetic' and r.json()['max_participants']==2
grants={'roomJoin':True,'room':'echo-synthetic','canSubscribe':True,'canPublish':True,'canPublishData':False,'canPublishSources':['microphone','camera']}
token=module.jwt(s,'synthetic-peer',grants,time.time())
# An authenticated signalling handshake exercises the same claims as the browser.
# No SDP, microphone, camera or RTP packets are sent.
query=urlencode({'access_token':token,'sdk':'js','version':'2.22.3','protocol':'16','auto_subscribe':'1'})
with socket.create_connection(('127.0.0.1',7880),timeout=5) as sock:
 nonce=base64.b64encode(os.urandom(16)).decode()
 sock.sendall(('GET /rtc?'+query+' HTTP/1.1\r\nHost: 127.0.0.1:7880\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: '+nonce+'\r\n\r\n').encode())
 reply=b''
 while b'\r\n\r\n' not in reply:
  block=sock.recv(4096)
  if not block:break
  reply+=block
 assert reply.startswith(b'HTTP/1.1 101 '),'Provider rejected the scoped participant token'
assert rpc('DeleteRoom',{'room':'echo-synthetic'},token).status_code in {401,403}
assert rpc('DeleteRoom',{'room':'echo-synthetic'},admin).status_code==200
print(json.dumps({'server':'1.13.7','create_room':True,'participant_signalling':True,'participant_admin_denied':True,'delete_room':True,'audio':False,'ports_published':False}))
'''.replace('SOURCE',repr(source)).replace('KEY',repr(key)).replace('SECRET',repr(secret))
    try:
        docker('run','-d','--name',name,'--network','none','--label','echo.rehearsal=calling',SERVER,
               '--dev','--bind','127.0.0.1','--keys',key+': '+secret)
        result=docker('run','--rm','-i','--network','container:'+name,'--entrypoint','python',args.host_image,'-',input=code,timeout=90)
        print(result.stdout.strip())
    except subprocess.CalledProcessError as error:
        # Avoid echoing process arguments or signalling URLs containing test tokens.
        detail=(error.stderr or '')[-1800:].replace(key,'[test-key]').replace(secret,'[test-secret]')
        print(re.sub(r'eyJ[A-Za-z0-9_.-]+','[test-token]',detail))
        raise SystemExit('Calling provider rehearsal failed. No real call was attempted.') from None
    finally:
        subprocess.run(prefix+['rm','-f',name],capture_output=True,check=False)


if __name__=='__main__':main()
