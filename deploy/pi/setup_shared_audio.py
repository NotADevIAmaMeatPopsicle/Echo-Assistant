"""Create an explicit ALSA mixer for simultaneous Pi music and voice playback.

Run as the desktop user with --card ALSA_CARD_NAME. This does not select an
output, enable a receiver, open audio hardware, or alter the system default.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil

BEGIN='# BEGIN ECHO SHARED OUTPUT'
END='# END ECHO SHARED OUTPUT'


def configure(home,card):
    if not re.fullmatch(r'[A-Za-z0-9_]{1,40}',card):raise ValueError('Use a named ALSA card from aplay -l')
    path=Path(home)/'.asoundrc'
    if path.is_symlink():raise ValueError('Inspect the existing ALSA symlink before changing it')
    old=path.read_text(encoding='utf-8') if path.exists() else ''
    if old.count(BEGIN)!=old.count(END) or old.count(BEGIN)>1:raise ValueError('Existing Echo mixer block is incomplete')
    key=int(hashlib.sha256(('echo:'+card).encode()).hexdigest()[:7],16)
    block=f'''{BEGIN}
pcm.echo_shared {{
    type plug
    slave.pcm {{
        type dmix
        ipc_key {key}
        ipc_key_add_uid true
        ipc_perm 0600
        slave {{
            pcm "hw:{card},0"
            rate 48000
            channels 2
            period_size 960
            buffer_size 3840
        }}
    }}
    hint {{
        show on
        ioid "Output"
        description "Echo shared speaker (music and voice)"
    }}
}}
{END}'''
    if BEGIN in old:
        start=old.index(BEGIN);end=old.index(END)+len(END)
        if end<start:raise ValueError('Existing Echo mixer block is invalid')
        content=old[:start]+block+old[end:]
    else:
        if re.search(r'\bpcm\.echo_shared\b',old):raise ValueError('An unmanaged echo_shared output already exists')
        content=old.rstrip()+'\n\n'+block+'\n'
    if content==old:return 'already configured'
    backup=path.with_name('.asoundrc.before-echo')
    if path.exists() and not backup.exists():shutil.copy2(path,backup)
    temporary=path.with_name('.asoundrc.echo-new')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:stream.write(content)
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
    return 'configured'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--card',required=True)
    print('Echo shared output:',configure(Path.home(),parser.parse_args().card))
