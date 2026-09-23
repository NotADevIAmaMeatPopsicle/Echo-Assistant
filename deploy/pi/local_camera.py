"""Explicit camera leases, local motion wake and a dedicated Google Meet window."""
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile
import threading
import time

from kiosk import selected_audio_environment
from spotify import Unavailable

DEFAULTS = {'presence': False, 'mirror': False, 'rotate': 0, 'focus': None}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Choose camera settings')
    if type(value['presence']) is not bool or type(value['mirror']) is not bool:
        raise ValueError('Choose camera switches')
    if type(value['rotate']) is not int or value['rotate'] not in (0, 180):
        raise ValueError('Choose upright or rotated orientation')
    if value['focus'] is not None and (type(value['focus']) is not int or not 0 <= value['focus'] <= 4095):
        raise ValueError('Choose a lens position from 0 to 4095')
    return dict(value)


def meet_url(value):
    if not isinstance(value, str):
        raise ValueError('Enter a Google Meet code or link')
    value = value.strip().removeprefix('https://meet.google.com/').rstrip('/')
    if not re.fullmatch(r'[a-z]{3}-[a-z]{4}-[a-z]{3}', value):
        raise ValueError('Use a Google Meet code such as abc-defg-hij')
    return 'https://meet.google.com/' + value


