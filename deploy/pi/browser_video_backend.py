"""Linux Chromium -> private null monitor -> bounded PCM -> echo_processed.

No service/global mixer changes. Only start creates private files and runtime
children. Commands use fixed argv; errors never contain provider/user data.
"""
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

from kiosk import x11_geometry


class BackendUnavailable(RuntimeError):
    pass


class Commands:
    def text(self, argv, *, env=None, timeout=1):
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                                    env={**os.environ, 'LC_ALL': 'C', **(env or {})})
            if result.returncode or len(result.stdout) > 2_000_000:
                raise BackendUnavailable('command_unavailable')
            return result.stdout.decode('utf-8', errors='strict')
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise BackendUnavailable('command_unavailable') from None

    def json(self, argv):
        try:
            return json.loads(self.text(argv))
        except (ValueError, TypeError):
            raise BackendUnavailable('invalid_pulse_response') from None


def null_configuration(socket):
    # Caller supplies only its internally allocated runtime path. Modules cannot
    # subsequently be loaded by clients; no hardware/network discovery exists.
    return ('.fail\n'
            f'load-module module-native-protocol-unix socket={socket} auth-cookie-enabled=0\n'
            'load-module module-null-sink sink_name=echo_video_capture rate=48000 channels=2\n'
            'set-default-sink echo_video_capture\n'
            'set-default-source echo_video_capture.monitor\n')


ALSA_NULL = 'pcm.!default { type null }\npcm.null { type null }\n'


