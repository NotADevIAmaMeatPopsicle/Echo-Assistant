"""Copy only the existing reviewed model directories to Echo's own Docker volume."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import deployment
NAMES=('pocket-tts-english-official','kokoro-82m-official','vosk-model-small-en-us-0.15')
OPTIONAL=('faster-whisper-base.en',)
IMAGE='python:3.13-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e'

def docker(*args,context=None,**kwargs):
    return subprocess.run(['docker','--context',context or deployment.docker_context(),*args],check=True,**kwargs)

def manifest(source=None):
    source=Path(source) if source is not None else ROOT/'local/models'
    if source.is_symlink() or (hasattr(source,'is_junction') and source.is_junction()):
        raise RuntimeError('Model import does not follow a linked source directory')
    result={}
    names = NAMES + tuple(name for name in OPTIONAL if (source/name).is_dir())
    for name in names:
        directory=source/name
        if directory.is_symlink() or (hasattr(directory,'is_junction') and directory.is_junction()):
            raise RuntimeError('Model import does not follow linked directories')
        if not directory.is_dir():raise RuntimeError('Prepare the reviewed local models before importing')
        for path in directory.rglob('*'):
            if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):raise RuntimeError('Model import does not follow linked paths')
            if path.is_file():
                with path.open('rb') as stream:result[path.relative_to(source).as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
    return result

def check(expected,context=None):
    script="""import json,hashlib,sys
from pathlib import Path
import sys
root=Path('/models'); wanted=json.load(sys.stdin); missing=bad=0; missing_dirs=set()
if any(p.is_symlink() for p in root.rglob('*')):raise ValueError('Model volume contains linked paths')
present_dirs={p.name for p in root.iterdir()}
for name,digest in wanted.items():
 p=root/name
 if not p.is_file():missing+=1;missing_dirs.add(Path(name).parts[0]);continue
 with p.open('rb') as f:bad+=hashlib.file_digest(f,'sha256').hexdigest()!=digest
extra=sum(p.is_file() and p.relative_to(root).as_posix() not in wanted for p in root.rglob('*'))
print(json.dumps({'missing':missing,'different':bad,'extra':extra,'missing_directories':sorted(missing_dirs),
 'partial_directories':sorted(missing_dirs & present_dirs)}))
"""
    result=docker('run','--rm','-i','--network','none','--mount','type=volume,src=echo_models,dst=/models,readonly',
        IMAGE,'python','-c',script,input=json.dumps(expected).encode(),capture_output=True,context=context)
    return json.loads(result.stdout)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'local/models',help='Directory holding the reviewed model subdirectories')
    parser.add_argument('--context',help='Explicit Docker context; defaults to Echo deployment settings')
    args=parser.parse_args(argv);source=args.source;context=args.context or deployment.docker_context()
    expected=manifest(source)
    inspected=subprocess.run(['docker','--context',context,'volume','inspect','echo_models'],capture_output=True)
    if inspected.returncode:
        docker('volume','create','--label','org.echo.owner=round-voice','echo_models',capture_output=True,context=context)
    elif json.loads(inspected.stdout)[0].get('Labels',{}).get('org.echo.owner')!='round-voice':
        raise RuntimeError('The model volume is not owned by this Echo setup')
    state=check(expected,context)
    if state['different'] or state['extra']:raise RuntimeError('The model volume differs; its existing data was preserved')
    if state['partial_directories']:raise RuntimeError('The model volume has partially populated directories; existing data was preserved. Restore into a deliberately prepared empty model volume.')
    if state['missing']:
        name='echo-model-import-'+uuid.uuid4().hex[:10]
        script="import os; from pathlib import Path; [os.chmod(p,0o555 if p.is_dir() else 0o444) for p in Path('/models').rglob('*') if not p.is_symlink()]"
        docker('create','--name',name,'--label','org.echo.owner=round-voice','--user','0',
            '--mount','type=volume,src=echo_models,dst=/models',IMAGE,'python','-c',script,capture_output=True,context=context)
        try:
            for directory in state['missing_directories']:docker('cp',str(source/directory),name+':/models/'+directory,context=context)
            docker('start','-a',name,capture_output=True,context=context)
        finally:docker('rm',name,capture_output=True,context=context)
        verified = check(expected,context)
        if any(verified[key] for key in ('missing', 'different', 'extra')):
            raise RuntimeError('Model copy verification failed')
    print(json.dumps({'verified_files':len(expected),'volume':'echo_models','downloaded_models':False}))

if __name__=='__main__':main()
