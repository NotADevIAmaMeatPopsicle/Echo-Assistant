"""Join owner video grants to the Pi's explicit, short-lived browser player."""
import re
import secrets
import threading
import time

from browser_video import BrowserVideo
from spotify import Unavailable


class VideoSession:
    def __init__(self, request, music, group=None, screen=None, home=None, *,
                 clock=time.monotonic, receiver_factory=BrowserVideo):
        self.request, self.music, self.group, self.screen = request, music, group, screen
        self.clock = clock
        self.lock = threading.RLock()
        self.operation = threading.Lock()
        self.stop = threading.Event()
        self.monitoring = threading.Event()
        self.thread = None
        self.access = None
        self.observed_at = None
        self.generation = 0
        self.access_sequence = 0
        self.music_generation = None
        self.availability = None
        self.checked_at = -100.
        self.receiver = receiver_factory(home, self.focus_snapshot)
        self.music.register_auxiliary(self.receiver)

    def focus_snapshot(self):
        now = self.clock()
        grouped = bool(self.group and self.group.playback_active())
        with self.lock:
            valid = (self.access is not None and self.observed_at is not None
                     and 0 <= now - self.observed_at <= 1.0 and not self.stop.is_set())
            with self.music.lock:
                if self.music_generation != self.music.generation:
                    self.music_generation = self.music.generation
                    self.generation += 1
                playing = bool(self.music.player and self.music.player.poll() is None)
                playing |= self.music.status == 'playing' and not self.music.silenced
                return {'held': grouped or self.music.held(), 'ducked': self.music.ducked(),
                        'spotify_active': playing, 'access_valid': valid,
                        'generation': self.generation, 'observed_at': now}

    def refresh_access(self):
        with self.lock:
            self.access_sequence += 1
            sequence = self.access_sequence
        selected = None
        try:
            result = self.request('/v1/display/video', timeout=2)
            if (result.get('available') is True and result.get('reason') == 'allowed'
                    and result.get('provider') == 'youtube'
                    and type(result.get('revision')) is int and result['revision'] >= 0
                    and type(result.get('profile_revision')) is int and result['profile_revision'] >= 0
                    and isinstance(result.get('video_id'), str)
                    and re.fullmatch(r'[A-Za-z0-9_-]{11}', result['video_id'])):
                selected = (result['revision'], result['profile_revision'], result['video_id'])
        except Exception:
            pass
        with self.lock:
            if sequence != self.access_sequence: return None
            if self.stop.is_set(): selected = None
            changed = selected != self.access
            if changed: self.generation += 1
            self.access, self.observed_at = selected, self.clock()
        # No session/music lock may be held while awaiting actual output silence.
        if changed or selected is None: self.receiver.hard_stop('access')
        return selected

    def start(self):
        if self.thread: return
        def watch():
            while not self.stop.wait(.4):
                if self.monitoring.is_set():
                    self.refresh_access()
                    # Never wait on the receiver's startup lock before updating
                    # access freshness. Launch/pulse own operation while active.
                    if self.operation.acquire(blocking=False):
                        try:
                            if not self.receiver.snapshot().get('active'):self.monitoring.clear()
                        finally:self.operation.release()
        self.thread = threading.Thread(target=watch, name='pi-video-access', daemon=True)
        self.thread.start()

    def snapshot(self):
        selected = self.refresh_access()
        if selected is None:
            return {'available': False, 'phase': 'unavailable', 'error': 'video_not_allowed'}
        if self.clock() - self.checked_at > 5 or self.availability is None:
            checked = self.receiver.check()
            self.availability, self.checked_at = checked, self.clock()
        state = self.receiver.snapshot()
        return {'available': self.availability.get('available') is True,
                'phase': state.get('phase', 'unavailable'),
                'error': state.get('error') or self.availability.get('error')}

    def launch(self, revision):
        if type(revision) is not int or revision < 0: raise ValueError('Invalid video revision')
        with self.operation:
            selected = self.refresh_access()
            if selected is None: raise Unavailable('Video is not enabled for this Household display')
            if selected[0] != revision: raise Unavailable('Video selection changed; reload before playing')
            if self.group and self.group.playback_active():
                raise Unavailable('Stop grouped music before loading video')
            with self.music.lock:
                if self.music.held(): raise Unavailable('Finish the current audio session before loading video')
                self.music.pause()
            self.music.stop_auxiliary('focus')
            if self.refresh_access() != selected:
                raise Unavailable('Video access changed before playback')
            lease = secrets.token_hex(16)
            self.monitoring.set()
            if not self.receiver.start(lease, selected[2]):
                raise Unavailable('The dedicated video player is unavailable; check its audio setup')
            if self.screen: self.screen.wake()
            return {'accepted': True}

    def end(self):
        if not self.receiver.hard_stop('stop'):
            raise Unavailable('The video output has not confirmed that it stopped')
        return {'stopped': True}

    def pulse(self, lease, action):
        with self.operation:
            return self._pulse(lease, action)

    def _pulse(self, lease, action):
        if not isinstance(lease, str) or not re.fullmatch(r'[a-f0-9]{32}', lease):
            raise ValueError('Invalid player lease')
        if action not in {'pulse', 'stop'}: raise ValueError('Invalid player action')
        selected = self.refresh_access()
        state = self.receiver.snapshot()
        if (selected is None or not state.get('active') or state.get('lease_id') != lease
                or state.get('video_id') != selected[2]):
            raise Unavailable('This player has expired or its access changed')
        if action == 'stop': return self.end()
        if not self.receiver.heartbeat(lease): raise Unavailable('This player has expired')
        if self.screen: self.screen.wake()
        return {'active': True, 'video_id': selected[2],
                'watch_url': 'https://www.youtube.com/watch?v=' + selected[2]}

    def active(self):
        return self.receiver.snapshot().get('active') is True

    def close(self):
        self.stop.set()
        with self.lock:
            self.access = None
            self.generation += 1
        self.receiver.hard_stop('shutdown')
        if self.thread: self.thread.join(timeout=3)
        self.receiver.close()
