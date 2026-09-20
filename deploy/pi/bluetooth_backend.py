"""Explicit BlueZ/PulseAudio access for the optional Pi media receiver.

No discovery, pairing, module loading, audio defaults or OS configuration changes.
Commands use argv arrays and a fixed private server. Raw provider output is never
included in errors/status. Construction performs no I/O.
"""
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import stat
import subprocess


A2DP_SOURCE = '0000110a-0000-1000-8000-00805f9b34fb'
A2DP_SINK = '0000110b-0000-1000-8000-00805f9b34fb'
MAX_RESPONSE = 2_000_000


class BackendUnavailable(RuntimeError):
    """Only fixed machine-readable reason codes may leave this module."""


def private_server(uid=None):
    uid = os.getuid() if uid is None else uid
    if type(uid) is not int or uid < 1:
        raise BackendUnavailable('normal_pi_user_required')
    return f'unix:/run/user/{uid}/echo-audio/native'


class Commands:
    def __init__(self, run=subprocess.run):
        self.run = run

    def text(self, argv, *, ok=(0,), timeout=1):
        try:
            result = self.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                              env={**os.environ, 'LC_ALL': 'C', 'SYSTEMD_PAGER': ''})
            if result.returncode not in ok or len(result.stdout) > MAX_RESPONSE:
                raise BackendUnavailable('command_unavailable')
            return result.stdout.decode('utf-8', errors='strict')
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise BackendUnavailable('command_unavailable') from None

    def json(self, argv):
        try:
            return json.loads(self.text(argv))
        except (ValueError, TypeError):
            raise BackendUnavailable('invalid_backend_response') from None


