"""Build the Linux host with a narrow generated context, excluding all local data."""
from pathlib import Path
import shutil
import subprocess
import sys
from fetch_native_sources import fetch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import deployment
TARGET=ROOT/'deploy/host/context'

def stage():
    fetch(ROOT)
    TARGET.mkdir(exist_ok=True)
    for directory in ('backend','web'):
        shutil.copytree(ROOT/directory,TARGET/directory,dirs_exist_ok=True,
            ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for directory in ('config','tools','deploy/host','native'):(TARGET/directory).mkdir(parents=True,exist_ok=True)
    for filename in ('tts-runtime.lock.txt','tts-models.json','host-linux.lock.txt','tts-linux.lock.txt','stt-linux.lock.txt'):
        shutil.copyfile(ROOT/'config'/filename,TARGET/'config'/filename)
    for filename in ('prepare_tts.py','download_tts_models.py','check_tts.py','build_receiver.py','receiver_events.rs'):
        shutil.copyfile(ROOT/'tools'/filename,TARGET/'tools'/filename)
    for filename in ('Dockerfile','.dockerignore'):shutil.copyfile(ROOT/'deploy/host'/filename,TARGET/filename)
    shutil.copyfile(ROOT/'deploy/host/bootstrap.py',TARGET/'deploy/host/bootstrap.py')
    shutil.copyfile(ROOT/'deploy/host/build_aec.py',TARGET/'deploy/host/build_aec.py')
    for filename in ('librespot-0.8.0.crate','aec_audio_processing-1.0.1.tar.gz'):
        shutil.copyfile(ROOT/'local/runtime'/filename,TARGET/'native'/filename)

if __name__=='__main__':
    stage()
    subprocess.run(['docker','--context',deployment.docker_context(),'compose','-f',str(ROOT/'deploy/host/compose.yaml'),'build','api'],check=True)
