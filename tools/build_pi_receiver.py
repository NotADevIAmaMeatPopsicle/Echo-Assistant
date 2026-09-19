"""Build the Pi receiver on a Docker host without sending the private workspace."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
from build_receiver import SHA256,VERSION

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--docker-context');args=parser.parse_args()
    output=ROOT/'output/pi-receiver';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='echo-pi-build-',dir=ROOT/'output') as temporary:
        stage=Path(temporary)
        for name in ('tools/build_receiver.py','tools/receiver_events.rs','deploy/pi/receiver.Dockerfile'):
            target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
        cached=ROOT/f'local/runtime/librespot-{VERSION}.crate'
        raw=cached.read_bytes() if cached.exists() else urllib.request.urlopen(f'https://static.crates.io/crates/librespot/librespot-{VERSION}.crate',timeout=30).read(4_000_000)
        if hashlib.sha256(raw).hexdigest()!=SHA256:raise SystemExit('Pinned source checksum mismatch')
        archive=stage/f'local/runtime/librespot-{VERSION}.crate';archive.parent.mkdir(parents=True);archive.write_bytes(raw)
        command=['docker']+(['--context',args.docker_context] if args.docker_context else [])
        subprocess.run(command+['build','--file',str(stage/'deploy/pi/receiver.Dockerfile'),'--output','type=local,dest='+str(output),str(stage)],check=True)
    digest=hashlib.sha256((output/'echo-librespot').read_bytes()).hexdigest()
    (output/'SHA256SUMS').write_text(digest+'  echo-librespot\n',encoding='utf-8');print('Pi receiver SHA256: '+digest)


if __name__=='__main__':main()
