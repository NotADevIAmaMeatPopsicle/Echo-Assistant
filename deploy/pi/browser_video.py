"""Explicit leased browser playback with a native, fail-closed PCM boundary.

Construction/status are inert. The coordinator owns authorization, provider
selection and fresh focus, and must call hard_stop outside its own locks.
"""
from array import array
import math
import re
import sys
import threading
import time

from browser_video_backend import BackendUnavailable, BrowserVideoBackend


LEASE_SECONDS = 15.0
FOCUS_MAX_AGE = 1.0
BLOCK_BYTES = 3840  # 20 ms, stereo s16le, 48 kHz.


def attenuate(pcm, ducked):
    if len(pcm) > BLOCK_BYTES or len(pcm) % 4 or type(ducked) is not bool:
        raise ValueError('Invalid browser PCM block')
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    divisor = 250 if ducked else 50
    for index, sample in enumerate(samples):
        samples[index] = int(sample / divisor)  # Round toward silence.
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()


class BrowserVideo:
    def __init__(self, home, focus_snapshot, backend=None, clock=time.monotonic):
        self.backend = backend or BrowserVideoBackend(home)
        self.focus_snapshot, self.clock = focus_snapshot, clock
        self.lock = threading.RLock()
        self.thread = None
        self.phase, self.error = 'idle', None
        self.active, self.output_active, self.stop_confirmed = False, False, True
        self.lease_id = self.video_id = self.generation = None
        self.deadline = 0.0
        self.used_leases = set()
        self.carry = b''
        self.closed = False
        self.touched_backend = False
        self.epoch = 0

    def snapshot(self):
        with self.lock:
            return {'phase': self.phase, 'active': self.active,
                    'output_active': self.output_active, 'error': self.error,
                    'stop_confirmed': self.stop_confirmed, 'lease_id': self.lease_id,
                    'video_id': self.video_id, 'output_volume': 2}

    @staticmethod
    def _reason(error):
        if isinstance(error, BackendUnavailable) and re.fullmatch(r'[a-z_]{1,80}', str(error)):
            return str(error)
        return 'backend_unavailable'

    def check(self):
        """Explicit read-only capability check; never creates a playback child."""
        try:
            self.backend.check()
            return {'available': True, 'error': None}
        except Exception as error:
            return {'available': False, 'error': self._reason(error)}

    def _focus(self):
        # Must never be invoked while holding self.lock: the supplier can take
        # Spotify/session locks and call hard_stop after releasing those locks.
        try:
            value = self.focus_snapshot()
            if (not isinstance(value, dict)
                    or any(type(value.get(k)) is not bool for k in
                           ('held', 'ducked', 'spotify_active', 'access_valid'))
                    or type(value.get('generation')) is not int or value['generation'] < 0
                    or type(value.get('observed_at')) not in (int, float)
                    or not math.isfinite(value['observed_at'])
                    or not 0 <= self.clock() - value['observed_at'] <= FOCUS_MAX_AGE):
                return None
            return value
        except Exception:
            return None

    def _blocked(self, focus):
        if focus is None or not 0 <= self.clock() - focus['observed_at'] <= FOCUS_MAX_AGE:
            return 'stale_focus'
        if not focus['access_valid']:
            return 'access'
        if focus['held']:
            return 'focus'
        if focus['spotify_active']:
            return 'spotify'
        return None

    def start(self, lease_id, video_id):
        if (not isinstance(lease_id, str) or not re.fullmatch(r'[0-9a-f]{32}', lease_id)
                or not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id)):
            return False
        with self.lock:
            epoch = self.epoch
        focus = self._focus()
        with self.lock:
            if (epoch != self.epoch or self.closed or self.active or not self.stop_confirmed
                    or lease_id in self.used_leases):
                return False
            # Bounded lifetime: refusing after 4096 starts preserves replay
            # rejection without unbounded state. A service restart resets it.
            if len(self.used_leases) >= 4096:
                self.phase, self.error = 'unavailable', 'lease_limit_reached'
                return False
            self.used_leases.add(lease_id)
            self.error = self._blocked(focus)
            if self.error:
                self.phase = 'stopped'
                return False
            self.lease_id, self.video_id = lease_id, video_id
            self.generation = focus['generation']
            self.phase = 'starting'
            try:
                self.backend.check()
                self.touched_backend = True
                self.stop_confirmed = False
                self.backend.start('http://127.0.0.1:8790/display/video-player#' + lease_id)
                self.active = True
                self.deadline = self.clock() + LEASE_SECONDS
                self.carry = b''
            except Exception as error:
                self._stop_locked(self._reason(error))
                return False
        # Startup may be slow. No PCM has been admitted yet; resample external
        # focus outside the receiver lock before starting the pump.
        focus = self._focus()
        with self.lock:
            if not self.active or self.lease_id != lease_id:
                return False
            reason = self._blocked(focus)
            if not reason and focus['generation'] != self.generation:
                reason = 'focus_changed'
            if reason:
                self._stop_locked(reason)
                return False
            self.phase = 'playing'
            self.thread = threading.Thread(target=self._run, args=(lease_id,),
                                           name='echo-browser-video', daemon=True)
            self.thread.start()
            return True

    def heartbeat(self, lease_id):
        with self.lock:
            if not self.active or lease_id != self.lease_id:
                return False
            if self.clock() >= self.deadline:
                # Do not extend a dead lease or do OS work from a heartbeat.
                return False
            self.deadline = self.clock() + LEASE_SECONDS
            return True

    def _stop_locked(self, reason):
        self.epoch += 1
        self.active = False
        self.carry = b''
        stopped = True
        if self.touched_backend:
            try:
                stopped = self.backend.stop() is True
            except Exception:
                stopped = False
        self.stop_confirmed = stopped
        self.output_active = not stopped
        self.phase = 'stopped' if stopped else 'unavailable'
        self.error = reason if stopped else 'output_stop_unconfirmed'
        return stopped

    def hard_stop(self, reason='focus'):
        if reason not in {'focus', 'access', 'spotify', 'shutdown', 'stop', 'group', 'provider_changed'}:
            reason = 'focus'
        with self.lock:
            self.epoch += 1  # Also cancel a start still obtaining external focus.
            if not self.touched_backend:
                return True
            return self._stop_locked(reason)

    def _step(self, lease_id):
        focus = self._focus()
        with self.lock:
            if not self.active or self.lease_id != lease_id:
                return False
            reason = self._blocked(focus)
            if not reason and focus['generation'] != self.generation:
                reason = 'focus_changed'
            if not reason and self.clock() >= self.deadline:
                reason = 'lease_expired'
            if reason:
                self._stop_locked(reason)
                return False
            try:
                block = self.backend.read()
                if not isinstance(block, bytes) or len(block) > BLOCK_BYTES:
                    raise BackendUnavailable('invalid_pcm_block')
                data = self.carry + block
                usable = min(len(data) // 4 * 4, BLOCK_BYTES)
                self.carry = data[usable:]
                if usable:
                    if self._blocked(focus):
                        self._stop_locked('stale_focus')
                        return False
                    self.backend.write(attenuate(data[:usable], focus['ducked']))
                    self.output_active = True
                return True
            except Exception as error:
                self._stop_locked(self._reason(error))
                return False

    def _run(self, lease_id):
        while self._step(lease_id):
            time.sleep(.01)

    def close(self):
        with self.lock:
            self.closed = True
            self.epoch += 1
            if not self.touched_backend:
                return True
            return self._stop_locked('shutdown')
