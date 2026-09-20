"""Opt-in X11 display sleep. Never suspends the Pi, microphone or music."""
import json
import os
from pathlib import Path
import subprocess
import threading


DEFAULTS = {'dim_after': 120, 'off_after': 600, 'hdmi_sleep': False}
TIMES = {0, 60, 120, 300, 600, 900, 1800, 3600}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Choose screen timers and HDMI sleep')
    if any(type(value[k]) is not int or value[k] not in TIMES for k in ('dim_after', 'off_after')):
        raise ValueError('Invalid screen timer')
    if type(value['hdmi_sleep']) is not bool:
        raise ValueError('Invalid HDMI sleep choice')
    if value['off_after'] and value['dim_after'] >= value['off_after']:
        raise ValueError('Sleep must be later than dimming')
    return dict(value)


class Screen:
    def __init__(self, home=None, run=subprocess.run):
        self.home = Path(home or Path.home())
        self.path = self.home / '.config/echo-display/screen.json'
        self.run = run
        self.lock = threading.RLock()
        self.config = dict(DEFAULTS)
        try:
            if not self.path.is_symlink():
                self.config = validate(json.loads(self.path.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass

    def command(self, *args):
        env = {**os.environ, 'DISPLAY': os.environ.get('DISPLAY', ':0'),
               'XAUTHORITY': os.environ.get('XAUTHORITY', str(self.home / '.Xauthority')),
               'LC_ALL': 'C'}
        result = self.run(['xset', *args], env=env, capture_output=True, text=True, timeout=3, check=True)
        return result.stdout

    def supported(self):
        try:
            return 'DPMS is' in self.command('q')
        except (OSError, subprocess.SubprocessError):
            return False

    def snapshot(self):
        with self.lock:
            return {'supported': True, 'hdmi_supported': self.supported(),
                    'settings': dict(self.config), 'presence_available': False}

    def apply(self):
        with self.lock:
            if not self.config['hdmi_sleep']:
                return
            self.command('s', 'off')
            if self.config['off_after']:
                self.command('+dpms')
                # Give the browser's black, wake-only cover time to appear first.
                self.command('dpms', '0', '0', str(self.config['off_after'] + 2))
            else:
                self.command('dpms', 'force', 'on')
                self.command('-dpms')

    def configure(self, value):
        value = validate(value)
        with self.lock:
            if value['hdmi_sleep'] and not self.supported():
                raise ValueError('This desktop does not expose HDMI sleep')
            old = self.config
            self.config = value
            try:
                if old['hdmi_sleep'] and not value['hdmi_sleep']:
                    self.command('dpms', 'force', 'on')
                    self.command('-dpms')
                self.apply()
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if self.path.is_symlink():
                    raise ValueError('Use a regular screen settings file')
                temporary = self.path.with_suffix('.new')
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(value, stream)
                temporary.replace(self.path)
            except (OSError, ValueError, subprocess.SubprocessError):
                self.config = old
                self.apply()
                raise
            self.wake()
            return self.snapshot()

    def wake(self):
        with self.lock:
            if self.config['hdmi_sleep']:
                try:
                    if self.config['off_after']:
                        self.command('dpms', 'force', 'on')
                    self.command('s', 'reset')
                except (OSError, subprocess.SubprocessError):
                    pass  # Display failure must never block a voice request.

    def sleep(self):
        with self.lock:
            if self.config['hdmi_sleep'] and self.config['off_after']:
                self.command('dpms', 'force', 'off')
