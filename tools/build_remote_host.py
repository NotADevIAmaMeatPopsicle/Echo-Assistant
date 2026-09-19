"""Build the Linux host with a narrow generated context, excluding all local data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import deployment
from tools.fetch_native_sources import fetch
from tools.release_guard import PRIVATE,FORBIDDEN_SUFFIXES,PATTERNS

EXTRA=(
    *('config/'+name for name in ('tts-runtime.lock.txt','tts-models.json','host-linux.lock.txt','tts-linux.lock.txt','stt-linux.lock.txt')),
    *('tools/'+name for name in ('prepare_tts.py','download_tts_models.py','check_tts.py','build_receiver.py','receiver_events.rs')),
    'deploy/host/bootstrap.py','deploy/host/build_aec.py','deploy/host/Dockerfile','deploy/host/.dockerignore',
)


def sources(root):
    git=lambda *args:subprocess.check_output(['git','-C',str(root),*args])
    if Path(git('rev-parse','--show-toplevel').decode().strip()).resolve()!=root:
        raise ValueError('Build from the Echo Git checkout')
    if git('ls-files','--others','--exclude-standard','--','backend','web'):
        raise ValueError('Review and track new backend/web source before packaging it')
    names=set(git('ls-files','-z','--','backend','web').decode().strip('\0').split('\0'))|set(EXTRA)
    content={}
    for name in sorted(names):
        path=root/name
        if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in (path,*path.parents) if p!=root):
            raise ValueError('Build source must remain inside the checkout: '+name)
        if set(Path(name).parts)&PRIVATE or path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.startswith(('.env','secrets.')):
            raise ValueError('Private artifact in build source: '+name)
        raw=path.read_bytes()
        if any(pattern.search(raw) for pattern in PATTERNS.values()):
            raise ValueError('Credential or personal path in build source: '+name)
        content[name]=raw
    return content

def stage(root=ROOT):
    root=Path(root).resolve();target=root/'deploy/host/context'
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError('Generated context must remain inside the checkout')
    content=sources(root)
    fetch(root)  # Explicit build command only; cached sources are checksum-verified.
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.echo-stage-',dir=target.parent) as temporary:
        fresh=Path(temporary)/'context';fresh.mkdir()
        manifest={}
        for name,raw in content.items():
            destination=Path(name).name if name in {'deploy/host/Dockerfile','deploy/host/.dockerignore'} else name
            path=fresh/destination;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            manifest[destination]=hashlib.sha256(raw).hexdigest()
        for filename in ('librespot-0.8.0.crate','aec_audio_processing-1.0.1.tar.gz'):
            path=fresh/'native'/filename;path.parent.mkdir(exist_ok=True)
            shutil.copyfile(root/'local/runtime'/filename,path)
            manifest['native/'+filename]=hashlib.sha256(path.read_bytes()).hexdigest()
        (fresh/'context-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        previous=None
        if target.exists():
            backups=root/'local/build-context-backups'
            if not backups.resolve().is_relative_to(root):raise ValueError('Context backup must remain inside the checkout')
            backups.mkdir(parents=True,exist_ok=True)
            previous=backups/uuid.uuid4().hex
            target.rename(previous)  # Preserve old generated files outside the new image.
        try:fresh.rename(target)
        except OSError:
            if previous is not None:previous.rename(target)
            raise
    return target

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-only',action='store_true',help='Prepare a clean context without invoking Docker')
    args=parser.parse_args();target=stage()
    print('Prepared reviewed host context:',target)
    if not args.stage_only:
        subprocess.run(['docker','--context',deployment.docker_context(),'compose','-f',str(ROOT/'deploy/host/compose.yaml'),'build','api'],check=True)
