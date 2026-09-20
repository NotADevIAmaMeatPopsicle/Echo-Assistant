"""Synthetic PCM, lease, process and native-route checks; no hardware/provider I/O."""
from array import array
from copy import deepcopy
import ctypes
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

PI = Path(__file__).resolve().parents[1] / 'deploy' / 'pi'
sys.path.insert(0, str(PI))
from browser_video import BrowserVideo, attenuate
from browser_video_backend import (ALSA_NULL, BackendUnavailable, BrowserVideoBackend,
    ChannelVolume, PA_STREAM_DONT_MOVE, PulseOutput, null_configuration)

LEASE = 'a' * 32
VIDEO = 'abcdefgh_-1'
FRAME = b'\xff\x7f\x00\x80' * 960


class FakeBackend:
    def __init__(self):
        self.calls, self.frames, self.written = [], [], []
        self.stop_ok, self.error = True, None

    def check(self):
        self.calls.append('check')
        if self.error:
            raise self.error

    def start(self, url):
        self.calls.append(url)

    def read(self):
        return self.frames.pop(0) if self.frames else b''

    def write(self, pcm):
        self.written.append(pcm)

    def stop(self):
        self.calls.append('stop')
        self.frames.clear()
        return self.stop_ok


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.now, self.age = 100., 0.
        self.focus = {'held': False, 'ducked': False, 'spotify_active': False,
                      'access_valid': True, 'generation': 1}
        self.backend = FakeBackend()
        self.receiver = BrowserVideo(Path('/synthetic'), self.focus_snapshot, self.backend, lambda: self.now)
        self.thread = patch('browser_video.threading.Thread').start()
        self.addCleanup(patch.stopall)

    def focus_snapshot(self):
        return {**self.focus, 'observed_at': self.now - self.age}

    def start(self):
        self.assertTrue(self.receiver.start(LEASE, VIDEO))

    def test_construction_snapshot_and_unused_cleanup_inert(self):
        self.receiver.snapshot()
        self.assertTrue(self.receiver.hard_stop())
        self.assertTrue(self.receiver.close())
        self.assertEqual(self.backend.calls, [])

    def test_check_read_only_and_sanitizes_errors(self):
        self.assertEqual(self.receiver.check(), {'available': True, 'error': None})
        self.backend.error = RuntimeError('secret source URL')
        self.assertEqual(self.receiver.check(), {'available': False, 'error': 'backend_unavailable'})
        self.assertTrue(self.receiver.hard_stop())
        self.assertEqual(self.backend.calls, ['check', 'check'])

    def test_id_validation_never_touches_backend(self):
        for lease, video in [(LEASE.upper(), VIDEO), (LEASE + '/x', VIDEO), (LEASE, 'https://bad'),
                             (None, VIDEO), (LEASE, VIDEO + '\n'), (LEASE + '\n', VIDEO)]:
            self.assertFalse(self.receiver.start(lease, video))
        self.assertEqual(self.backend.calls, [])

    def test_fixed_url_and_explicit_start(self):
        self.start()
        self.assertEqual(self.backend.calls, ['check', 'http://127.0.0.1:8790/display/video-player#' + LEASE])
        self.assertTrue(self.receiver.snapshot()['active'])
        self.assertFalse(self.receiver.start('b' * 32, VIDEO))

    def test_competing_or_invalid_focus_refuses_before_probe(self):
        for key in ('held', 'spotify_active', 'access_valid'):
            self.focus[key] = key != 'access_valid'
            self.assertFalse(self.receiver.start(str(len(self.receiver.used_leases)) * 32, VIDEO))
            self.focus[key] = key == 'access_valid'
        self.age = 1.001
        self.assertFalse(self.receiver.start(LEASE, VIDEO))
        self.assertEqual(self.backend.calls, [])

    def test_focus_rechecked_after_slow_start_before_any_pcm(self):
        def start(url):
            self.focus['held'] = True
        self.backend.start = start
        self.assertFalse(self.receiver.start(LEASE, VIDEO))
        self.assertEqual(self.backend.written, [])
        self.assertIn('stop', self.backend.calls)

    def test_generation_change_after_start_is_latched(self):
        self.start()
        self.focus['generation'] += 1
        self.backend.frames.append(FRAME)
        self.assertFalse(self.receiver._step(LEASE))
        self.assertEqual(self.receiver.snapshot()['error'], 'focus_changed')
        self.assertFalse(self.receiver.heartbeat(LEASE))
        self.assertFalse(self.receiver.start(LEASE, VIDEO))
        self.assertEqual(self.backend.written, [])

    def test_stale_focus_access_spotify_and_hold_stop_before_output(self):
        for key, value in [('held', True), ('spotify_active', True), ('access_valid', False)]:
            with self.subTest(key=key):
                self.setUp()
                self.start()
                self.focus[key] = value
                self.backend.frames.append(FRAME)
                self.assertFalse(self.receiver._step(LEASE))
                self.assertEqual(self.backend.written, [])
                self.assertTrue(self.receiver.snapshot()['stop_confirmed'])

    def test_pcm_ceiling_and_ducking(self):
        self.start()
        self.backend.frames.append(FRAME)
        self.receiver._step(LEASE)
        self.assertEqual(array('h', self.backend.written[-1])[:2], array('h', [655, -655]))
        self.focus['ducked'] = True
        self.backend.frames.append(FRAME)
        self.receiver._step(LEASE)
        self.assertEqual(array('h', self.backend.written[-1])[:2], array('h', [131, -131]))

    def test_fractional_pcm_frames_stay_bounded(self):
        self.start()
        self.backend.frames.extend([FRAME[:3], FRAME[3:]])
        self.receiver._step(LEASE)
        self.assertEqual(self.backend.written, [])
        self.receiver._step(LEASE)
        self.assertEqual(len(self.backend.written[0]), 3840)
        self.assertEqual(self.receiver.carry, b'')

    def test_stale_focus_after_slow_backend_read_blocks_pcm(self):
        self.start()
        def read():
            self.now += 2
            return FRAME
        self.backend.read = read
        self.assertFalse(self.receiver._step(LEASE))
        self.assertEqual(self.backend.written, [])

    def test_heartbeat_does_not_touch_os_or_revive_expired_lease(self):
        self.start()
        calls = list(self.backend.calls)
        self.now += 14
        self.assertTrue(self.receiver.heartbeat(LEASE))
        self.assertEqual(self.backend.calls, calls)
        self.now += 15
        self.assertFalse(self.receiver.heartbeat(LEASE))
        self.assertFalse(self.receiver._step(LEASE))
        self.assertEqual(self.receiver.snapshot()['error'], 'lease_expired')

    def test_wrong_lease_cannot_extend_or_drive_worker(self):
        self.start()
        self.assertFalse(self.receiver.heartbeat('b' * 32))
        self.assertFalse(self.receiver._step('b' * 32))
        self.assertTrue(self.receiver.snapshot()['active'])

    def test_stop_failure_blocks_new_start_and_reports_conservative_output(self):
        self.start()
        self.backend.stop_ok = False
        self.assertFalse(self.receiver.hard_stop())
        state = self.receiver.snapshot()
        self.assertFalse(state['active'])
        self.assertTrue(state['output_active'])
        self.assertEqual(state['error'], 'output_stop_unconfirmed')
        self.assertFalse(self.receiver.start('b' * 32, VIDEO))
        self.backend.stop_ok = True
        self.assertTrue(self.receiver.hard_stop())
        self.assertTrue(self.receiver.start('b' * 32, VIDEO))

    def test_stop_exception_does_not_escape(self):
        self.start()
        self.backend.stop = Mock(side_effect=OSError('private error'))
        self.assertFalse(self.receiver.hard_stop())

    def test_old_worker_cannot_write_after_stop_and_new_start(self):
        self.start()
        self.receiver.hard_stop()
        self.assertTrue(self.receiver.start('b' * 32, VIDEO))
        self.backend.frames.append(FRAME)
        self.assertFalse(self.receiver._step(LEASE))
        self.assertEqual(self.backend.written, [])

    def test_external_focus_never_taken_under_receiver_lock(self):
        def focus():
            self.assertFalse(self.receiver.lock._is_owned())
            return self.focus_snapshot()
        self.receiver.focus_snapshot = focus
        self.start()
        self.receiver._step(LEASE)
        self.receiver.snapshot()

    def test_stop_during_initial_external_focus_cancels_late_start(self):
        def focus():
            self.assertTrue(self.receiver.hard_stop('stop'))
            return self.focus_snapshot()
        self.receiver.focus_snapshot = focus
        self.assertFalse(self.receiver.start(LEASE, VIDEO))
        self.assertEqual(self.backend.calls, [])

    def test_stop_serializes_with_start_and_no_late_launch(self):
        # Use real threads just for the race; the audio pump remains disabled.
        patch.stopall()
        real_thread = threading.Thread
        entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
        def launch(url):
            entered.set()
            release.wait(2)
        self.backend.start = launch
        self.receiver._run = lambda lease: None
        starter = real_thread(target=lambda: self.receiver.start(LEASE, VIDEO))
        starter.start()
        self.assertTrue(entered.wait(1))
        stopper = real_thread(target=lambda: (self.receiver.hard_stop(), stopped.set()))
        stopper.start()
        self.assertFalse(stopped.wait(.05))
        release.set()
        starter.join(2)
        stopper.join(2)
        self.assertTrue(stopped.is_set())
        self.assertFalse(self.receiver.snapshot()['active'])


