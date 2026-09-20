"""Bounded recovery envelopes and encrypted photo blobs; no live-host operations."""
import base64
import hashlib
import json
from pathlib import Path
import re
import zipfile

LEGACY_FILES=('echo-settings.json','echo-memory.json','echo-routines.json','echo-household.json',
              'echo-schedules.json','echo-displays.json','echo-experiences.json','home-access.json',
              'echo-media.json','speaker-selection.json','timers.json','spotify-credentials.json',
              'remote-agent.json','host-migration.json')
FILES=(*LEGACY_FILES,'echo-announcements.json','echo-calendar-receipts.json','echo-doorbells.json','echo-group-music.json')
LIMITS={'echo-displays.json':1_000_000,'echo-schedules.json':1_500_000,'echo-household.json':800_000,
        'echo-announcements.json':2_000_000,'echo-calendar-receipts.json':4_000_000}
MAX_ENVELOPE=24_000_000
MAX_PHOTO=6_000_000
MAX_ARCHIVE=MAX_ENVELOPE+60*MAX_PHOTO+100_000
ENVELOPE='recovery.dpapi'


def photo_name(name):
    return isinstance(name,str) and bool(re.fullmatch(r'display-photos/[a-f0-9]{32}\.photo',name))


def checked_blob(raw,item,limit):
    if len(raw)>limit or hashlib.sha256(raw).hexdigest()!=item.get('sha256'):
        raise ValueError('Damaged recovery file')
    return raw


def validate(payload):
    if not isinstance(payload,dict) or payload.get('kind')!='echo-remote' or payload.get('version') not in (1,2):
        raise ValueError('Unsupported recovery archive')
    allowed=LEGACY_FILES if payload['version']==1 else FILES
    if not isinstance(payload.get('files'),dict) or set(payload['files'])-set(allowed):
        raise ValueError('Unexpected recovery file')
    for name,item in payload['files'].items():
        raw=base64.b64decode(item['data'],validate=True)
        json.loads(checked_blob(raw,item,LIMITS.get(name,500_000)))
    bootstrap=payload.get('bootstrap',{})
    if any(not isinstance(bootstrap.get(n),dict) for n in ('api','agent')):
        raise ValueError('Invalid recovery bootstrap')
    if len(base64.b64decode(bootstrap['api']['storage_key'],validate=True))!=32:
        raise ValueError('Invalid storage key')
    photos=payload.get('photos',{})
    if (not isinstance(photos,dict) or len(photos)>60 or
            payload['version']==1 and photos or any(not photo_name(n) for n in photos)):
        raise ValueError('Invalid recovery album')
    for item in photos.values():
        if (type(item.get('size')) is not int or not 0<item['size']<=MAX_PHOTO or
                not isinstance(item.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',item['sha256'])):
            raise ValueError('Invalid photo descriptor')
    return payload


def read_archive(path,protector):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>MAX_ARCHIVE:raise ValueError('Recovery archive is too large or linked')
    if not zipfile.is_zipfile(path):
        if path.stat().st_size>4_000_000:raise ValueError('Legacy recovery archive is too large')
        return validate(json.loads(protector.decrypt(path.read_bytes())))
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist()
        if len(entries)>61 or len({i.filename for i in entries})!=len(entries):raise ValueError('Unexpected archive entries')
        envelope=archive.getinfo(ENVELOPE)
        if envelope.file_size>MAX_ENVELOPE or envelope.compress_type!=zipfile.ZIP_STORED:raise ValueError('Invalid envelope')
        payload=validate(json.loads(protector.decrypt(archive.read(envelope))))
        if payload['version']!=2 or set(archive.namelist())!={ENVELOPE,*payload.get('photos',{})}:
            raise ValueError('Archive inventory does not match its protected manifest')
        for name,item in payload.get('photos',{}).items():
            entry=archive.getinfo(name)
            if entry.file_size!=item['size'] or entry.compress_type!=zipfile.ZIP_STORED:raise ValueError('Invalid photo entry')
            checked_blob(archive.read(entry),item,MAX_PHOTO)
    return payload


def read_photo(path,name,item):
    if not photo_name(name):raise ValueError('Invalid photo path')
    with zipfile.ZipFile(path) as archive:
        entry=archive.getinfo(name)
        if entry.file_size!=item['size'] or entry.file_size>MAX_PHOTO or entry.compress_type!=zipfile.ZIP_STORED:
            raise ValueError('Invalid photo entry')
        return checked_blob(archive.read(entry),item,MAX_PHOTO)


def write_archive(path,payload,protector,reader):
    """Only the protected envelope and already encrypted photos reach disk."""
    validate(payload)
    if payload['version']!=2:raise ValueError('Write the current archive format')
    sealed=protector.encrypt(json.dumps(payload).encode())
    if len(sealed)>MAX_ENVELOPE:raise ValueError('Recovery envelope is too large')
    path=Path(path)
    # Exclusive creation: an earlier recovery point is never overwritten.
    with path.open('xb') as stream:
        try:
            with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED) as archive:
                archive.writestr(ENVELOPE,sealed)
                for name,item in payload.get('photos',{}).items():
                    raw=checked_blob(reader(name),item,MAX_PHOTO)
                    if len(raw)!=item['size']:raise ValueError('Photo changed during backup')
                    archive.writestr(name,raw)
        except Exception:
            stream.close();path.unlink();raise
