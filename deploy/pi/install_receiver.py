"""Install a locally built, checksum-verified ARM64 receiver; never enables audio."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys


def install(source,digest,home):
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Receiver checksum mismatch')
    if len(raw)<64 or raw[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(raw[18:20],'little')!=183:raise ValueError('Expected a Linux ARM64 executable')
    directory=home/'.local/share/echo-display/runtime';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=directory/'echo-librespot';temporary=directory/'echo-librespot.new';previous=directory/'echo-librespot.previous'
    if any(p.is_symlink() for p in (directory,target,temporary,previous)):raise ValueError('Receiver paths must not be symbolic links')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o700)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        if target.exists():shutil.copy2(target,previous)
        temporary.replace(target)
    finally:temporary.unlink(missing_ok=True)
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--binary',required=True,type=Path);parser.add_argument('--sha256',required=True);args=parser.parse_args()
    if sys.platform!='linux' or os.geteuid()==0:raise SystemExit('Run as the normal Pi desktop user, without sudo')
    install(args.binary,args.sha256,Path.home());print('Pi receiver installed. Playback remains disabled until configured in Display Settings.')


if __name__=='__main__':main()