class BackendTests(unittest.TestCase):
    def test_unspecified_home_uses_normal_user_home_without_io(self):
        with patch('browser_video_backend.Path.home', return_value=Path('/synthetic')):
            backend = BrowserVideoBackend(None)
        self.assertEqual(backend.home, Path('/synthetic'))

    def test_null_configuration_has_only_private_protocol_and_null_sink(self):
        text = null_configuration('/run/user/1000/echo-video-test/pulse/native')
        modules = [line.split()[1] for line in text.splitlines() if line.startswith('load-module')]
        self.assertEqual(modules, ['module-native-protocol-unix', 'module-null-sink'])
        self.assertNotIn('type hw', ALSA_NULL)
        self.assertNotIn('include', ALSA_NULL)

    def test_unsupported_platform_inert(self):
        commands, popen = Mock(), Mock()
        backend = BrowserVideoBackend('/synthetic', commands, popen=popen, system=lambda: 'Windows')
        with self.assertRaisesRegex(BackendUnavailable, 'linux_pulseaudio_required'):
            backend.check()
        self.assertTrue(backend.stop())
        commands.text.assert_not_called()
        popen.assert_not_called()

    def test_bad_player_url_does_not_create_runtime_or_process(self):
        backend = BrowserVideoBackend('/synthetic', popen=Mock())
        with self.assertRaisesRegex(BackendUnavailable, 'invalid_player_url'):
            backend.start('https://example.invalid/')
        backend.popen.assert_not_called()
        self.assertIsNone(backend.runtime)

    def test_real_route_must_belong_to_echo_cancellation(self):
        commands = Mock()
        commands.text.return_value = '1\tmodule-null-sink\tsink_name=echo_processed\t\n'
        commands.json.side_effect = [{'server_name': 'pulseaudio', 'server_version': '17.0'},
                                    [{'name': 'echo_processed', 'owner_module': 1}]]
        backend = BrowserVideoBackend('/synthetic', commands)
        backend.output_server = 'unix:/synthetic'
        with self.assertRaisesRegex(BackendUnavailable, 'processed_output_missing'):
            backend._route()

    def test_supported_pulse_routes_use_explicit_module_ids(self):
        for version in ('16.1', '17.0'):
            with self.subTest(version=version):
                commands = Mock()
                commands.text.return_value = ('3\tmodule-native-protocol-unix\t\t\n'
                    '17\tmodule-echo-cancel\tsink_name=echo_processed\t\n')
                commands.json.side_effect = [{'server_name': 'pulseaudio', 'server_version': version},
                    [{'name': 'echo_processed', 'owner_module': 17, 'flags': []}]]
                backend = BrowserVideoBackend('/synthetic', commands)
                backend.output_server = 'unix:/synthetic'
                self.assertEqual(backend._route(), version)
                commands.text.assert_called_once_with(
                    ['pactl', '--server=unix:/synthetic', 'list', 'short', 'modules'])

    def test_module_ids_reject_malformed_or_ambiguous_rows(self):
        for listing in ('module-null-sink\t\t\n', '1 module-null-sink\n',
                        '-1\tmodule-null-sink\t\t\n', '4294967295\tmodule-null-sink\t\t\n',
                        '0\tnot-a-module\t\t\n',
                        '1\tmodule-null-sink\t\t\n1\tmodule-echo-cancel\t\t\n'):
            with self.subTest(listing=listing):
                commands = Mock()
                commands.text.return_value = listing
                backend = BrowserVideoBackend('/synthetic', commands)
                with self.assertRaisesRegex(BackendUnavailable, 'invalid_pulse_response'):
                    backend._list('modules', 'unix:/synthetic')

    def test_private_null_topology_requires_reciprocal_monitor_and_owned_null_module(self):
        # These field names and types match actual pactl 16.1 JSON, including
        # its surprising monitor_source field on both the sink and the source.
        sinks = [{'name': 'echo_video_capture', 'monitor_source': 'echo_video_capture.monitor',
                  'driver': 'module-null-sink.c', 'owner_module': 17}]
        sources = [{'name': 'echo_video_capture.monitor', 'monitor_source': 'echo_video_capture',
                    'driver': 'module-null-sink.c', 'owner_module': 17}]
        cases = [('valid', sinks, sources)]
        for kind, original in (('sink', sinks), ('source', sources)):
            for field, value in (('monitor_source', None), ('monitor_source', 'other'),
                                 ('driver', 'module-alsa-sink.c'), ('owner_module', 3),
                                 ('owner_module', None), ('owner_module', True)):
                changed = deepcopy(original)
                changed[0][field] = value
                cases.append((f'{kind} {field}={value}', changed if kind == 'sink' else sinks,
                              changed if kind == 'source' else sources))
        cases.extend([('extra source', sinks, sources * 2), ('extra sink', sinks * 2, sources),
                      ('no source', sinks, []), ('no sink', [], sources)])
        for label, actual_sinks, actual_sources in cases:
            with self.subTest(label=label):
                commands = Mock()
                commands.text.return_value = ('3\tmodule-native-protocol-unix\t\t\n'
                    '17\tmodule-null-sink\tsink_name=echo_video_capture\t\n')
                commands.json.side_effect = [actual_sinks, actual_sources]
                backend = BrowserVideoBackend('/synthetic', commands)
                if label == 'valid':
                    backend._check_private_server('unix:/synthetic')
                else:
                    with self.assertRaisesRegex(BackendUnavailable, 'private_pulse_not_isolated'):
                        backend._check_private_server('unix:/synthetic')

    def test_stop_needs_process_exit_and_sink_input_disappearance(self):
        backend = BrowserVideoBackend('/synthetic')
        writer = Mock(pid=123)
        backend.processes['writer'] = writer
        backend.output_pids.add('123')
        backend._terminate = Mock(return_value=True)
        backend._list = Mock(return_value=[{'properties': {'application.process.id': '123'}}])
        self.assertFalse(backend.stop())
        backend._list.return_value = []
        self.assertTrue(backend.stop())

    def test_flat_volume_route_cannot_change_shared_sink_gain(self):
        commands = Mock()
        commands.text.return_value = '1\tmodule-echo-cancel\tsink_name=echo_processed\t\n'
        commands.json.side_effect = [{'server_name': 'pulseaudio', 'server_version': '17.0'},
                                    [{'name': 'echo_processed', 'owner_module': 1, 'flags': ['FLAT_VOLUME']}]]
        backend = BrowserVideoBackend(None, commands)
        backend.output_server = 'unix:/synthetic'
        with self.assertRaisesRegex(BackendUnavailable, 'flat_volume_route_unsupported'):
            backend._route()

    def test_unconfirmed_browser_group_also_blocks_acknowledgement(self):
        backend = BrowserVideoBackend('/synthetic')
        backend.processes['browser'] = Mock(pid=123)
        backend._terminate = Mock(return_value=False)
        self.assertFalse(backend.stop())

    def test_no_sink_list_is_not_silence_proof(self):
        backend = BrowserVideoBackend('/synthetic')
        backend.output_pids.add('123')
        backend._list = Mock(side_effect=BackendUnavailable('command_unavailable'))
        self.assertFalse(backend.stop())


