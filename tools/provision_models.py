"""Portable, hash-checked model inventory and non-overwriting local restoration."""
from __future__ import annotations

from tools.provision_error import ProvisionError

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from tools.import_remote_models import NAMES, OPTIONAL

MAX_MANIFEST = 16_000_000
MAX_BYTES = 1_000_000_000_000
RESERVED = re.compile(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)')


def runtime_files():
    catalog = json.loads((Path(__file__).resolve().parents[1] / 'config/tts-models.json').read_text())
    required = {model['directory'] + '/' + asset['path'] for model in catalog['models'] for asset in model['assets']}
    required.update('vosk-model-small-en-us-0.15/' + name for name in
                    ('am/final.mdl', 'conf/model.conf', 'conf/mfcc.conf', 'graph/Gr.fst', 'graph/HCLr.fst'))
    return required


def require_runtime(value):
    required = runtime_files()
    if any(name.startswith('faster-whisper-base.en/') for name in value['files']):
        required.update('faster-whisper-base.en/' + name for name in
                        ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'))
    if required - value['files'].keys() or any(value['files'][name]['size'] <= 0 for name in required):
        raise ProvisionError('Model manifest lacks required speech weights, configuration, voices or attribution files')


def unlinked(path):
    """Reject Windows junctions as well as symlinks, including parent paths."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ProvisionError('Model paths must not contain links or reparse points')
    return path


def member_name(name):
    if not isinstance(name, str) or len(name) > 240:
        raise ProvisionError('Invalid model member')
    parts = name.split('/')
    if len(parts) < 2 or parts[0] not in (*NAMES, *OPTIONAL):
        raise ProvisionError('Unreviewed model directory')
    if any(not re.fullmatch(r'[A-Za-z0-9_.+-]+', p) or p in ('.', '..') or
           p.endswith('.') or RESERVED.match(p) for p in parts):
        raise ProvisionError('Unsafe portable model path')
    return name


def validate(value):
    if not isinstance(value, dict) or set(value) != {'kind', 'version', 'files'} or value['kind'] != 'echo-models' or value['version'] != 1:
        raise ProvisionError('Unsupported model manifest')
    files = value['files']
    if not isinstance(files, dict) or not 1 <= len(files) <= 100_000:
        raise ProvisionError('Invalid model inventory')
    seen = set()
    for name, item in files.items():
        member_name(name)
        folded = name.casefold()
        if folded in seen:
            raise ProvisionError('Case-colliding model paths')
        seen.add(folded)
        if not isinstance(item, dict) or set(item) != {'size', 'sha256'} or type(item['size']) is not int or not 0 <= item['size'] <= MAX_BYTES or not isinstance(item['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', item['sha256']):
            raise ProvisionError('Invalid model descriptor')
    for name in seen:
        if any('/'.join(name.split('/')[:i]) in seen for i in range(1, len(name.split('/')))):
            raise ProvisionError('Model file/directory collision')
    if set(NAMES) - {name.split('/')[0] for name in files}:
        raise ProvisionError('Manifest lacks a required model directory')
    if sum(item['size'] for item in files.values()) > MAX_BYTES:
        raise ProvisionError('Model inventory is too large')
    return value


def raw_manifest(value):
    return (json.dumps(validate(value), sort_keys=True, indent=2) + '\n').encode()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProvisionError('Duplicate manifest key')
        result[key] = value
    return result


def load(path, digest):
    path = unlinked(path)
    if not re.fullmatch('[a-f0-9]{64}', digest or ''):
        raise ProvisionError('Supply the trusted manifest SHA-256 separately')
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST:
        raise ProvisionError('Missing or oversized model manifest')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ProvisionError('Model manifest SHA-256 does not match')
    return validate(json.loads(raw, object_pairs_hook=_unique_pairs))


def descriptor(path):
    path = unlinked(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise ProvisionError('Unexpected model file')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ProvisionError('Model changed during inspection')
    return {'size': after.st_size, 'sha256': digest}


def inventory(source):
    source = unlinked(source)
    if not source.is_dir():
        raise ProvisionError('Model source is missing')
    files = {}
    for model in (*NAMES, *OPTIONAL):
        root = unlinked(source / model)
        if not root.exists():
            if model in NAMES:
                raise ProvisionError('A required model directory is missing')
            continue
        if not root.is_dir():
            raise ProvisionError('Model root must be a directory')
        for directory, directories, names in os.walk(root, followlinks=False):
            for entry in directories + names:
                unlinked(Path(directory) / entry)
            for entry in names:
                path = Path(directory) / entry
                name = member_name(path.relative_to(source).as_posix())
                files[name] = descriptor(path)
    return validate({'kind': 'echo-models', 'version': 1, 'files': files})


def verify_source(source, value):
    if inventory(source) != validate(value):
        raise ProvisionError('Model source inventory or hashes differ from the manifest')


def restore_plan(source, destination, value):
    verify_source(source, value)
    source, destination = unlinked(source), unlinked(destination)
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ProvisionError('Model source and destination must be separate trees')
    if destination.exists() and not destination.is_dir():
        raise ProvisionError('Model destination must be a directory')
    missing = []
    for name, expected in value['files'].items():
        target = unlinked(destination / name)
        if target.exists():
            if not target.is_file() or descriptor(target) != expected:
                raise ProvisionError('Existing model differs; all existing files were preserved')
        else:
            for parent in target.parents:
                if parent == destination.parent:
                    break
                if parent.exists() and not parent.is_dir():
                    raise ProvisionError('Existing model path is not a directory')
            missing.append(name)
    if destination.exists():
        for directory, dirs, names in os.walk(destination, followlinks=False):
            for entry in dirs + names:
                unlinked(Path(directory) / entry)
            for entry in names:
                if (Path(directory) / entry).relative_to(destination).as_posix() not in value['files']:
                    raise ProvisionError('Destination has extra files; its existing data was preserved')
    probe = destination
    while not probe.exists():
        probe = probe.parent
    missing_bytes = sum(value['files'][name]['size'] for name in missing)
    required = missing_bytes + 16 * 1024 * 1024
    free = shutil.disk_usage(probe).free
    if free < required:
        raise ProvisionError('Insufficient free disk space for model restoration')
    return {'missing_files': len(missing), 'missing_bytes': missing_bytes,
            'required_free_bytes': required, 'free_bytes': free, 'missing': missing}


def restore(source, destination, value, *, execute=False):
    plan = restore_plan(source, destination, value)
    if not execute:
        return {k: v for k, v in plan.items() if k != 'missing'} | {'executed': False}
    destination = unlinked(destination)
    for name in plan['missing']:
        target = unlinked(destination / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        unlinked(target.parent)
        temporary = None
        try:
            # Stage inside the selected destination filesystem. Hard-link publish
            # is atomic and exclusive on NTFS: a concurrent file is never replaced.
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.echo-model-', delete=False) as stream:
                temporary = Path(stream.name)
                with unlinked(Path(source) / name).open('rb') as reader:
                    shutil.copyfileobj(reader, stream, length=1024 * 1024)
                stream.flush()
                os.fsync(stream.fileno())
            if descriptor(temporary) != value['files'][name]:
                raise ProvisionError('Model source changed while copying')
            unlinked(target)
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    verify_source(destination, value)
    return {'executed': True, 'copied_files': plan['missing_files'],
            'verified_files': len(value['files']), 'downloaded_models': False}