def _unvariant(value):
    if isinstance(value, dict):
        if set(value) == {'type', 'data'}:
            return _unvariant(value['data'])
        return {k: _unvariant(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unvariant(v) for v in value]
    return value


class BlueZBackend:
    def __init__(self, commands=None, *, system=platform.system, which=shutil.which):
        self.commands = commands or Commands()
        self.system, self.which = system, which

    def _objects(self):
        if self.system() != 'Linux' or not self.which('busctl'):
            raise BackendUnavailable('linux_bluez_required')
        reply = self.commands.json(['busctl', '--system', '--json=short', '--timeout=1',
                                    'call', 'org.bluez', '/',
                                    'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects'])
        if not isinstance(reply, dict) or reply.get('type') != 'a{oa{sa{sv}}}':
            raise BackendUnavailable('invalid_bluez_response')
        value = _unvariant(reply)
        if isinstance(value, list) and len(value) == 1:
            value = value[0]  # busctl method replies contain a tuple of arguments.
        if not isinstance(value, dict):
            raise BackendUnavailable('invalid_bluez_response')
        if any(not isinstance(k, str) or not isinstance(v, dict)
               or any(not isinstance(p, dict) for p in v.values()) for k, v in value.items()):
            raise BackendUnavailable('invalid_bluez_response')
        return value

    def inspect(self, config):
        objects = self._objects()
        adapter = objects.get('/org/bluez/' + config['adapter'], {}).get('org.bluez.Adapter1', {})
        if adapter.get('Powered') is not True:
            raise BackendUnavailable('adapter_unpowered_or_missing')
        if A2DP_SINK not in adapter.get('UUIDs', []):
            raise BackendUnavailable('a2dp_receiver_not_registered')
        if not config['device_path']:
            raise BackendUnavailable('owner_bond_selection_required')
        device = objects.get(config['device_path'], {}).get('org.bluez.Device1', {})
        # Bonded is intentionally mandatory; older BlueZ without proof of a
        # persisted bond is unsupported, not silently treated as authorized.
        if device.get('Paired') is not True or device.get('Bonded') is not True:
            raise BackendUnavailable('selected_bond_unavailable')
        if device.get('Blocked') is True or device.get('Adapter') != '/org/bluez/' + config['adapter']:
            raise BackendUnavailable('selected_bond_unavailable')
        if A2DP_SOURCE not in device.get('UUIDs', []):
            raise BackendUnavailable('selected_peer_not_media_source')
        transports = []
        for path, interfaces in objects.items():
            transport = interfaces.get('org.bluez.MediaTransport1', {})
            if transport.get('Device') != config['device_path']:
                continue
            # UUID is the LOCAL endpoint: Deck is A2DP Sink. SBC codec ID is 0.
            if (transport.get('UUID') != A2DP_SINK or type(transport.get('Codec')) is not int
                    or transport['Codec'] != 0):
                raise BackendUnavailable('non_sbc_or_non_media_transport')
            if not path.startswith(config['device_path'] + '/'):
                raise BackendUnavailable('invalid_bluez_response')
            state = transport.get('State')
            if state not in {'idle', 'pending', 'active'}:
                raise BackendUnavailable('unsupported_transport_state')
            transports.append((path, state))
        if len(transports) > 1:
            raise BackendUnavailable('ambiguous_media_transport')
        path, state = transports[0] if transports else ('', 'idle')
        return {'connected': device.get('Connected') is True, 'transport': path, 'state': state}

    def disconnect_selected(self, config):
        # Reconfirm the selection/bond before the only BlueZ mutation in this
        # adapter. No wildcard, adapter disconnect, unpair or trust operations.
        device = self._objects().get(config['device_path'], {}).get('org.bluez.Device1', {})
        if (device.get('Paired') is not True or device.get('Bonded') is not True
                or device.get('Adapter') != '/org/bluez/' + config['adapter']):
            raise BackendUnavailable('selected_bond_unavailable')
        if device.get('Connected') is True:
            self.commands.text(['busctl', '--system', '--timeout=1', 'call', 'org.bluez',
                                config['device_path'], 'org.bluez.Device1', 'Disconnect'])
        return True


class PulseBackend:
    def __init__(self, commands=None, *, uid=None, popen=subprocess.Popen,
                 system=platform.system, which=shutil.which, socket_check=True):
        self.commands = commands or Commands()
        self.uid, self.popen, self.system, self.which = uid, popen, system, which
        self.socket_check = socket_check
        self.reader = None
        self.writer = None
        self.source = None
        self.unconfirmed_pids = set()

    @property
    def server(self):
        return private_server(self.uid)

    def _list(self, kind):
        command = ['pactl', '--server=' + self.server]
        if kind == 'modules':
            # Supported pactl JSON omits module IDs. The short listing supplies
            # the explicit IDs needed for sink ownership; list order is not an ID.
            value, indexes = [], set()
            for line in self.commands.text(command + ['list', 'short', 'modules']).splitlines():
                fields = line.split('\t')
                if (len(fields) != 4 or not re.fullmatch(r'[0-9]{1,10}', fields[0])
                        or not re.fullmatch(r'module-[A-Za-z0-9_-]+', fields[1])):
                    raise BackendUnavailable('invalid_pulse_response')
                index = int(fields[0])
                if index >= 0xffffffff or index in indexes:
                    raise BackendUnavailable('invalid_pulse_response')
                indexes.add(index)
                value.append({'index': index, 'name': fields[1], 'argument': fields[2]})
            return value
        value = self.commands.json(command + ['--format=json', 'list', kind])
        if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
            raise BackendUnavailable('invalid_pulse_response')
        return value

    def check(self):
        if self.system() != 'Linux':
            raise BackendUnavailable('linux_pulseaudio_required')
        if any(not self.which(name) for name in ('pactl', 'parec', 'pacat')):
            raise BackendUnavailable('pulse_utilities_missing')
        states = self.commands.text(['systemctl', '--user', 'is-active', 'pipewire.service',
                                     'pipewire-pulse.service', 'wireplumber.service',
                                     'pulseaudio.service', 'pulseaudio.socket'], ok=(0, 3, 4))
        if len(states.splitlines()) != 5 or any(x not in {'inactive', 'failed', 'unknown'} for x in states.splitlines()):
            raise BackendUnavailable('competing_audio_manager')
        installed = self.commands.text(['dpkg-query', '-W', '-f=${binary:Package}=${Version}\n',
                                        'pulseaudio', 'pulseaudio-module-bluetooth'])
        packages = dict(re.findall(r'^(pulseaudio(?:-module-bluetooth)?)(?::[a-z0-9]+)?=([^\s]+)$', installed, re.MULTILINE))
        if len(packages) != 2 or packages['pulseaudio'] != packages['pulseaudio-module-bluetooth']:
            raise BackendUnavailable('matching_distribution_modules_required')
        if self.socket_check:
            directory = Path(self.server.removeprefix('unix:')).parent
            try:
                info, endpoint = directory.stat(), (directory / 'native').stat()
                uid = os.getuid() if self.uid is None else self.uid
                if (directory.is_symlink() or (directory / 'native').is_symlink()
                        or info.st_uid != uid or stat.S_IMODE(info.st_mode) & 0o077
                        or not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != uid):
                    raise BackendUnavailable('private_pulse_socket_required')
            except OSError:
                raise BackendUnavailable('private_pulse_socket_required') from None
        info = self.commands.text(['pactl', '--server=' + self.server, 'info'])
        fields = dict(re.findall(r'^([^:\n]+):\s*(.*)$', info, re.MULTILINE))
        version = fields.get('Server Version', '')
        if fields.get('Server Name') != 'pulseaudio' or not re.fullmatch(r'(16\.1|17\.0)(?:[.+~-][A-Za-z0-9.+~_-]+)?', version):
            raise BackendUnavailable('unsupported_pulse_server')
        base = re.match(r'\d+\.\d+', version).group()
        if not re.match(r'^(?:\d+:)?' + re.escape(base) + r'(?:[+~.-]|$)', packages['pulseaudio']):
            raise BackendUnavailable('matching_distribution_modules_required')
        modules = self._list('modules')
        if any(m.get('name') in {'module-bluetooth-policy', 'module-loopback', 'module-rtp-send'}
               or re.fullmatch(r'module-(?:.*-protocol-tcp|tunnel-.*)', str(m.get('name', '')))
               for m in modules):
            raise BackendUnavailable('automatic_or_network_audio_route_present')
        discover = [m for m in modules if m.get('name') == 'module-bluez5-discover']
        if len(discover) != 1:
            raise BackendUnavailable('safe_bluez_module_required')
        try:
            pairs = [part.split('=', 1) for part in shlex.split(discover[0].get('argument', ''))]
            args = dict(pairs)
        except (ValueError, TypeError):
            raise BackendUnavailable('safe_bluez_module_required') from None
        if len(args) != len(pairs) or args.get('headset') != 'native' or any(
                args.get(k) not in {'false', 'no', '0'} for k in
                ('enable_native_hsp_hs', 'enable_native_hfp_hf', 'avrcp_absolute_volume')):
            raise BackendUnavailable('safe_bluez_module_required')
        sinks = [s for s in self._list('sinks') if s.get('name') == 'echo_processed']
        aec = {m['index'] for m in modules if m['name'] == 'module-echo-cancel'}
        if (len(sinks) != 1 or type(sinks[0].get('owner_module')) is not int
                or sinks[0]['owner_module'] not in aec):
            raise BackendUnavailable('processed_output_missing')
        return {'server_version': version, 'processed_output': True}

    def selected_source(self, config):
        cards = [c for c in self._list('cards')
                 if c.get('properties', {}).get('bluez.path') == config['device_path']
                 and c.get('properties', {}).get('device.api') == 'bluez']
        if len(cards) != 1:
            raise BackendUnavailable('selected_source_missing')
        card = cards[0]
        if card.get('active_profile') != 'a2dp_source':
            raise BackendUnavailable('non_media_source_rejected')
        sources = []
        for source in self._list('sources'):
            if source.get('card') != card.get('index'):
                continue
            props, name = source.get('properties', {}), source.get('name', '')
            if (props.get('bluetooth.protocol') != 'a2dp_source'
                    or props.get('bluetooth.codec') != 'sbc'
                    # pactl 16.1/17.0 reports the monitored sink's name here,
                    # or an explicit empty string for a non-monitor source.
                    or source.get('monitor_source') != ''
                    or not re.fullmatch(r'bluez_source\.[A-Fa-f0-9_:]+\.a2dp_source(?:\.\d+)?', name)):
                raise BackendUnavailable('non_media_source_rejected')
            if type(source.get('index')) is not int or type(source.get('owner_module')) is not int:
                raise BackendUnavailable('invalid_pulse_response')
            sources.append((name, source['index'], source['owner_module']))
        if len(sources) != 1:
            raise BackendUnavailable('selected_source_missing')
        return sources[0]

    def open_reader(self, source):
        if not re.fullmatch(r'bluez_source\.[A-Fa-f0-9_:]+\.a2dp_source(?:\.\d+)?', source):
            raise BackendUnavailable('non_media_source_rejected')
        if self.reader and self.source == source and self.reader.poll() is None:
            return
        self.close_reader()
        self.reader = self.popen(['parec', '--server=' + self.server, '--device=' + source,
                                 '--raw', '--format=s16le', '--rate=48000', '--channels=2',
                                 '--latency-msec=40', '--client-name=Echo Bluetooth input'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, bufsize=0)
        os.set_blocking(self.reader.stdout.fileno(), False)
        self.source = source

    def read(self):
        if not self.reader or self.reader.poll() is not None:
            raise BackendUnavailable('media_reader_stopped')
        try:
            block = os.read(self.reader.stdout.fileno(), 3840)  # At most 20 ms.
        except BlockingIOError:
            return b''
        if not block:
            raise BackendUnavailable('media_reader_stopped')
        return block

    def discard(self):
        # Closing the recording stream discards server and OS-pipe queues. A
        # later resume opens a fresh stream, never an accumulated pipe backlog.
        self.close_reader()

    def write(self, pcm):
        if len(pcm) > 3840 or len(pcm) % 4:
            raise BackendUnavailable('invalid_pcm_block')
        if not pcm:
            return
        if self.unconfirmed_pids:
            raise BackendUnavailable('output_stop_unconfirmed')
        if not self.writer:
            self.writer = self.popen(['pacat', '--server=' + self.server, '--device=echo_processed',
                                     '--playback', '--raw', '--format=s16le', '--rate=48000',
                                     '--channels=2', '--latency-msec=40', '--volume=65536',
                                     '--client-name=Echo Bluetooth output', '--stream-name=Bluetooth media'],
                                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, bufsize=0)
            os.set_blocking(self.writer.stdin.fileno(), False)
        if self.writer.poll() is not None:
            raise BackendUnavailable('media_output_stopped')
        # No growing queue. A congested output is a failure, not delayed replay.
        try:
            written = os.write(self.writer.stdin.fileno(), pcm)
        except (BlockingIOError, BrokenPipeError):
            raise BackendUnavailable('media_output_congested') from None
        if written != len(pcm):
            raise BackendUnavailable('media_output_congested')

    @staticmethod
    def _terminate(process):
        if not process:
            return True
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=.4)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=.4)
            except (OSError, subprocess.TimeoutExpired):
                return False
        finally:
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()
        return process.poll() is not None

    def stop_output(self):
        writer = self.writer
        if writer:
            self.unconfirmed_pids.add(str(writer.pid))
            if not self._terminate(writer):
                return False
            self.writer = None
        if self.unconfirmed_pids:
            try:
                inputs = self._list('sink-inputs')
                live = set()
                for stream in inputs:
                    props = stream.get('properties', {})
                    pid = props.get('application.process.id')
                    if (props.get('application.name') == 'Echo Bluetooth output'
                            or props.get('media.name') == 'Bluetooth media') and not pid:
                        return False
                    if pid:
                        live.add(str(pid))
            except BackendUnavailable:
                return False
            self.unconfirmed_pids.intersection_update(live)
        return not self.unconfirmed_pids

    def close_reader(self):
        if self.reader and not self._terminate(self.reader):
            raise BackendUnavailable('media_reader_stop_failed')
        self.reader, self.source = None, None

    def close(self):
        stopped = self.stop_output()
        self.close_reader()
        return stopped