def fake_lib():
    lib = Mock()
    for name in ('pa_mainloop_new', 'pa_mainloop_get_api', 'pa_context_new', 'pa_stream_new'):
        getattr(lib, name).return_value = 1
    for name in ('pa_context_connect', 'pa_stream_connect_playback', 'pa_stream_write', 'pa_mainloop_iterate'):
        getattr(lib, name).return_value = 0
    lib.pa_context_get_state.return_value = 4
    lib.pa_stream_get_state.return_value = 2
    lib.pa_stream_get_device_name.return_value = b'echo_processed'
    lib.pa_stream_writable_size.return_value = 7680
    return lib


class NativeOutputTests(unittest.TestCase):
    def test_explicit_sink_unity_volume_and_never_move_flag(self):
        lib = fake_lib()
        def connect(stream, device, attrs, flags, volume, sync):
            self.assertEqual(device, b'echo_processed')
            self.assertEqual(flags, PA_STREAM_DONT_MOVE)
            value = ctypes.cast(volume, ctypes.POINTER(ChannelVolume)).contents
            self.assertEqual((value.channels, value.values[0], value.values[1]), (2, 65536, 65536))
            return 0
        lib.pa_stream_connect_playback.side_effect = connect
        output = PulseOutput('unix:/synthetic', lib)
        output.write(attenuate(FRAME, False))
        lib.pa_stream_write.assert_called_once()
        output.close()

    def test_sink_removal_or_move_fails_without_reconnect_or_fallback(self):
        for state, device in [(3, b'echo_processed'), (2, b'other_sink')]:
            lib = fake_lib()
            output = PulseOutput('unix:/synthetic', lib)
            lib.pa_stream_get_state.return_value = state
            lib.pa_stream_get_device_name.return_value = device
            with self.assertRaisesRegex(BackendUnavailable, 'processed_output_lost'):
                output.write(b'\0' * 4)
            lib.pa_stream_write.assert_not_called()
            lib.pa_stream_connect_playback.assert_called_once()
            output.close()

    def test_final_process_rejects_raw_full_scale_and_congested_output(self):
        lib = fake_lib()
        output = PulseOutput('unix:/synthetic', lib)
        with self.assertRaisesRegex(BackendUnavailable, 'pcm_ceiling_exceeded'):
            output.write(FRAME)
        lib.pa_stream_writable_size.return_value = 0
        with self.assertRaisesRegex(BackendUnavailable, 'browser_output_congested'):
            output.write(b'\0' * 4)
        lib.pa_stream_write.assert_not_called()
        output.close()


if __name__ == '__main__':
    unittest.main()