class BrowserVideoBackend:
    def __init__(self, home, commands=None, *, popen=subprocess.Popen, uid=None,
                 system=platform.system, which=shutil.which):
        self.home = Path(home) if home is not None else Path.home()
        self.commands = commands or Commands()
        self.popen, self.uid, self.system, self.which = popen, uid, system, which
        self.runtime = None
        self.processes = {}
        self.output_pids = set()
        self.output_server = None
        self.checked_at = 0.0
        self.writer = self.reader = None
        self.browser = None

    def _uid(self):
        uid = os.getuid() if self.uid is None else self.uid
        if type(uid) is not int or uid < 1:
            raise BackendUnavailable('normal_pi_user_required')
        return uid

    def _list(self, kind, server=None):
        value = self.commands.json(['pactl', '--server=' + (server or self.output_server),
                                    '--format=json', 'list', kind])
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise BackendUnavailable('invalid_pulse_response')
        return value

    @staticmethod
    def _private_directory(path, uid):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise BackendUnavailable('private_runtime_required')

    def _route(self):
        info = self.commands.json(['pactl', '--server=' + self.output_server, '--format=json', 'info'])
        if (not isinstance(info, dict) or info.get('server_name') != 'pulseaudio'
                or not re.fullmatch(r'(?:16\.1|17\.0)(?:[.+~-][A-Za-z0-9.+:~_-]+)?',
                                    str(info.get('server_version', '')))):
            raise BackendUnavailable('unsupported_pulse_server')
        modules = self._list('modules')
        if any(re.fullmatch(r'module-(?:.*-protocol-tcp|tunnel-.*|loopback|rtp-send)',
                            str(m.get('name', ''))) for m in modules):
            raise BackendUnavailable('unsafe_output_route')
        aec = {m['index'] for m in modules if m.get('name') == 'module-echo-cancel'
               and type(m.get('index')) is int}
        sinks = [s for s in self._list('sinks') if s.get('name') == 'echo_processed']
        if len(sinks) != 1 or sinks[0].get('owner_module') not in aec:
            raise BackendUnavailable('processed_output_missing')
        if 'FLAT_VOLUME' in sinks[0].get('flags', []):
            raise BackendUnavailable('flat_volume_route_unsupported')
        return info['server_version']

    def check(self):
        if self.system() != 'Linux':
            raise BackendUnavailable('linux_pulseaudio_required')
        uid = self._uid()
        required = ('pulseaudio', 'pactl', 'parec', 'xrandr')
        if any(not self.which(name) for name in required):
            raise BackendUnavailable('browser_audio_dependencies_missing')
        self.browser = self.which('chromium') or self.which('chromium-browser')
        if not self.browser:
            raise BackendUnavailable('chromium_missing')
        if not ctypes.util.find_library('pulse'):
            raise BackendUnavailable('libpulse_missing')
        root = Path(f'/run/user/{uid}')
        try:
            self._private_directory(root, uid)
            self._private_directory(root / 'echo-audio', uid)
            sock = (root / 'echo-audio/native').lstat()
            if not stat.S_ISSOCK(sock.st_mode) or sock.st_uid != uid:
                raise BackendUnavailable('processed_output_missing')
        except OSError:
            raise BackendUnavailable('processed_output_missing') from None
        self.output_server = f'unix:{root}/echo-audio/native'
        version = self._route()
        installed = self.commands.text(['pulseaudio', '--version']).strip()
        if installed not in {'pulseaudio 16.1', 'pulseaudio 17.0'}:
            raise BackendUnavailable('unsupported_pulse_binary')
        # Explicit X11 target; the existing bare kiosk runs on :0. This is a
        # read-only connection/geometry check, never display power/configuration.
        bounds = self.commands.text(['xrandr', '--query'], env=self._display_env())
        if not x11_geometry(bounds):
            raise BackendUnavailable('display_geometry_unavailable')
        return {'server_version': version}

    def _display_env(self):
        return {'DISPLAY': os.environ.get('DISPLAY', ':0'),
                'XAUTHORITY': os.environ.get('XAUTHORITY', str(self.home / '.Xauthority'))}

    def _launch(self, key, argv, env, *, input_pipe=False, output_pipe=False):
        process = self.popen(argv, stdin=subprocess.PIPE if input_pipe else subprocess.DEVNULL,
                             stdout=subprocess.PIPE if output_pipe else subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=env, bufsize=0,
                             start_new_session=True)
        self.processes[key] = process
        return process

    def start(self, url):
        if not re.fullmatch(r'http://127\.0\.0\.1:8790/display/video-player#[0-9a-f]{32}', url):
            raise BackendUnavailable('invalid_player_url')
        if self.processes or self.runtime or self.output_pids:
            raise BackendUnavailable('output_stop_unconfirmed')
        uid = self._uid()
        self.runtime = Path(tempfile.mkdtemp(prefix='echo-video-', dir=f'/run/user/{uid}'))
        self.runtime.chmod(0o700)
        profile = self.runtime / 'profile'
        (profile / 'Default').mkdir(parents=True, mode=0o700)
        for directory in ('pulse', 'state', 'cache'):
            (self.runtime / directory).mkdir(mode=0o700)
        prefs = {'profile': {'default_content_setting_values': {
            'media_stream_mic': 2, 'media_stream_camera': 2, 'notifications': 2,
            'geolocation': 2, 'automatic_downloads': 2}}}
        files = {'pulse.pa': null_configuration(self.runtime / 'pulse/native'),
                 'alsa.conf': ALSA_NULL, 'client.conf': 'autospawn = no\n',
                 'profile/Default/Preferences': json.dumps(prefs)}
        for name, contents in files.items():
            path = self.runtime / name
            path.write_text(contents, encoding='utf-8')
            path.chmod(0o600)
        server = 'unix:' + str(self.runtime / 'pulse/native')
        env = {**os.environ, **self._display_env(), 'LC_ALL': 'C',
               'PULSE_SERVER': server, 'PULSE_SINK': 'echo_video_capture',
               'PULSE_SOURCE': 'echo_video_capture.monitor',
               'PULSE_RUNTIME_PATH': str(self.runtime / 'pulse'),
               'PULSE_STATE_PATH': str(self.runtime / 'state'),
               'PULSE_CLIENTCONFIG': str(self.runtime / 'client.conf'),
               'ALSA_CONFIG_PATH': str(self.runtime / 'alsa.conf'),
               'XDG_CACHE_HOME': str(self.runtime / 'cache')}
        # Do not let inherited ALSA/Pulse hints or a desktop bus redirect audio.
        for key in ('PULSE_COOKIE', 'ALSA_CARD', 'ALSA_PCM_CARD', 'ALSA_CTL_CARD',
                    'PIPEWIRE_REMOTE', 'DBUS_SESSION_BUS_ADDRESS'):
            env.pop(key, None)
        self._launch('pulse', ['pulseaudio', '-n', '--file=' + str(self.runtime / 'pulse.pa'),
                              '--daemonize=no', '--exit-idle-time=-1', '--use-pid-file=no',
                              '--disable-shm=yes', '--disallow-module-loading=yes',
                              '--disallow-exit=yes', '--log-target=stderr'], env)
        ready = False
        for _ in range(20):
            if self.processes['pulse'].poll() is not None:
                break
            if (self.runtime / 'pulse/native').exists():
                ready = True
                break
            time.sleep(.05)
        if not ready:
            raise BackendUnavailable('private_pulse_start_failed')
        modules = self._list('modules', server)
        if sorted(m.get('name', '') for m in modules) != ['module-native-protocol-unix', 'module-null-sink']:
            raise BackendUnavailable('private_pulse_not_isolated')
        sinks, sources = self._list('sinks', server), self._list('sources', server)
        if (len(sinks) != 1 or sinks[0].get('name') != 'echo_video_capture'
                or len(sources) != 1 or sources[0].get('name') != 'echo_video_capture.monitor'
                or sources[0].get('monitor_of_sink') != sinks[0].get('index')):
            raise BackendUnavailable('private_pulse_not_isolated')
        self.reader = self._launch('reader', ['parec', '--server=' + server,
            '--device=echo_video_capture.monitor', '--raw', '--format=s16le', '--rate=48000',
            '--channels=2', '--latency-msec=40', '--client-name=Echo browser monitor'], env, output_pipe=True)
        self.writer = self._launch('writer', [sys.executable, str(Path(__file__).resolve()),
                                             '--pcm-output'], env, input_pipe=True)
        self.output_pids.add(str(self.writer.pid))
        os.set_blocking(self.reader.stdout.fileno(), False)
        os.set_blocking(self.writer.stdin.fileno(), False)
        bounds = x11_geometry(self.commands.text(['xrandr', '--query'], env=self._display_env()))
        if not bounds:
            raise BackendUnavailable('display_geometry_unavailable')
        self._launch('browser', [self.browser, '--kiosk', '--no-first-run', '--noerrdialogs',
            '--ozone-platform=x11', '--force-device-scale-factor=1', *bounds,
            '--user-data-dir=' + str(profile), '--alsa-input-device=null', '--alsa-output-device=null',
            '--deny-permission-prompts', '--disable-background-mode', '--disable-sync',
            '--disable-extensions', '--disable-session-crashed-bubble',
            '--autoplay-policy=user-gesture-required', url], env)
        self.checked_at = time.monotonic()

    def read(self):
        if any(process.poll() is not None for process in self.processes.values()) or not self.reader:
            raise BackendUnavailable('browser_pipeline_stopped')
        if time.monotonic() - self.checked_at >= .5:
            self._route()
            self.checked_at = time.monotonic()
        try:
            data = os.read(self.reader.stdout.fileno(), 3840)
        except BlockingIOError:
            return b''
        if not data:
            raise BackendUnavailable('browser_pipeline_stopped')
        return data

    def write(self, pcm):
        if not pcm or len(pcm) > 3840 or len(pcm) % 4 or not self.writer:
            raise BackendUnavailable('invalid_pcm_block')
        try:
            written = os.write(self.writer.stdin.fileno(), pcm)
        except (BlockingIOError, BrokenPipeError, OSError):
            raise BackendUnavailable('browser_output_congested') from None
        if written != len(pcm):
            raise BackendUnavailable('browser_output_congested')

    @staticmethod
    def _group_alive(group):
        # Ignore dead zombies, which cannot retain an audio stream or window.
        try:
            for path in Path('/proc').glob('[0-9]*/stat'):
                try:
                    fields = path.read_text().rsplit(')', 1)[1].split()
                    if int(fields[2]) == group and fields[0] != 'Z':
                        return True
                except (OSError, ValueError, IndexError):
                    continue
            return False
        except OSError:
            return True

    @classmethod
    def _terminate(cls, process):
        try:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
                until = time.monotonic() + .4
                while time.monotonic() < until:
                    exited = process.poll() is not None
                    if exited and not cls._group_alive(process.pid):
                        return True
                    time.sleep(.02)
            return False
        except OSError:
            return False
        finally:
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()

    def stop(self):
        # Stop the only physical output first. All other children are confined
        # to the null server/ALSA null even when their shutdown is delayed.
        stopped = True
        for key in ('writer', 'browser', 'reader', 'pulse'):
            process = self.processes.get(key)
            if process:
                if self._terminate(process):
                    self.processes.pop(key)
                else:
                    stopped = False
        self.reader = self.writer = None
        if self.output_pids:
            try:
                streams = self._list('sink-inputs')
                live = set()
                for stream in streams:
                    props = stream.get('properties', {})
                    pid = props.get('application.process.id')
                    if (props.get('application.name') == 'Echo browser output'
                            or props.get('media.name') == 'Browser video') and not pid:
                        stopped = False
                    if pid:
                        live.add(str(pid))
                self.output_pids.intersection_update(live)
            except Exception:
                stopped = False
        stopped = stopped and not self.output_pids and not self.processes
        if stopped and self.runtime:
            # Only the exact mkdtemp directory owned by this backend, never a
            # profile/path supplied by an HTTP request or private configuration.
            root = Path(f'/run/user/{self._uid()}')
            try:
                self._private_directory(self.runtime, self._uid())
                if self.runtime.parent != root or not self.runtime.name.startswith('echo-video-'):
                    return False
                shutil.rmtree(self.runtime)
                self.runtime = None
            except OSError:
                return False
        return stopped