def inventory(commands=None, *, system=platform.system, which=shutil.which):
    """Read installed/candidate versions from the LOCAL apt cache, never update it."""
    result = {'platform': system(), 'architecture': platform.machine(), 'packages': {},
              'competing_audio_manager': None, 'rfkill_blocked': None}
    if result['platform'] != 'Linux':
        return result
    commands = commands or Commands()
    try:
        os_release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines()
                          if '=' in line and not line.startswith('#'))
        result['os'] = {k: os_release.get(k, '').strip('"')[:80]
                        for k in ('ID', 'VERSION_ID', 'VERSION_CODENAME')}
        blocked = []
        for entry in Path('/sys/class/rfkill').glob('rfkill*'):
            if (entry / 'type').read_text().strip() == 'bluetooth':
                blocked.append(any((entry / x).read_text().strip() == '1' for x in ('soft', 'hard')))
        result['rfkill_blocked'] = any(blocked)
    except (OSError, ValueError):
        pass
    if which('apt-cache'):
        for package in ('bluez', 'pulseaudio', 'pulseaudio-module-bluetooth', 'pulseaudio-utils', 'systemd'):
            try:
                # Pi apt-cache can take longer than the live audio probe budget.
                text = commands.text(['apt-cache', 'policy', package], timeout=5)
                values = dict(re.findall(r'^\s*(Installed|Candidate):\s*([A-Za-z0-9.+:~_()-]+)\s*$', text, re.MULTILINE))
                result['packages'][package] = {k.lower(): v for k, v in values.items()}
            except BackendUnavailable:
                result['packages'][package] = {}
    try:
        states = commands.text(['systemctl', '--user', 'is-active', 'pipewire.service',
                                'pipewire-pulse.service', 'wireplumber.service',
                                'pulseaudio.service', 'pulseaudio.socket'], ok=(0, 3, 4))
        result['competing_audio_manager'] = any(x == 'active' for x in states.splitlines())
    except BackendUnavailable:
        pass
    return result