class LocalCamera:
    def __init__(self, request, music, screen, voice=None, home=None):
        self.home = Path(home or Path.home())
        self.path = self.home / '.config/echo-display/camera.json'
        self.request, self.music, self.screen, self.voice = request, music, screen, voice
        try:
            self.supported = subprocess.run(['/usr/bin/python3', '-c',
                'import importlib.util;raise SystemExit(0 if importlib.util.find_spec("picamera2") else 1)'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3).returncode == 0
        except (OSError, subprocess.SubprocessError):
            self.supported = False
        self.config = dict(DEFAULTS)
        if self.path.exists() and not self.path.is_symlink():
            self.config = validate(json.loads(self.path.read_text()))
        self.lock = threading.RLock()
        self.process = self.directory = self.temporary = None
        self.lease = self.client = self.purpose = None
        self.expires = 0
        self.focus_once = None
        self.access = None
        self.access_at = 0
        self.presence_suspended = False
        self.motion_at = 0
        self.meet = None
        self.meet_module = None
        self.meet_sink = None
        self.meet_until = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.watch, name='echo-camera', daemon=True)
        self.thread.start()

    def allowed(self):
        try:
            s = self.request('/v1/display/session', timeout=3)
            if s.get('profile', {}).get('mode') != 'household' or s.get('member'):
                return None
            return s.get('profile_revision', 0)
        except Exception:
            return None

    def state(self):
        try:
            value = json.loads((self.directory / 'status.json').read_text())
            if time.time() - value.get('updated_at', time.time()) > 3:
                return {'ready': False, 'capturing': False, 'error': 'Camera stopped responding'}
            return value
        except (OSError, ValueError, TypeError):
            return {'ready': False, 'capturing': False}

    def snapshot(self):
        with self.lock:
            state = self.state() if self.directory else {'ready': False, 'capturing': False}
            return {'supported': self.supported,
                    'virtual_camera': Path('/sys/class/video4linux/video42/name').exists(),
                    'settings': dict(self.config), 'purpose': self.purpose,
                    'presence_suspended': self.presence_suspended, 'meet_active': bool(self.meet),
                    'motion_at': self.motion_at, **state}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError('Use a regular camera settings file')
        temporary = self.path.with_suffix('.new')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(self.config, stream)
        temporary.replace(self.path)

    def configure(self, value):
        value = validate(value)
        with self.lock:
            if self.allowed() is None:
                raise Unavailable('Camera access requires an online Household display')
            self.config = value
            self.presence_suspended = False
            self.save()
            if not value['presence'] and self.purpose == 'presence':
                self.end_worker()
            self.control()
            return self.snapshot()

    def control(self):
        if not self.directory:
            return
        value = {**self.config, 'purpose': self.purpose, 'heartbeat': time.monotonic(),
                 'focus_once': self.focus_once}
        path = self.directory / 'control.new'
        path.write_text(json.dumps(value)); path.replace(self.directory / 'control.json')

    def start_worker(self, purpose):
        if not self.supported:
            raise Unavailable('Install the Pi camera dependencies first')
        if purpose in {'call', 'meet'}:
            name = Path('/sys/class/video4linux/video42/name')
            if not name.exists() or name.read_text().strip() != 'Echo Camera':
                raise Unavailable('Echo virtual webcam is not installed')
        self.temporary = tempfile.TemporaryDirectory(prefix='echo-camera-', dir='/dev/shm')
        self.directory = Path(self.temporary.name)
        self.purpose = purpose; self.focus_once = None
        self.control()
        self.process = subprocess.Popen(['/usr/bin/python3', str(Path(__file__).with_name('camera_worker.py')),
                                         str(self.directory)], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        start_new_session=True)

    def end_worker(self):
        if self.process:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL); self.process.wait(timeout=2)
            except ProcessLookupError:
                pass
        self.process = None
        if self.temporary:
            self.temporary.cleanup()
        self.directory = self.temporary = self.purpose = None

    def start_capture(self, client, purpose):
        if not isinstance(client, str) or not re.fullmatch(r'[a-f0-9]{32}', client) or purpose not in {'preview', 'call', 'meet'}:
            raise ValueError('Choose a camera session')
        with self.lock:
            access = self.allowed()
            if access is None:
                raise Unavailable('Camera access requires an online Household display')
            if self.lease:
                raise Unavailable('Close the current camera session first')
            self.end_worker()
            self.presence_suspended = True
            self.access, self.access_at = access, time.monotonic()
            self.lease, self.client = secrets.token_hex(16), client
            self.expires = time.monotonic() + 12
            try:
                self.start_worker(purpose)
            except Exception:
                self.lease = self.client = None
                raise
            return {'lease': self.lease, 'label': 'Echo Camera', 'purpose': purpose}

    def check_lease(self, value):
        if not isinstance(value, dict) or value.get('lease') != self.lease or not self.lease or value.get('client') != self.client:
            raise Unavailable('This camera session ended')
        if time.monotonic() > self.expires:
            raise Unavailable('Camera permission expired')
        if self.allowed() != self.access:
            self.close_capture()
            raise Unavailable('Camera access changed')

    def pulse(self, value):
        with self.lock:
            self.check_lease(value)
            self.expires = time.monotonic() + 12
            return self.snapshot()

    def frame(self, value):
        with self.lock:
            self.check_lease(value)
            if not self.directory or not self.state().get('capturing'):
                raise Unavailable('The camera is warming up')
            try:
                raw = (self.directory / 'frame.jpg').read_bytes()
            except OSError:
                raise Unavailable('The camera is warming up') from None
            if len(raw) > 1_000_000:
                raise Unavailable('The camera frame is too large')
            return raw

    def focus(self, value):
        with self.lock:
            self.check_lease(value)
            if not self.state().get('focus_supported'):
                raise Unavailable('This camera does not expose lens controls')
            self.focus_once = secrets.token_hex(8); self.control()
            return {'accepted': True}

    def release(self, value):
        with self.lock:
            self.check_lease(value)
            self.close_capture()
            return self.snapshot()

    def close_capture(self):
        self.end_meet()
        self.end_worker()
        self.lease = self.client = None
        self.expires = 0

    def disable(self):
        with self.lock:
            self.close_capture(); self.config['presence'] = False; self.save()
            return self.snapshot()

    def pulse_command(self, *args):
        return subprocess.check_output(['pactl', '--server=unix:/run/user/' + str(os.getuid()) + '/echo-audio/native',
                                        *args], text=True, timeout=4).strip()

    def launch_meet(self, client, code):
        url = meet_url(code)
        with self.lock:
            if self.music.held():
                raise Unavailable('Finish the current voice session or call first')
            session = self.start_capture(client, 'meet')
            try:
                deadline = time.monotonic() + 6
                while not self.state().get('ready'):
                    if time.monotonic() > deadline or self.process.poll() is not None:
                        raise Unavailable('Virtual camera did not become ready')
                    time.sleep(.15)
                self.music.focus(client, True)
                if self.voice: self.voice.interrupt()
                self.meet_sink = 'echo_meet_' + secrets.token_hex(6)
                self.meet_module = self.pulse_command('load-module', 'module-remap-sink',
                    'master=echo_processed', 'sink_name=' + self.meet_sink, 'remix=no')
                self.pulse_command('set-sink-volume', self.meet_sink, '2%')
                profile = self.home / '.local/share/echo-display/meet-browser'
                profile.mkdir(parents=True, exist_ok=True, mode=0o700)
                env = {**os.environ, **selected_audio_environment(self.home, os.getuid()),
                       'PULSE_SINK': self.meet_sink, 'PULSE_SOURCE': 'echo_cancelled',
                       'DISPLAY': ':0', 'XAUTHORITY': str(self.home / '.Xauthority')}
                self.meet = subprocess.Popen(['chromium', '--no-first-run', '--disable-background-mode',
                    '--new-window', '--window-size=1024,600', '--user-data-dir=' + str(profile),
                    url], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True)
                self.meet_until = time.monotonic() + 3600
                self.screen.wake()
                return session
            except Exception:
                self.close_capture()
                raise Unavailable('Meet could not open with the selected audio and camera') from None

    def end_meet(self):
        if self.meet:
            try:
                os.killpg(self.meet.pid, signal.SIGTERM); self.meet.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.meet.pid, signal.SIGKILL); self.meet.wait(timeout=2)
            except ProcessLookupError:
                pass
            self.meet = None
        if self.meet_module:
            try: self.pulse_command('unload-module', self.meet_module)
            except (OSError, subprocess.SubprocessError): pass
            self.meet_module = self.meet_sink = None
        if self.client:
            self.music.focus(self.client, False)

    def watch(self):
        while not self.stop.wait(1):
            with self.lock:
                try:
                    active = self.lease or self.config['presence'] and not self.presence_suspended
                    if not active:
                        continue
                    now = time.monotonic()
                    if now - self.access_at > 3:
                        access = self.allowed()
                        if access is None or self.access is not None and access != self.access:
                            self.close_capture(); self.presence_suspended = True; continue
                        self.access = access; self.access_at = now
                    if self.meet:
                        if self.meet.poll() is not None or now > self.meet_until:
                            self.close_capture(); continue
                        self.expires = now + 12
                        self.music.focus(self.client, True)
                    if self.lease and now > self.expires:
                        self.close_capture(); continue
                    if not self.process and not self.lease and self.config['presence'] and not self.presence_suspended:
                        self.start_worker('presence')
                    self.control()
                    state = self.state() if self.directory else {}
                    if self.focus_once and state.get('focus_completed') == self.focus_once:
                        self.config['focus'] = state['focus'];self.save();self.focus_once = None
                    if self.purpose == 'presence' and state.get('motion_at', 0) > self.motion_at:
                        self.motion_at = state['motion_at']; self.screen.wake()
                except Exception:
                    self.close_capture(); self.presence_suspended = True

    def close(self):
        self.stop.set()
        with self.lock: self.close_capture()
