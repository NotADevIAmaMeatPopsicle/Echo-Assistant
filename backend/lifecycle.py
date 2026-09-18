"""Exclusive bridge ownership and an explicit local graceful-stop request."""
import json
import os
from pathlib import Path
import signal
import time
import uuid
import errno


def _acquire_lock(directory, name):
    """The OS lock, not a saved PID, is authoritative for service ownership."""
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory/f'{name}.lock').open('a+b')
    try:
        lock.seek(0)
        if not lock.read(1): lock.write(b'0'); lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        lock.close()
        if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}: return None
        raise
    return lock


def _release_lock(lock):
    if lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


class Lifecycle:
    def __init__(self, root: Path, name='voice'):
        if name not in {'voice', 'api', 'host'}: raise ValueError('Unknown service')
        self.name = name
        self.directory = root/'local'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.identity = uuid.uuid4().hex
        self.lock = None
        self.stopping = False
        self.signals = {}

    def __enter__(self):
        self.lock = _acquire_lock(self.directory, self.name)
        if self.lock is None:
            raise RuntimeError(f'Another Round Voice {self.name} service already owns this project')
        record = {'run_id': self.identity, 'pid': os.getpid()}
        path = self.directory/f'{self.name}-process.json'
        try:
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(record), encoding='utf-8')
            temporary.replace(path)
        except OSError:
            _release_lock(self.lock); self.lock = None; raise
        for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
            value = getattr(signal, name, None)
            if value is not None:
                self.signals[value] = signal.signal(value, self._stop)
        return self

    def _stop(self, *_):
        self.stopping = True

    def stopped(self):
        if self.stopping: return True
        try:
            request = (self.directory/f'{self.name}-stop').read_text(encoding='utf-8').strip()
            self.stopping = request == self.identity
        except FileNotFoundError:
            pass
        return self.stopping

    def wait(self, seconds):
        until = time.monotonic()+seconds
        while not self.stopped() and time.monotonic() < until:
            time.sleep(min(.1, max(0, until-time.monotonic())))

    def __exit__(self, *_):
        for value, handler in self.signals.items(): signal.signal(value, handler)
        try: (self.directory/f'{self.name}-process.json').unlink(missing_ok=True)
        finally: _release_lock(self.lock); self.lock = None


def request_stop(root: Path, name='voice'):
    if name not in {'voice', 'api', 'host'}: raise ValueError('Unknown service')
    path = root/f'local/{name}-process.json'
    lock = _acquire_lock(path.parent, name)
    if lock is not None:
        try:
            # A dead process cannot retain this lock. Remove only the stale
            # metadata while holding it; never signal or kill a reused PID.
            path.unlink(missing_ok=True)
            (root/f'local/{name}-stop').unlink(missing_ok=True)
        finally: _release_lock(lock)
        return False
    try: record = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError: return False
    identity = record.get('run_id') if isinstance(record, dict) else None
    if not isinstance(identity, str) or len(identity) != 32:
        raise ValueError('Invalid bridge process record')
    (root/f'local/{name}-stop').write_text(identity, encoding='utf-8')
    return True
