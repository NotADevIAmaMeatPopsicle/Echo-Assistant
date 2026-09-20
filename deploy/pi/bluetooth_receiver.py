"""Default-off owner-configured A2DP receive adapter for Deck, never Mini.

The coordinator must wire hard_stop() into synchronous audio focus admission.
Import/construction and disabled start are inert. See docs/PI_BLUETOOTH.md.
"""
from array import array
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time

from bluetooth_backend import BackendUnavailable, BlueZBackend, PulseBackend


DEFAULT_CONFIG = {'version': 1, 'enabled': False, 'adapter': 'hci0',
                  'device_path': '', 'output': 'echo_processed', 'volume': 2}
FOCUS_MAX_AGE = 1.0
SOURCE_MAX_AGE = .75
BLOCK_BYTES = 3840  # 20 ms of stereo signed-16 at 48 kHz.


def validate_config(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_CONFIG):
        raise ValueError('Invalid Bluetooth configuration')
    if type(value['version']) is not int or value['version'] != 1 or type(value['enabled']) is not bool:
        raise ValueError('Invalid Bluetooth configuration')
    if (not isinstance(value['adapter'], str) or not re.fullmatch(r'hci[0-9]{1,2}', value['adapter'])
            or value['output'] != 'echo_processed' or type(value['volume']) is not int or value['volume'] != 2):
        raise ValueError('Bluetooth requires the processed output and unchanged 2% ceiling')
    peer = value['device_path']
    pattern = r'/org/bluez/' + value['adapter'] + r'/dev_(?:[0-9A-F]{2}_){5}[0-9A-F]{2}'
    if not isinstance(peer, str) or (peer and not re.fullmatch(pattern, peer)) or (value['enabled'] and not peer):
        raise ValueError('Select one existing bond on the chosen adapter')
    return dict(value)


def load_private_config(path):
    """No repair, chmod or creation; unreadable originals remain untouched."""
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    if path.is_symlink():
        raise ValueError('Use a regular owner-only Bluetooth configuration')
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > 4096
                or os.name == 'posix' and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077)):
            raise ValueError('Use a regular owner-only Bluetooth configuration')
        with os.fdopen(fd, encoding='utf-8') as stream:
            fd = None
            return validate_config(json.load(stream))
    finally:
        if fd is not None:
            os.close(fd)


def attenuate(pcm, ducked):
    """Final 2% amplitude cap; ducking is exactly 20% of that local ceiling."""
    if len(pcm) > BLOCK_BYTES or len(pcm) % 4 or type(ducked) is not bool:
        raise ValueError('Expected bounded stereo PCM')
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    divisor = 250 if ducked else 50
    for index, sample in enumerate(samples):
        samples[index] = round(sample / divisor)
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()


