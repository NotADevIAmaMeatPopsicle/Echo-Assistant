"""Own the API and optional voice child in one Linux container, without recording logs."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
from .lifecycle import Lifecycle, _acquire_lock, _release_lock, request_stop
from .transport import load_wifi


def request_voice_restart(root):
    """Address the live supervisor's generation, never a possibly recycled PID."""
    lock = _acquire_lock(root/'local', 'host')
    if lock is not None:
        _release_lock(lock)
        raise ValueError('The container voice supervisor is not running')
    owner = json.loads((root/'local/host-process.json').read_text())
    state = json.loads((root/'local/host-status.json').read_text())
    identity = owner.get('run_id')
    if (not isinstance(identity, str) or len(identity) != 32
            or state.get('run_id') != identity or state.get('voice_enabled') is not True
            or not 0 <= time.time()-state.get('updated_at', 0) < 5):
        raise ValueError('Voice is not enabled on this container')
    path = root/'local/voice-restart'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(identity)
    temporary.replace(path)


def api_ready():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8768/health', timeout=.5) as response:
            return response.status == 200
    except OSError: return False


class Host:
    def __init__(self, root, voice_enabled, *, launch=None, ready=api_ready, grace=35):
        self.root, self.voice_enabled = root, voice_enabled
        self.launch = launch or self._launch
        self.ready, self.grace = ready, grace
        self.api = self.voice = None
        self.restarts = 0
        self.phase = 'starting'

    def _launch(self, name):
        return subprocess.Popen([sys.executable, '-m', 'backend.'+name], cwd=self.root,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)

    def _stop_child(self, child, name):
        if child is None: return
        if child.poll() is None:
            request_stop(self.root, name)
            child.terminate()
            try: child.wait(timeout=self.grace)
            except subprocess.TimeoutExpired:
                # The process group was created by this supervisor and still has its child.
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)

    def run(self):
        with Lifecycle(self.root, 'host') as owner:
            self.api = self.launch('app')
            retry_at = 0.
            paused = False
            try:
                while not owner.stopped() and self.api.poll() is None:
                    now = time.monotonic()
                    restart = self.root/'local/voice-restart'
                    try: requested = restart.read_text() == owner.identity
                    except FileNotFoundError: requested = False
                    if requested:
                        restart.unlink(missing_ok=True)
                        if self.voice_enabled:
                            self._stop_child(self.voice, 'voice')
                            self.voice = None; paused = False; retry_at = 0
                            self.restarts += 1
                    if self.voice is not None and self.voice.poll() is not None:
                        # A successful explicit bridge stop stays stopped until Apply/restart.
                        paused = self.voice.returncode == 0
                        self.voice = None
                        if not paused:
                            self.restarts += 1
                            retry_at = now+min(30, 2**min(self.restarts, 5))
                    if self.voice_enabled and self.voice is None and not paused and now >= retry_at and self.ready():
                        self.voice = self.launch('voice')
                    self.phase = ('paused' if paused else 'running' if self.voice else 'waiting') if self.voice_enabled else 'api_only'
                    path = self.root/'local/host-status.json'
                    temporary = path.with_suffix('.tmp')
                    temporary.write_text(json.dumps({'run_id':owner.identity,'updated_at':time.time(),
                        'voice_enabled':self.voice_enabled,'phase':self.phase,'voice_restarts':self.restarts}))
                    temporary.replace(path)
                    owner.wait(.25)
                return self.api.returncode or 0
            finally:
                self._stop_child(self.voice, 'voice')
                self._stop_child(self.api, 'api')
                (self.root/'local/host-status.json').unlink(missing_ok=True)


def main():
    if sys.platform != 'linux' or os.environ.get('ECHO_CONTAINER') != '1':
        raise RuntimeError('The container supervisor is Linux-only')
    root = Path(__file__).resolve().parents[1]
    enabled = os.environ.get('ECHO_VOICE_ENABLED') == '1'
    if enabled and (os.environ.get('ECHO_DEPLOYMENT_MODE') != 'device' or not load_wifi(root)):
        raise RuntimeError('Voice requires an explicitly paired device deployment')
    return Host(root, enabled).run()


if __name__ == '__main__': sys.exit(main())
