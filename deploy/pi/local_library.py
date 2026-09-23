"""Read-only SD-card music library, rooted in the desktop user's Music/Echo folder."""
import hashlib
import os
from pathlib import Path
import re
import stat
from threading import RLock
import time


MEDIA = {'.mp3', '.m4a', '.aac', '.ogg', '.oga', '.opus', '.wav', '.flac', '.mp4', '.webm'}
TYPES = {'.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.ogg': 'audio/ogg',
         '.oga': 'audio/ogg', '.opus': 'audio/ogg', '.wav': 'audio/wav', '.flac': 'audio/flac',
         '.mp4': 'video/mp4', '.webm': 'video/webm'}


class LocalLibrary:
    def __init__(self, home=None, clock=time.monotonic):
        self.root = Path(home or Path.home()) / 'Music' / 'Echo'
        if self.root.is_symlink() or self.root.parent.is_symlink():
            raise ValueError('Use a regular Music/Echo directory')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = self.root.resolve()
        self.clock, self.lock = clock, RLock()
        self.last_scan, self.tracks, self.snapshot = None, {}, None

    @staticmethod
    def identifier(path):
        return hashlib.sha256(path.as_posix().encode()).hexdigest()[:32]

    def scan(self, force=False):
        with self.lock:
            if not force and self.last_scan is not None and self.clock() - self.last_scan < 10:
                return self.snapshot
            tracks, playlist_paths, paths, truncated = {}, [], {}, False
            visited = 0
            for folder, dirs, files in os.walk(self.root, followlinks=False):
                relative = Path(folder).relative_to(self.root)
                dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink())
                if len(relative.parts) >= 8: dirs[:] = []
                for name in sorted(files):
                    visited += 1
                    if visited > 10000 or len(tracks) >= 5000: truncated = True; break
                    path = Path(folder)/name
                    if name.startswith('.') or path.is_symlink(): continue
                    try: info = path.stat()
                    except OSError: continue
                    if not stat.S_ISREG(info.st_mode): continue
                    if path.suffix.lower() in {'.m3u', '.m3u8'}:
                        if len(playlist_paths) < 200 and info.st_size <= 262144: playlist_paths.append(path)
                        continue
                    if path.suffix.lower() not in MEDIA or not info.st_size: continue
                    rel = path.relative_to(self.root); key = self.identifier(rel)
                    tracks[key] = {'path': rel, 'size': info.st_size, 'modified': info.st_mtime_ns,
                                   'inode': info.st_ino, 'device': info.st_dev}
                    paths[path] = key
                if truncated: break
            items = [{'id': key, 'name': value['path'].stem, 'filename': value['path'].name,
                      'folder': value['path'].parent.as_posix() if value['path'].parent != Path('.') else '',
                      'size': value['size'], 'type': TYPES[value['path'].suffix.lower()],
                      'url': '/v1/display/library/stream/'+key} for key, value in tracks.items()]
            playlists = []
            for path in playlist_paths:
                try:
                    # Refuse links even if they appeared after the walk. No arbitrary files are served.
                    if path.is_symlink(): continue
                    with path.open('rb') as stream: raw = stream.read(262145)
                    if len(raw) > 262144: continue
                    entries, missing = [], 0
                    for line in raw.decode('utf-8-sig', errors='replace').splitlines():
                        line = line.strip()
                        if not line or line.startswith('#'): continue
                        if len(entries) >= 1000: break
                        candidate = Path(line.replace('\\', '/'))
                        if candidate.is_absolute() or '://' in line or re.match(r'^[A-Za-z]:', line): missing += 1; continue
                        resolved = (path.parent/candidate).resolve()
                        if not resolved.is_relative_to(self.root) or resolved not in paths: missing += 1; continue
                        entries.append(paths[resolved])
                    playlists.append({'id': self.identifier(path.relative_to(self.root)), 'name': path.stem,
                                      'tracks': entries, 'missing': missing})
                except OSError: continue
            self.tracks = tracks
            revision = hashlib.sha256(repr(([(k, v['size'], v['modified']) for k, v in tracks.items()], playlists)).encode()).hexdigest()
            self.snapshot = {'supported': True, 'folder': '~/Music/Echo', 'revision': revision,
                             'tracks': items, 'playlists': playlists, 'truncated': truncated,
                             'free_bytes': os.statvfs(self.root).f_bavail * os.statvfs(self.root).f_frsize if hasattr(os, 'statvfs') else None}
            self.last_scan = self.clock()
            return self.snapshot

    def open_track(self, identifier):
        if not re.fullmatch(r'[a-f0-9]{32}', identifier): raise FileNotFoundError('Unknown track')
        self.scan()
        with self.lock: entry = self.tracks.get(identifier)
        if entry is None: raise FileNotFoundError('Rescan the music folder')
        path = self.root/entry['path']
        if os.name == 'posix':
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for part in entry['path'].parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(directory); directory = child
                descriptor = os.open(entry['path'].name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            finally: os.close(directory)
            stream = os.fdopen(descriptor, 'rb')
        else:
            if any(p.is_symlink() for p in [path, *path.parents]) or not path.resolve().is_relative_to(self.root):
                raise FileNotFoundError('Track is unavailable')
            stream = path.open('rb')
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or (info.st_size, info.st_mtime_ns, info.st_ino, info.st_dev)
                != (entry['size'], entry['modified'], entry['inode'], entry['device'])):
            stream.close(); raise FileNotFoundError('Track changed. Rescan the music folder.')
        return stream, info.st_size, TYPES[path.suffix.lower()]


def byte_range(header, size):
    if not header: return 0, size - 1, False
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
    if not match or not any(match.groups()): raise ValueError('Invalid byte range')
    first, last = match.groups()
    if not first:
        if int(last) <= 0: raise ValueError('Invalid byte range')
        start, end = max(0, size-int(last)), size-1
    else: start, end = int(first), min(int(last), size-1) if last else size-1
    if start >= size or end < start: raise ValueError('Unsatisfiable byte range')
    return start, end, True
