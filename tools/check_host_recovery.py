"""Rehearse a fresh API install, restart and archive restore in disposable Docker containers.

Requires an already-built Echo image. No published ports, network, device mounts,
production volumes, provider calls or live credentials. The Hermes service and
Windows Scheduled Task recovery are not exercised by this check.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.settings import WindowsProtector
from backend.linux_protection import LinuxProtector
from tools.backup_remote import COLLECT,PHOTO
from tools.recovery_archive import FILES,LIMITS,read_archive,write_archive,read_photo
from tools.recovery_restore import SCRIPT

LABEL='org.echo.recovery-check'
PROBE=r'''
import hashlib,io,json,sys,time,urllib.request,urllib.error
from pathlib import Path
data=json.load(sys.stdin);phase=data['phase'];proof=data.get('proof')
token=Path('/run/echo/api-token').read_text()
def request(path,body=None,method='GET',auth=None,content='application/json'):
    raw=body if isinstance(body,bytes) else json.dumps(body).encode() if body is not None else None
    q=urllib.request.Request('http://127.0.0.1:8768'+path,data=raw,method=method,
        headers={'Authorization':auth or 'Bearer '+token,'Content-Type':content,'X-Echo-Request':'1'})
    with urllib.request.urlopen(q,timeout=5) as r:
        raw=r.read();return json.loads(raw) if r.headers.get_content_type()=='application/json' else raw
deadline=time.monotonic()+35
while True:
    try:request('/health');break
    except (OSError,ValueError):
        if time.monotonic()>deadline:raise RuntimeError('Fresh API did not start')
        time.sleep(.3)
assert not Path('/dev/snd').exists()
if phase=='seed':
    assert request('/v1/household')['items']==[] and request('/v1/display/photos')['items']==[]
    code=request('/v1/displays/pairing',{'name':'Synthetic study display'},'POST')['code']
    paired=request('/v1/displays/enroll',{'code':code},'POST')
    note=request('/v1/household',{'revision':0,'kind':'notes','text':'Synthetic recovery note'},'POST')['items'][0]
    from PIL import Image
    image=io.BytesIO();Image.new('RGB',(12,12),(20,110,120)).save(image,format='PNG')
    photo=request('/v1/display/photos',image.getvalue(),'POST',content='image/png')['id']
    rooms=request('/v1/audio/rooms')
    request('/v1/audio/rooms',{'revision':rooms['revision'],'endpoints':[{'id':paired['id'],'room':'Study','enabled':True,'calls_enabled':True}]},'PUT')
    from backend.calendar_events import CalendarWriter
    from backend.settings import default_protector
    receipts={'a'*64:{'digest':'b'*64,'status':'accepted'}}
    CalendarWriter(None,Path('/opt/echo'),default_protector()).commit(receipts)
    proof={'paired':paired,'note':note['id'],'photo':photo,
           'photo_hash':hashlib.sha256(request('/v1/display/photos/'+photo)).hexdigest()}
else:
    assert any(n['id']==proof['note'] and n['text']=='Synthetic recovery note' for n in request('/v1/household')['items'])
    assert hashlib.sha256(request('/v1/display/photos/'+proof['photo'])).hexdigest()==proof['photo_hash']
    rooms=request('/v1/audio/rooms')['items']
    assert any(n['id']==proof['paired']['id'] and n['room']=='Study' and n['calls_enabled'] for n in rooms)
    from backend.calendar_events import CalendarWriter
    from backend.settings import default_protector
    writer=CalendarWriter(None,Path('/opt/echo'),default_protector())
    assert not writer.error and writer.receipts['a'*64]['status']=='accepted'
auth='Display '+proof['paired']['credential']
request('/v1/household',auth=auth)
try:request('/v1/settings',auth=auth)
except urllib.error.HTTPError as e:assert e.code==403
else:raise AssertionError('Paired display gained owner access')
print(json.dumps(proof))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',required=True)
    parser.add_argument('--image',required=True,help='Existing image tag or ID; never built or pulled by this check')
    args=parser.parse_args()
    prefix='echo-recovery-check-'+secrets.token_hex(6)
    containers=[];volumes=[]
    def docker(*args_,data=None,timeout=60):
        p=subprocess.run(['docker','--context',args.context,*args_],input=data,capture_output=True,timeout=timeout)
        if p.returncode:raise RuntimeError('Disposable Docker operation failed: '+args_[0])
        return p.stdout
    image=json.loads(docker('image','inspect',args.image))[0]['Id']
    payload={'storage_key':base64.b64encode(os.urandom(32)).decode(),'api_token':secrets.token_urlsafe(40),
             'home_tools_token':secrets.token_urlsafe(40),'settings':{},'provider_key':None,
             'home_access':{'default_access':'read','devices':{}}}
    def owned(kind,name):
        info=json.loads(docker(kind,'inspect',name))[0]
        labels=info.get('Labels',{}) if kind=='volume' else info['Config'].get('Labels',{})
        if labels.get(LABEL)!=prefix:raise RuntimeError('Refusing to modify an unowned Docker resource')
    def create(suffix):
        volume=prefix+'-'+suffix+'-data'
        check=subprocess.run(['docker','--context',args.context,'volume','inspect',volume],capture_output=True)
        if check.returncode==0:raise RuntimeError('Refusing to reuse a volume')
        docker('volume','create','--label',LABEL+'='+prefix,volume);volumes.append(volume)
        name=prefix+'-'+suffix
        docker('create','--name',name,'--label',LABEL+'='+prefix,'--network','none','--read-only',
               '--log-driver','none','--memory','512m','--cpus','1','--pids-limit','96',
               '--tmpfs','/run/echo:uid=10000,gid=10000,mode=0700,size=16m',
               '--tmpfs','/tmp:mode=1777,size=64m','--tmpfs','/models:uid=10000,gid=10000,mode=0700,size=1m',
               '--mount','type=volume,source='+volume+',target=/opt/echo/local',
               '-e','ECHO_DEPLOYMENT_MODE=validation','-e','ECHO_VOICE_ENABLED=0',image)
        containers.append(name);return name
    def start(name):
        owned('container',name);docker('start',name)
        inject="import json,os,sys;raw=json.load(sys.stdin);f=os.open('/run/echo/bootstrap.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.write(f,json.dumps(raw).encode());os.close(f)"
        docker('exec','-i',name,'python','-c',inject,data=json.dumps(payload).encode())
    def probe(name,phase,proof=None):
        return json.loads(docker('exec','-i',name,'python','-c',PROBE,data=json.dumps({'phase':phase,'proof':proof}).encode(),timeout=45))
    try:
        first=create('source');start(first);proof=probe(first,'seed')
        print('Fresh isolated API: enrollment, note, photo and room settings created.',flush=True)
        owned('container',first);docker('stop','--time','15',first);start(first);probe(first,'verify',proof)
        print('Container restart: saved data and scoped display access survived.',flush=True)
        saved=json.loads(docker('exec','-i',first,'python','-c',COLLECT,data=json.dumps({'files':FILES,'limits':LIMITS}).encode()))
        archive_data={'kind':'echo-remote','version':2,'created_at':1.0,**saved,'bootstrap':{'api':payload,'agent':{}}}
        with TemporaryDirectory(prefix='echo-recovery-check-') as directory:
            directory=Path(directory)
            if os.name=='nt':protector=WindowsProtector()
            else:
                key=directory/'archive-key';key.write_bytes(os.urandom(32));key.chmod(0o600);protector=LinuxProtector(key)
            archive=directory/'synthetic.echo-backup'
            write_archive(archive,archive_data,protector,lambda name:docker('exec','-i',first,'python','-c',PHOTO,data=json.dumps(name).encode()))
            restored=read_archive(archive,protector)
            second=create('restored');docker('start',second) # Bootstrap waits while the empty volume is restored.
            command=['docker','--context',args.context,'exec','-i',second,'python','-c',SCRIPT]
            with subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE) as p:
                header={'names':FILES,'limits':LIMITS,'files':restored['files'],'photos':restored['photos'],'storage_key':payload['storage_key']}
                p.stdin.write(json.dumps(header).encode()+b'\n')
                for name,item in restored['photos'].items():
                    p.stdin.write(json.dumps({'name':name,'data':base64.b64encode(read_photo(archive,name,item)).decode()}).encode()+b'\n')
                p.stdin.close()
                p.stdin=None
                try:_,error=p.communicate(timeout=20)
                except subprocess.TimeoutExpired:
                    p.kill();p.communicate();raise
                result=p.returncode
                if result:raise RuntimeError('Synthetic restore failed: '+error.decode()[-1200:])
            # Start injects the same storage key and credentials into the new runtime.
            start(second);probe(second,'verify',proof)
        print('PASS: fresh-volume restore retained the photo, note, pairing, room policy and calendar receipt. No network or audio used.',flush=True)
    finally:
        for name in reversed(containers):
            owned('container',name);docker('rm','--force',name)
        for name in reversed(volumes):
            owned('volume',name);docker('volume','rm',name)


if __name__=='__main__':main()
