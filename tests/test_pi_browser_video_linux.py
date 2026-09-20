"""Opt-in Docker-only synthetic null audio. Never opens hardware or a browser."""
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

PI = Path(__file__).resolve().parents[1] / 'deploy' / 'pi'
sys.path.insert(0, str(PI))
from browser_video_backend import BackendUnavailable, BrowserVideoBackend, Commands, PulseOutput


ALLOWED = (sys.platform == 'linux' and os.environ.get('ECHO_VIDEO_NULL_TEST') == '1'
           and Path('/.dockerenv').exists() and not Path('/dev/snd').exists())


@unittest.skipUnless(ALLOWED, 'Explicit isolated Docker null-server check only')
class LinuxNullTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.getuid(), 1000)
        self.root = Path('/run/user/1000/echo-audio')
        self.assertFalse((self.root / 'native').exists())
        self.root.mkdir(mode=0o700, exist_ok=True)
        config = self.root / 'null-test.pa'
        config.write_text('.fail\n'
            f'load-module module-native-protocol-unix socket={self.root}/native auth-cookie-enabled=0\n'
            'load-module module-null-sink sink_name=echo_processed rate=48000 channels=2\n'
            'load-module module-null-sink sink_name=synthetic_fallback rate=48000 channels=2\n'
            'set-default-sink synthetic_fallback\n')
        self.env = {**os.environ, 'PULSE_RUNTIME_PATH': str(self.root),
                    'PULSE_STATE_PATH': str(self.root), 'PULSE_SERVER': 'unix:' + str(self.root / 'native')}
        self.pulse = subprocess.Popen(['pulseaudio', '-n', '--file=' + str(config),
            '--daemonize=no', '--exit-idle-time=-1', '--use-pid-file=no', '--disable-shm=yes',
            '--log-target=stderr'], env=self.env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(self.cleanup_pulse)
        for _ in range(100):
            if (self.root / 'native').exists():
                break
            self.assertIsNone(self.pulse.poll())
            time.sleep(.02)
        self.commands = Commands()
        self.server = self.env['PULSE_SERVER']

    def cleanup_pulse(self):
        self.assertTrue(BrowserVideoBackend._terminate(self.pulse))

    def pulse_list(self, kind):
        return self.commands.json(['pactl', '--server=' + self.server, '--format=json', 'list', kind])

    def test_real_native_sink_removal_does_not_rescue_stream(self):
        output = PulseOutput(self.server)
        self.addCleanup(output.close)
        output.write(b'\0' * 3840)
        for _ in range(20):
            output.iterate()
            time.sleep(.005)
        sinks = self.pulse_list('sinks')
        selected = next(s for s in sinks if s['name'] == 'echo_processed')
        streams = self.pulse_list('sink-inputs')
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]['sink'], selected['index'])
        self.commands.text(['pactl', '--server=' + self.server, 'unload-module', str(selected['owner_module'])])
        for _ in range(100):
            output.iterate()
            try:
                output._validate()
            except BackendUnavailable:
                break
            time.sleep(.005)
        with self.assertRaisesRegex(BackendUnavailable, 'processed_output_lost'):
            output.write(b'\0' * 4)
        self.assertEqual(self.pulse_list('sink-inputs'), [])
        self.assertEqual([s['name'] for s in self.pulse_list('sinks')], ['synthetic_fallback'])

    def test_real_private_pipeline_silence_and_cleanup(self):
        commands = Commands()
        original_text = commands.text
        commands.text = lambda argv, **kwargs: ('HDMI-1 connected primary 800x480+0+0\n'
            if argv == ['xrandr', '--query'] else original_text(argv, **kwargs))
        backend = BrowserVideoBackend(Path.home(), commands)
        backend.output_server, backend.browser = self.server, '/synthetic-browser'
        launch = backend._launch
        def fake_browser(key, argv, env, **kwargs):
            if key == 'browser':
                argv = [sys.executable, '-c', 'import time; time.sleep(30)']
            return launch(key, argv, env, **kwargs)
        backend._launch = fake_browser
        self.addCleanup(backend.stop)
        # Deliberately bypass production check: this test's echo_processed is a
        # null sink, which production check MUST reject as non-AEC.
        with self.assertRaisesRegex(BackendUnavailable, 'processed_output_missing'):
            backend._route()
        backend.start('http://127.0.0.1:8790/display/video-player#' + 'a' * 32)
        runtime = backend.runtime
        self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
        server = 'unix:' + str(runtime / 'pulse/native')
        modules = backend._list('modules', server)
        self.assertEqual(sorted(m['name'] for m in modules), ['module-native-protocol-unix', 'module-null-sink'])
        with self.assertRaises(BackendUnavailable):
            commands.text(['pactl', '--server=' + server, 'load-module', 'module-null-sink'])
        for _ in range(100):
            data = backend.read()
            if data:
                self.assertFalse(any(data))  # Only generated digital silence.
                backend.write(data[:len(data) // 4 * 4])
                break
            time.sleep(.005)
        else:
            self.fail('Null monitor did not deliver silence')
        for _ in range(100):
            if self.pulse_list('sink-inputs'):
                break
            time.sleep(.005)
        self.assertEqual(len(self.pulse_list('sink-inputs')), 1)
        self.assertTrue(backend.stop())
        self.assertEqual(self.pulse_list('sink-inputs'), [])
        self.assertFalse(runtime.exists())


if __name__ == '__main__':
    unittest.main()
