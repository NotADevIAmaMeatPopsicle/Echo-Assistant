"""Stage a stopped host's saved data before replacing it; called by backup_remote."""
import base64
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


def restore(root, stream):
    data=json.loads(stream.readline(32_000_001))
    names=data['names'];photos=data['photos'];files=data['files']
    if (not isinstance(names,list) or len(names)>32 or len(set(names))!=len(names) or
            any(not re.fullmatch('[a-z][a-z0-9-]*\\.json',n) for n in names) or
            set(files)-set(names) or not isinstance(photos,dict) or len(photos)>60 or
            any(not re.fullmatch('display-photos/[a-f0-9]{32}\\.photo',n) for n in photos)):
        raise ValueError('Invalid restore inventory')
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('Invalid restore directory')
    album=root/'display-photos'
    if album.is_symlink() or album.exists() and not album.is_dir():raise ValueError('Invalid album directory')
    existing=list(album.glob('*.photo')) if album.exists() else []
    if any(p.is_symlink() or not p.is_file() or not re.fullmatch('[a-f0-9]{32}\\.photo',p.name) for p in existing):
        raise ValueError('Invalid existing photo')
    targets=set(names)|set(photos)|{'display-photos/'+p.name for p in existing}
    for name in targets:
        p=root/name
        if p.is_symlink() or p.exists() and not p.is_file():raise ValueError('Invalid restore target')
    # All bytes are validated and staged before the first live file changes.
    # These temporary files contain only the already protected app data.
    with tempfile.TemporaryDirectory(prefix='.echo-restore-',dir=root) as directory:
        stage=Path(directory)/'new';stage.mkdir(mode=0o700)
        old=Path(directory)/'old';old.mkdir(mode=0o700)
        for name,item in files.items():
            raw=base64.b64decode(item['data'],validate=True)
            if len(raw)>data['limits'].get(name,500_000) or hashlib.sha256(raw).hexdigest()!=item['sha256']:
                raise ValueError('Damaged restored file')
            json.loads(raw)
            if name=='echo-announcements.json':
                # A restored queue cannot prove what played after its snapshot.
                # Retain room permissions/history without replaying old deliveries.
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                cipher=AESGCM(base64.b64decode(data['storage_key'],validate=True))
                envelope=json.loads(raw);protected=base64.b64decode(envelope['protected'],validate=True)
                if not protected.startswith(b'ECHOAES1'):raise ValueError('Unsupported announcement encryption')
                context=b'Echo protected local data, version 1'
                saved=json.loads(cipher.decrypt(protected[8:20],protected[20:],context))
                for message in saved['messages']:
                    for delivery in message['deliveries']:
                        if delivery['status'] in ('queued','claimed'):
                            status='unknown' if delivery['status']=='claimed' else 'cancelled'
                            delivery.update(status=status,claim_hash='',claim_until=0.0,client='')
                nonce=os.urandom(12)
                envelope['protected']=base64.b64encode(b'ECHOAES1'+nonce+cipher.encrypt(nonce,json.dumps(saved).encode(),context)).decode()
                raw=json.dumps(envelope).encode()
            p=stage/name;p.write_bytes(raw);p.chmod(0o600)
        for expected,item in photos.items():
            message=json.loads(stream.readline(8_100_001))
            if message['name']!=expected:raise ValueError('Photo stream does not match the manifest')
            raw=base64.b64decode(message['data'],validate=True)
            if len(raw)!=item['size'] or len(raw)>6_000_000 or hashlib.sha256(raw).hexdigest()!=item['sha256']:
                raise ValueError('Damaged restored photo')
            p=stage/expected;p.parent.mkdir(mode=0o700,exist_ok=True);p.write_bytes(raw);p.chmod(0o600)
        if stream.read(1):raise ValueError('Unexpected restore data')
        # Preserve originals until the entire replacement succeeds. Roll back
        # ordinary I/O failures; the separately verified archive covers power loss.
        for name in targets:
            p=root/name
            if p.exists():
                saved=old/name;saved.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copy2(p,saved)
        changed=[]
        try:
            for name in sorted(targets):
                p=root/name;replacement=stage/name
                p.parent.mkdir(mode=0o700,exist_ok=True)
                if replacement.exists():replacement.replace(p);changed.append(name)
                elif p.exists():p.unlink();changed.append(name)
        except OSError:
            for name in reversed(changed):
                p=root/name;saved=old/name
                if saved.exists():saved.replace(p)
                else:p.unlink(missing_ok=True)
            raise


SCRIPT=('import base64,hashlib,json,os,re,shutil,tempfile,sys\nfrom pathlib import Path\n'+
        inspect.getsource(restore)+"\nrestore(Path('/opt/echo/local'),sys.stdin.buffer)\n")