class BluetoothReceiver:
    def __init__(self, config, focus_snapshot, bluez=None, pulse=None, clock=time.monotonic):
        self.config = validate_config(config)
        self.focus_snapshot = focus_snapshot
        self.bluez, self.pulse = bluez or BlueZBackend(), pulse or PulseBackend()
        self.clock = clock
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.ever_started = False
        self.supported = None
        self.phase = 'disabled' if not self.config['enabled'] else 'ready'
        self.reason = None if not self.config['enabled'] else 'resume_required'
        self.connected = False
        self.output_active = False
        self.latched = True
        self.saw_inactive = False
        self.epoch = 0
        self.generation = None
        self.source = None
        self.transport = None
        self.state = None
        self.state_at = float('-inf')
        self.checked_at = float('-inf')
        self.retry_at = float('-inf')
        self.carry = b''
        self.stop_confirmed = True

    def snapshot(self):
        with self.lock:
            return {'phase': self.phase, 'supported': self.supported,
                    'connected': self.connected, 'output_active': self.output_active,
                    'blocked_reason': self.reason, 'label': 'Owner phone',
                    'output_volume': 2, 'stop_confirmed': self.stop_confirmed}

    def check(self):
        """Read-only backend capability/bond check; no reader/player is opened."""
        try:
            details = self.pulse.check()
            state = self.bluez.inspect(self.config)
            result = {'supported': True, 'blocked_reason': None,
                      'server_version': details['server_version'],
                      'selected_bond': True, 'connected': state['connected']}
        except Exception as error:
            reason = self._reason(error)
            result = {'supported': False, 'blocked_reason': reason, 'selected_bond': False}
        with self.lock:
            self.supported = result['supported']
            if not self.supported and self.config['enabled']:
                self.phase, self.reason = 'unsupported', result['blocked_reason']
        return result

    @staticmethod
    def _reason(error):
        if isinstance(error, BackendUnavailable) and re.fullmatch(r'[a-z_]{1,80}', str(error)):
            return str(error)
        return 'backend_unavailable'

    def _focus(self):
        try:
            value = self.focus_snapshot()
            if (not isinstance(value, dict)
                    or any(type(value.get(k)) is not bool for k in ('held', 'ducked', 'spotify_active', 'access_valid'))
                    or type(value.get('generation')) is not int or value['generation'] < 0
                    or type(value.get('observed_at')) not in (int, float)
                    or not math.isfinite(value['observed_at'])
                    or not 0 <= self.clock() - value['observed_at'] <= FOCUS_MAX_AGE):
                raise ValueError()
            return value
        except Exception:
            # An integration/backend error may contain private data. Never log it.
            return None

    def _stop_locked(self, reason):
        self.epoch += 1
        self.latched, self.saw_inactive = True, False
        self.carry = b''
        self.source, self.state = None, None
        self.state_at = float('-inf')
        stopped = True
        try:
            stopped = self.pulse.stop_output()
        except Exception:
            stopped = False
        try:
            self.pulse.discard()
        except Exception:
            stopped = False
        self.stop_confirmed = stopped is True
        # An unconfirmed stream remains conservatively active for group focus.
        self.output_active = not self.stop_confirmed
        self.phase = 'held' if self.stop_confirmed else 'unavailable'
        self.reason = reason if self.stop_confirmed else 'output_stop_unconfirmed'
        return self.stop_confirmed

    def hard_stop(self, reason='focus'):
        """Synchronous: call outside Spotify's lock, before capture acknowledgement."""
        if reason not in {'focus', 'access', 'spotify', 'shutdown', 'disconnect'}:
            reason = 'focus'
        with self.lock:
            if not self.ever_started and not self.output_active and self.stop_confirmed:
                return True
            return self._stop_locked(reason)

    def _gate_locked(self, focus):
        reason = None
        if focus is None:
            reason = 'stale_focus'
        elif not focus['access_valid']:
            reason = 'access'
        elif focus['held']:
            reason = 'focus'
        elif focus['spotify_active']:
            reason = 'spotify'
        elif self.generation is not None and focus['generation'] != self.generation:
            reason = 'access_changed'
        if focus is not None:
            self.generation = focus['generation']
        if reason:
            # Repeated denied polls must not acquire audio or replay anything.
            if not self.latched or self.output_active or self.reason != reason:
                self._stop_locked(reason)
            return False
        return True

    def start(self):
        with self.lock:
            if not self.config['enabled'] or self.thread is not None:
                return self.snapshot()
            if self.stop_event.is_set():
                return self.snapshot()  # Closed instances cannot be restarted.
        if not self.check()['supported']:
            return self.snapshot()
        with self.lock:
            if self.thread is None and not self.stop_event.is_set():
                self.ever_started = True
                self.thread = threading.Thread(target=self._run, name='pi-bluetooth', daemon=True)
                self.thread.start()
        return self.snapshot()

    def _run(self):
        while not self.stop_event.wait(.02):
            self._step()

    def _step(self):
        """One bounded pump iteration, also used by synthetic hardware-free tests."""
        if not self.config['enabled'] or self.stop_event.is_set():
            return
        with self.lock:
            self.ever_started = True
            if self.clock() < self.retry_at:
                return
        focus = self._focus()
        with self.lock:
            if not self._gate_locked(focus):
                return
            epoch = self.epoch
            needs_state = self.clock() - self.state_at >= .20
        try:
            if needs_state:
                sampled_at = self.clock()
                if sampled_at - self.checked_at >= 1:
                    self.pulse.check()
                    self.checked_at = sampled_at
                state = self.bluez.inspect(self.config)
                source = self.pulse.selected_source(self.config) if state['connected'] and state['state'] in {'pending', 'active'} else None
            else:
                state, source, sampled_at = self.state, self.source, self.state_at
            # Re-read after potentially slow command I/O. Root's hard_stop also
            # increments epoch so an old inspection can never undo a new hold.
            focus = self._focus()
            with self.lock:
                if epoch != self.epoch or self.stop_event.is_set() or not self._gate_locked(focus):
                    return
                if not 0 <= self.clock() - sampled_at <= SOURCE_MAX_AGE:
                    self._stop_locked('stale_source')
                    return
                self.connected = state['connected']
                token = (state['transport'], source)
                if self.transport is not None and source is not None and token != self.transport:
                    self._stop_locked('source_changed')
                    self.transport = token
                    return
                if source is not None:
                    self.transport = token
                self.state, self.source, self.state_at = state, source, sampled_at
                if not self.connected or state['state'] not in {'pending', 'active'}:
                    if self.output_active or self.phase == 'receiving' or self.carry:
                        self._stop_locked('sender_paused')
                    # A connected phone observed idle is fresh pause evidence.
                    # Losing/reacquiring the radio connection alone must never
                    # authorize a reconnecting phone to resume automatically.
                    self.latched = True
                    self.saw_inactive = self.connected
                    self.phase, self.reason = 'ready', 'resume_required'
                    return
                if self.latched:
                    if not self.saw_inactive:
                        self.phase, self.reason = 'held', 'resume_required'
                        return
                    if not self.pulse.stop_output():
                        self._stop_locked('output_stop_unconfirmed')
                        return
                    self.latched, self.saw_inactive = False, False
                self.pulse.open_reader(source[0])
                block = self.pulse.read()
                if not isinstance(block, bytes) or len(block) > BLOCK_BYTES:
                    raise BackendUnavailable('invalid_pcm_block')
                self.carry += block
                size = min(len(self.carry) // 4 * 4, BLOCK_BYTES)
                pcm, self.carry = self.carry[:size], self.carry[size:]
                if len(self.carry) > 3:
                    raise BackendUnavailable('invalid_pcm_block')
                if pcm:
                    self.pulse.write(attenuate(pcm, focus['ducked']))
                    self.output_active = True
                self.phase, self.reason = 'receiving', None
                self.supported, self.stop_confirmed = True, True
        except Exception as error:
            with self.lock:
                self._stop_locked(self._reason(error))
                self.phase = 'unavailable'
                self.retry_at = self.clock() + 1

    def resume(self):
        """Owner action only; never sends Play or accepts stale permission."""
        if not self.config['enabled'] or self.stop_event.is_set():
            return False
        focus = self._focus()
        with self.lock:
            if not self._gate_locked(focus):
                return False
            if not self.stop_confirmed and not self._stop_locked('focus'):
                return False
            self.latched, self.saw_inactive = False, False
            self.epoch += 1
            self.source, self.state = None, None
            self.state_at = float('-inf')
            self.retry_at = float('-inf')
            self.phase, self.reason = 'ready', None
            return True

    def disconnect_selected(self):
        # Stop our output even if the device disappeared; do not touch another
        # phone, remove its bond, or change adapter power/discovery/trust.
        if not self.hard_stop('disconnect'):
            return False
        if not self.config['enabled']:
            return True
        try:
            result = self.bluez.disconnect_selected(self.config)
            with self.lock:
                self.connected = False
            return result is True
        except (BackendUnavailable, OSError, ValueError):
            return False

    def close(self):
        self.stop_event.set()
        stopped = self.hard_stop('shutdown')
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(3)
        with self.lock:
            if stopped:
                self.phase, self.reason, self.connected = 'disabled', None, False
        return stopped and (self.thread is None or not self.thread.is_alive())
