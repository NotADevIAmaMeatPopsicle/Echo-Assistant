"""Explicit, isolated Vosk install. Never enables the microphone or changes pairing."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile

NAME='vosk-model-small-en-us-0.15'
PACKAGES=('vosk==0.3.45','cffi==2.1.1','pycparser==3.0','requests==2.34.2',
          'charset_normalizer==3.5.1','idna==3.20','urllib3==2.8.0','certifi==2026.7.22',
          'tqdm==4.70.1','websockets==17.1','srt==3.5.3')
SIZE=41205931
SHA256='30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498'


def install_model(archive, destination):
    if archive.stat().st_size!=SIZE or hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:
        raise ValueError('Wake model archive does not match the pinned release')
    if destination.exists():
        if destination.is_symlink():raise ValueError('Use a regular model directory')
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                if item.is_dir():continue
                relative=PurePosixPath(item.filename).relative_to(NAME)
                if '..' in relative.parts or not (destination/relative).is_file():raise ValueError('Existing wake model is incomplete')
                if hashlib.sha256((destination/relative).read_bytes()).digest()!=hashlib.sha256(source.read(item)).digest():raise ValueError('Existing wake model was modified; preserve and inspect it')
        return
    with tempfile.TemporaryDirectory(prefix='wake-model-',dir=destination.parent) as temporary:
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                path=PurePosixPath(item.filename)
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!=NAME or '\\' in item.filename or (item.external_attr>>16)&0o170000==0o120000:
                    raise ValueError('Unexpected model archive entry')
            source.extractall(temporary)
        (Path(temporary)/NAME).rename(destination)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    if sys.platform!='linux':raise SystemExit('Install this runtime on the Pi using Python 3.11 or later.')
    runtime=Path.home()/'.local/share/echo-display/runtime';runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
    if shutil.disk_usage(runtime).free<350*1024*1024:raise SystemExit('Free at least 350 MB before installing the wake runtime.')
    environment=runtime/'voice'
    if environment.is_symlink():raise ValueError('Use a private runtime directory')
    if not (environment/'bin/python').is_file():venv.EnvBuilder(with_pip=True).create(environment)
    python=str(environment/'bin/python')
    subprocess.run([python,'-m','pip','install','--disable-pip-version-check','--no-cache-dir',*PACKAGES],check=True)
    with tempfile.TemporaryDirectory(prefix='wake-download-',dir=runtime) as temporary:
        archive=args.archive
        if archive is None:
            archive=Path(temporary)/'model.zip'
            with urllib.request.urlopen('https://alphacephei.com/vosk/models/'+NAME+'.zip',timeout=30) as response,archive.open('wb') as output:
                total=0
                while block:=response.read(1024*1024):
                    total+=len(block)
                    if total>SIZE:raise ValueError('Wake model download exceeds its expected size')
                    output.write(block)
        install_model(archive,runtime/'voice-model')
    subprocess.run([python,'-c',"from vosk import Model,SetLogLevel;import sys;SetLogLevel(-1);Model(sys.argv[1]);print('Wake model loaded; no audio devices opened.')",str(runtime/'voice-model')],check=True)
    print('Pi wake runtime installed. Run setup.py --install for the current bundle, then choose the microphone in Settings. Listening remains disabled.')


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError):raise SystemExit('Wake installation failed. Existing pairing and voice settings were preserved.') from None
