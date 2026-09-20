"""Opt-in Pi alarm chime. No microphone, model, browser tab or round board needed."""
from array import array
from collections import deque
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
import time
import wave

from spotify import outputs, Unavailable


def chime(volume):
    """Two soft, decaying notes; volume is applied before samples reach ALSA."""
    samples = array('h')
    for i in range(48000*3):
        t = i/48000
        value = 0.
        for start, frequency in ((0., 392.), (1.3, 523.25)):
            age = t-start
            if 0 <= age < 1.5:
                envelope = min(1., age/.035)*math.exp(-3.5*age)*min(1., (1.5-age)/.05)
                value += envelope*(math.sin(2*math.pi*frequency*age)+.18*math.sin(4*math.pi*frequency*age))
        samples.append(round(value*16000*max(0, min(30, volume))/100))
    if sys.byteorder != 'little': samples.byteswap()
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed')); wav.writeframes(samples.tobytes())
    return stream.getvalue()


def validate(value):
    if not isinstance(value, dict) or set(value) != {'enabled', 'output', 'volume'}: raise ValueError('Invalid alert settings')
    if type(value['enabled']) is not bool or type(value['volume']) is not int or not 0 <= value['volume'] <= 30: raise ValueError('Choose 0–30% volume')
    if not isinstance(value['output'], str) or value['output'] and not re.fullmatch(r'[A-Za-z0-9_.,:=+-]{1,120}', value['output']): raise ValueError('Choose an ALSA output')
    if value['enabled'] and not value['output']: raise ValueError('Choose the speaker attached to this Pi')
    return dict(value)


class Alerts:
    def __init__(self, request, music, home=None, *, devices=outputs, popen=subprocess.Popen):
        self.request, self.music, self.devices, self.popen = request, music, devices, popen
        self.path = Path(home or Path.home())/'.config/echo-display/alerts.json'
        self.config = {'enabled': False, 'output': '', 'volume': 2}
        self.error = None; self.config_error = False; self.current = None
        self.lock = threading.RLock(); self.stop = threading.Event(); self.cancel = threading.Event()
        self.thread = None; self.player = None; self.client = secrets.token_hex(16)
        self.completed = deque(maxlen=144); self.pending = None; self.retries = {}
        if self.path.exists():
            try:
                info = self.path.stat()
                if self.path.is_symlink() or os.name == 'posix' and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode)&0o077): raise ValueError()
                self.config = validate(json.loads(self.path.read_text(encoding='utf-8')))
            except (OSError, ValueError, TypeError):
                self.config_error = True; self.error = 'Saved alert settings are unreadable; the original file was preserved'

    def settings(self):
        with self.lock:
            return {'supported': True, 'settings': dict(self.config), 'outputs': self.devices(),
                    'current': self.current, 'error': self.error}

    def configure(self, value):
        if self.config_error: raise Unavailable('Repair the saved alert settings before editing them')
        value = validate(value)
        if value['enabled'] and value['output'] not in {d['id'] for d in self.devices()}: raise ValueError('That output is unavailable; no fallback was selected')
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.path.is_symlink(): raise ValueError('Use a regular settings file')
            temp = self.path.with_suffix('.new'); fd = os.open(temp, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as file: json.dump(value, file); file.flush(); os.fsync(file.fileno())
                temp.replace(self.path)
            finally: temp.unlink(missing_ok=True)
            self.config = value; self.error = None; self.interrupt()
        return self.settings()

    def interrupt(self):
        with self.lock:
            self.cancel.set()
            if self.player and self.player.poll() is None:
                try: self.player.terminate(); self.player.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    try: self.player.kill(); self.player.wait(timeout=1)
                    except (OSError, subprocess.TimeoutExpired): pass

    def start(self):
        self.thread = threading.Thread(target=self.run, name='pi-alerts', daemon=True); self.thread.start()

    def close(self):
        self.stop.set(); self.interrupt()
        if self.thread: self.thread.join(8)

    def deliver(self, item, claim, config):
        body = {'occurrence': item['occurrence'], 'token': claim['token'], 'outcome': 'interrupted'}
        path = '/v1/display/alerts/'+item['id']
        if not self.music.claim_idle(self.client):return body
        try:
            with self.lock:
                if self.cancel.is_set() or self.config != config: return body
                self.current = {k: item[k] for k in ('id', 'label')}
            # Only a generated chime is spooled, never speech or microphone data.
            raw = chime(config['volume'])
            with tempfile.TemporaryFile() as source:
                source.write(raw); source.seek(0)
                if not self.request(path+'/check', body)['valid']: return body
                with self.lock:
                    if self.cancel.is_set(): return body
                    self.player = self.popen(['aplay', '-q', '-D', config['output'], '-t', 'wav'],
                                             stdin=source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                started = checked = time.monotonic()
                while self.player.poll() is None:
                    if self.stop.wait(.1) or self.cancel.is_set() or time.monotonic()-started > 8: return body
                    if time.monotonic()-checked > .8:
                        if not self.request(path+'/check', body)['valid']: return body
                        checked = time.monotonic()
                if self.player.returncode == 0 and not self.cancel.is_set(): body['outcome'] = 'played'
                else: body['outcome'] = 'failed'
                return body
        finally:
            self.interrupt()
            with self.lock: self.player = None; self.current = None
            self.music.focus(self.client, False)

    def cycle(self):
        # Retry a delivery receipt without replaying sound after a lost response.
        if self.pending:
            path, body = self.pending
            try: self.request(path, body)
            except Exception as error:
                if getattr(error, 'code', None) not in {404, 409}: raise
            self.pending = None
        with self.lock:
            config = dict(self.config)
            if not config['enabled'] or not config['volume'] or self.config_error: return
        if config['output'] not in {d['id'] for d in self.devices()}: raise Unavailable('Attached alert output is unavailable; sound is waiting')
        with self.music.lock:
            if self.music.held(): return  # Do not chime over a call or microphone capture.
        inbox = self.request('/v1/display/alerts')
        keys = {(i['id'], i['occurrence']) for i in inbox['items']}
        self.retries = {k:v for k,v in self.retries.items() if k in keys}
        item = next((i for i in inbox['items'] if i['audible'] and (i['id'], i['occurrence']) not in self.completed
                     and self.retries.get((i['id'], i['occurrence']), 0) < time.monotonic()), None)
        if not item: return
        key = item['id'], item['occurrence']; self.retries[key] = time.monotonic()+60
        with self.lock: self.cancel.clear()
        path = '/v1/display/alerts/'+item['id']
        claim = self.request(path+'/claim', {'occurrence': item['occurrence']})
        body = self.deliver(item, claim, config)
        if body['outcome'] == 'played': self.completed.append(key)
        self.pending = path+'/receipt', body
        self.request(*self.pending); self.pending = None

    def run(self):
        while not self.stop.wait(2):
            try:
                self.cycle()
                if not self.config_error: self.error = None
            except Exception:
                if not self.config_error: self.error = 'Alert sound is waiting for its output or private connection. Check pairing and audio settings.'