class SampleSpec(ctypes.Structure):
    _fields_ = [('format', ctypes.c_int), ('rate', ctypes.c_uint32), ('channels', ctypes.c_uint8)]


class ChannelVolume(ctypes.Structure):
    _fields_ = [('channels', ctypes.c_uint8), ('values', ctypes.c_uint32 * 32)]


class BufferAttributes(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in ('maxlength', 'tlength', 'prebuf', 'minreq', 'fragsize')]


PA_STREAM_DONT_MOVE = 0x0200  # libpulse public ABI, pulse/def.h.


class PulseOutput:
    """Minimal process-local libpulse client. No recording or default route API."""
    def __init__(self, server, lib=None):
        self.lib = lib or ctypes.CDLL('libpulse.so.0')
        self.mainloop = self.context = self.stream = None
        ptr, integer, size = ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t
        signatures = {
            'pa_mainloop_new': (ptr, []), 'pa_mainloop_get_api': (ptr, [ptr]),
            'pa_mainloop_iterate': (integer, [ptr, integer, ptr]), 'pa_mainloop_free': (None, [ptr]),
            'pa_context_new': (ptr, [ptr, ctypes.c_char_p]),
            'pa_context_connect': (integer, [ptr, ctypes.c_char_p, integer, ptr]),
            'pa_context_get_state': (integer, [ptr]), 'pa_context_disconnect': (None, [ptr]),
            'pa_context_unref': (None, [ptr]),
            'pa_stream_new': (ptr, [ptr, ctypes.c_char_p, ctypes.POINTER(SampleSpec), ptr]),
            'pa_stream_connect_playback': (integer, [ptr, ctypes.c_char_p,
                ctypes.POINTER(BufferAttributes), integer, ctypes.POINTER(ChannelVolume), ptr]),
            'pa_stream_get_state': (integer, [ptr]), 'pa_stream_writable_size': (size, [ptr]),
            'pa_stream_write': (integer, [ptr, ptr, size, ptr, ctypes.c_int64, integer]),
            'pa_stream_disconnect': (integer, [ptr]), 'pa_stream_unref': (None, [ptr]),
            'pa_stream_get_device_name': (ctypes.c_char_p, [ptr]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = result, args
        try:
            self.mainloop = self.lib.pa_mainloop_new()
            if not self.mainloop:
                raise BackendUnavailable('libpulse_connection_failed')
            self.context = self.lib.pa_context_new(self.lib.pa_mainloop_get_api(self.mainloop),
                                                    b'Echo browser output')
            if not self.context or self.lib.pa_context_connect(self.context, server.encode(), 1, None) < 0:
                raise BackendUnavailable('libpulse_connection_failed')
            self._wait(self.lib.pa_context_get_state, self.context, 4, {5, 6})
            sample = SampleSpec(3, 48000, 2)  # PA_SAMPLE_S16LE.
            self.stream = self.lib.pa_stream_new(self.context, b'Browser video', ctypes.byref(sample), None)
            if not self.stream:
                raise BackendUnavailable('libpulse_connection_failed')
            volume = ChannelVolume()
            volume.channels = 2
            volume.values[0] = volume.values[1] = 65536
            attributes = BufferAttributes(7680, 3840, 0, 3840, 0xffffffff)
            if self.lib.pa_stream_connect_playback(self.stream, b'echo_processed', ctypes.byref(attributes),
                    PA_STREAM_DONT_MOVE, ctypes.byref(volume), None) < 0:
                raise BackendUnavailable('processed_output_missing')
            self._wait(self.lib.pa_stream_get_state, self.stream, 2, {3, 4})
            self._validate()
        except Exception:
            self.close()
            raise

    def iterate(self):
        if self.lib.pa_mainloop_iterate(self.mainloop, 0, None) < 0:
            raise BackendUnavailable('libpulse_connection_failed')

    def _wait(self, state, instance, ready, failed):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            self.iterate()
            value = state(instance)
            if value == ready:
                return
            if value in failed:
                break
            time.sleep(.005)
        raise BackendUnavailable('libpulse_connection_failed')

    def _validate(self):
        if (self.lib.pa_context_get_state(self.context) != 4
                or self.lib.pa_stream_get_state(self.stream) != 2
                or self.lib.pa_stream_get_device_name(self.stream) != b'echo_processed'):
            raise BackendUnavailable('processed_output_lost')

    def write(self, pcm):
        self.iterate()
        self._validate()
        if not pcm or len(pcm) > 3840 or len(pcm) % 4:
            raise BackendUnavailable('invalid_pcm_block')
        # Defense at the final process boundary: no full-scale sample can exceed
        # 2%, even if a future caller accidentally omits software attenuation.
        from array import array
        values = array('h')
        values.frombytes(pcm)
        if sys.byteorder != 'little':
            values.byteswap()
        if any(abs(value) > 655 for value in values):
            raise BackendUnavailable('pcm_ceiling_exceeded')
        available = self.lib.pa_stream_writable_size(self.stream)
        if available == ctypes.c_size_t(-1).value or available < len(pcm):
            raise BackendUnavailable('browser_output_congested')
        data = ctypes.create_string_buffer(pcm)
        if self.lib.pa_stream_write(self.stream, data, len(pcm), None, 0, 0) < 0:
            raise BackendUnavailable('browser_output_congested')

    def close(self):
        if self.stream:
            self.lib.pa_stream_disconnect(self.stream)
            self.lib.pa_stream_unref(self.stream)
            self.stream = None
        if self.context:
            self.lib.pa_context_disconnect(self.context)
            self.lib.pa_context_unref(self.context)
            self.context = None
        if self.mainloop:
            self.lib.pa_mainloop_free(self.mainloop)
            self.mainloop = None


def output_main():
    """Owned stdin-only playback process; no configurable server/device/volume."""
    import select
    uid = os.getuid()
    if uid < 1:
        return 1
    output = None
    try:
        output = PulseOutput(f'unix:/run/user/{uid}/echo-audio/native')
        pending = b''
        while True:
            output.iterate()
            output._validate()
            readable, _, _ = select.select([sys.stdin.buffer], [], [], .01)
            if not readable:
                continue
            data = os.read(sys.stdin.fileno(), 3840)
            if not data:
                return 0
            pending += data
            size = min(len(pending) // 4 * 4, 3840)
            if size:
                output.write(pending[:size])
                pending = pending[size:]
    except Exception:
        return 1
    finally:
        if output:
            output.close()


if __name__ == '__main__':
    raise SystemExit(output_main() if sys.argv[1:] == ['--pcm-output'] else 2)
