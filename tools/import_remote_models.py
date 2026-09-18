"""Copy only the existing reviewed model directories to Echo's own Docker volume."""
from backend import deployment
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[1]
NAMES=('pocket-tts-english-official','kokoro-82m-official','vosk-model-small-en-us-0.15')
IMAGE='python:3.13-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e'

def docker(*args,**kwargs):
    return subprocess.run(['docker','--context',deployment.docker_context(),*args],check=True,**kwargs)

def manifest():
    result={}
    for name in NAMES:
        directory=ROOT/'local/models'/name
        if not directory.is_dir():raise RuntimeError('Prepare the reviewed local models before importing')
        for path in directory.rglob('*'):
            if path.is_symlink():raise RuntimeError('Model import does not follow symbolic links')
            if path.is_file():
                with path.open('rb') as stream:result[path.relative_to(ROOT/'local/models').as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
    return result

def check(expected):
    script="""import json,hashlib,sys
from pathlib import Path
root=Path('/models'); wanted=json.load(sys.stdin); missing=bad=0
for name,digest in wanted.items():
 p=root/name
 if not p.is_file():missing+=1;continue
 with p.open('rb') as f:bad+=hashlib.file_digest(f,'sha256').hexdigest()!=digest
extra=sum(p.is_file() and p.relative_to(root).as_posix() not in wanted for p in root.rglob('*'))
print(json.dumps({'missing':missing,'different':bad,'extra':extra}))
"""
    result=docker('run','--rm','-i','--network','none','--mount','type=volume,src=echo_models,dst=/models,readonly',
        IMAGE,'python','-c',script,input=json.dumps(expected).encode(),capture_output=True)
    return json.loads(result.stdout)

def main():
    expected=manifest()
    inspected=subprocess.run(['docker','--context',deployment.docker_context(),'volume','inspect','echo_models'],capture_output=True)
    if inspected.returncode:
        docker('volume','create','--label','org.echo.owner=round-voice','echo_models',capture_output=True)
    elif json.loads(inspected.stdout)[0].get('Labels',{}).get('org.echo.owner')!='round-voice':
        raise RuntimeError('The model volume is not owned by this Echo setup')
    state=check(expected)
    if state['different'] or state['extra']:raise RuntimeError('The model volume differs; its existing data was preserved')
    if state['missing']:
        name='echo-model-import-'+uuid.uuid4().hex[:10]
        script="import os; from pathlib import Path; [os.chmod(p,0o555 if p.is_dir() else 0o444) for p in Path('/models').rglob('*') if not p.is_symlink()]"
        docker('create','--name',name,'--label','org.echo.owner=round-voice','--user','0',
            '--mount','type=volume,src=echo_models,dst=/models',IMAGE,'python','-c',script,capture_output=True)
        try:
            for directory in NAMES:docker('cp',str(ROOT/'local/models'/directory),name+':/models/'+directory)
            docker('start','-a',name,capture_output=True)
        finally:docker('rm',name,capture_output=True)
        if any(check(expected).values()):raise RuntimeError('Model copy verification failed')
    print(json.dumps({'verified_files':len(expected),'volume':'echo_models','downloaded_models':False}))

if __name__=='__main__':main()
