"""Synthetic Bluetooth/PCM/process checks. Never accesses BlueZ or audio hardware."""
from array import array
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

PI = Path(__file__).resolve().parents[1] / 'deploy' / 'pi'
sys.path.insert(0, str(PI))
from bluetooth_backend import A2DP_SINK, A2DP_SOURCE, BackendUnavailable, BlueZBackend, Commands, PulseBackend
from bluetooth_receiver import BluetoothReceiver, DEFAULT_CONFIG, attenuate, load_private_config, validate_config

PEER = '/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF'
SOURCE = ('bluez_source.AA_BB_CC_DD_EE_FF.a2dp_source', 20, 30)
CONFIG = {**DEFAULT_CONFIG, 'enabled': True, 'device_path': PEER}
FRAME = b'\xff\x7f\x00\x80' * 960


class FakeBlueZ:
    def __init__(self):
        self.state = {'connected': True, 'transport': PEER + '/fd0', 'state': 'active'}
        self.calls = []
        self.error = None

    def inspect(self, config):
        self.calls.append('inspect')
        if self.error:
            raise self.error
        return dict(self.state)

    def disconnect_selected(self, config):
        self.calls.append('disconnect')
        self.state['connected'] = False
        return True


class FakePulse:
    def __init__(self):
        self.calls, self.frames, self.written = [], [], []
        self.source = SOURCE
        self.stop_ok = True
        self.error = None

    def check(self):
        self.calls.append('check')
        if self.error:
            raise self.error
        return {'server_version': '17.0'}

    def selected_source(self, config):
        self.calls.append('source')
        return self.source

    def open_reader(self, source):
        if source != self.source[0]:
            raise AssertionError('Wrong source')
        self.calls.append('reader')

    def read(self):
        return self.frames.pop(0) if self.frames else b''

    def write(self, pcm):
        self.written.append(pcm)

    def stop_output(self):
        self.calls.append('stop')
        return self.stop_ok

    def discard(self):
        self.calls.append('discard')
        self.frames.clear()


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.blue, self.pulse = FakeBlueZ(), FakePulse()
        self.focus = {'held': False, 'ducked': False, 'spotify_active': False,
                      'access_valid': True, 'generation': 1}
        self.age = 0
        self.receiver = BluetoothReceiver(CONFIG, self.snapshot, self.blue, self.pulse, lambda: self.now)

    def snapshot(self):
        return {**self.focus, 'observed_at': self.now - self.age}

    def play(self):
        self.assertTrue(self.receiver.resume())
        self.pulse.frames.append(FRAME)
        self.receiver._step()
        self.assertTrue(self.receiver.snapshot()['output_active'])

    def advance(self):
        self.now += .21
        self.receiver._step()

    def test_disabled_construction_start_close_and_status_are_inert(self):
        callback = Mock(side_effect=AssertionError('Focus must not be called'))
        receiver = BluetoothReceiver(DEFAULT_CONFIG, callback, self.blue, self.pulse)
        self.assertEqual(receiver.start()['phase'], 'disabled')
        self.assertTrue(receiver.close())
        receiver._step()
        self.assertEqual(self.blue.calls, [])
        self.assertEqual(self.pulse.calls, [])
        callback.assert_not_called()

    def test_preflight_is_read_only_and_status_does_not_leak_peer(self):
        self.assertTrue(self.receiver.check()['supported'])
        self.assertEqual(self.pulse.calls, ['check'])
        state = json.dumps(self.receiver.snapshot())
        self.assertNotIn('AA_BB', state)
        self.assertNotIn('/org/bluez', state)
        self.assertFalse(self.pulse.written)

    def test_not_started_cleanup_preserves_unsupported_without_os_calls(self):
        self.pulse.error = BackendUnavailable('safe_bluez_module_required')
        self.assertFalse(self.receiver.check()['supported'])
        self.pulse.calls.clear()
        self.assertTrue(self.receiver.hard_stop('access'))
        self.assertEqual(self.receiver.snapshot()['phase'], 'unsupported')
        self.assertTrue(self.receiver.close())
        self.assertEqual(self.pulse.calls, [])

    def test_initial_stream_requires_new_sender_action(self):
        self.receiver._step()
        self.assertNotIn('reader', self.pulse.calls)
        self.blue.state['state'] = 'idle'
        self.advance()
        self.blue.state['state'] = 'pending'  # Streaming, not yet acquired by PA.
        self.pulse.frames.append(FRAME)
        self.advance()
        self.assertTrue(self.receiver.snapshot()['output_active'])

    def test_exact_ceiling_duck_and_restore_with_phone_full_scale(self):
        self.play()
        self.assertEqual(self.pulse.written[-1], b'\x8f\x02\x71\xfd' * 960)
        self.focus['ducked'] = True
        self.pulse.frames.append(FRAME)
        self.advance()
        self.assertEqual(self.pulse.written[-1], b'\x83\x00\x7d\xff' * 960)
        self.focus['ducked'] = False
        self.pulse.frames.append(FRAME)
        self.advance()
        self.assertEqual(self.pulse.written[-1], b'\x8f\x02\x71\xfd' * 960)

    def test_hard_hold_ack_drops_buffers_and_release_never_replays(self):
        self.play()
        self.pulse.frames.append(FRAME)
        self.focus['held'] = True
        self.assertTrue(self.receiver.hard_stop())
        self.assertFalse(self.receiver.snapshot()['output_active'])
        self.assertEqual(self.pulse.frames, [])
        count = len(self.pulse.written)
        self.focus['held'] = False
        self.now += 16
        self.receiver._step()
        self.assertEqual(len(self.pulse.written), count)
        self.assertEqual(self.receiver.snapshot()['blocked_reason'], 'resume_required')
        self.assertTrue(self.receiver.resume())
        self.receiver._step()
        self.assertEqual(len(self.pulse.written), count)

    def test_only_post_hold_idle_then_stream_resumes(self):
        self.play()
        self.assertTrue(self.receiver.hard_stop())
        self.blue.state['state'] = 'idle'
        self.advance()
        self.blue.state['state'] = 'active'
        self.pulse.frames.append(FRAME)
        self.advance()
        self.assertTrue(self.receiver.snapshot()['output_active'])
        self.assertEqual(len(self.pulse.written), 2)

    def test_stale_access_generation_and_spotify_fail_closed(self):
        for change in ({'access_valid': False}, {'spotify_active': True}, {'generation': 2}, {'held': True}):
            with self.subTest(change=change):
                self.setUp()
                self.play()
                self.focus.update(change)
                self.advance()
                self.assertFalse(self.receiver.snapshot()['output_active'])
                self.assertIn('discard', self.pulse.calls)
                self.assertTrue(self.receiver.latched)
        for age in (1.01, -.1, float('inf'), float('nan')):
            with self.subTest(age=age):
                self.setUp()
                self.play()
                self.age = age
                self.receiver._step()
                self.assertFalse(self.receiver.snapshot()['output_active'])
                self.assertFalse(self.receiver.resume())

    def test_malformed_focus_and_slow_device_evidence_never_open_output(self):
        for changes in ({'generation': True}, {'held': 1}, {'access_valid': None}):
            self.setUp()
            self.focus.update(changes)
            self.assertFalse(self.receiver.resume())
            self.receiver._step()
            self.assertNotIn('reader', self.pulse.calls)
        self.setUp()
        self.assertTrue(self.receiver.resume())
        original = self.blue.inspect
        def slow(config):
            self.now += 1
            return original(config)
        self.blue.inspect = slow
        self.receiver._step()
        self.assertEqual(self.receiver.snapshot()['blocked_reason'], 'stale_source')
        self.assertNotIn('reader', self.pulse.calls)

    def test_unknown_backend_exception_is_sanitized_and_silent(self):
        self.play()
        self.blue.error = RuntimeError('private hostname, address, credential')
        self.advance()
        state = self.receiver.snapshot()
        self.assertFalse(state['output_active'])
        self.assertEqual(state['blocked_reason'], 'backend_unavailable')
        self.assertNotIn('credential', json.dumps(state))
        count = len(self.blue.calls)
        self.advance()
        self.assertEqual(len(self.blue.calls), count, 'Failures back off instead of spawning commands every 20 ms')

    def test_source_generation_and_reader_loss_latch_stop(self):
        self.play()
        self.pulse.source = (SOURCE[0], 21, 31)
        self.advance()
        self.assertEqual(self.receiver.snapshot()['blocked_reason'], 'source_changed')
        self.pulse.frames.append(FRAME)
        self.advance()
        self.assertEqual(len(self.pulse.written), 1)
        self.assertTrue(self.receiver.resume())
        self.pulse.read = Mock(side_effect=BackendUnavailable('media_reader_stopped'))
        self.receiver._step()
        self.assertFalse(self.receiver.snapshot()['output_active'])

    def test_unconfirmed_stop_blocks_capture_resume_and_group_music(self):
        self.play()
        self.pulse.stop_ok = False
        self.assertFalse(self.receiver.hard_stop())
        self.assertTrue(self.receiver.snapshot()['output_active'])
        self.assertFalse(self.receiver.snapshot()['stop_confirmed'])
        self.assertFalse(self.receiver.resume())
        self.pulse.stop_ok = True
        self.assertTrue(self.receiver.hard_stop())
        self.assertFalse(self.receiver.snapshot()['output_active'])

    def test_stop_exception_still_discards_input_and_blocks_capture(self):
        self.play()
        self.pulse.stop_output = Mock(side_effect=RuntimeError('private raw provider error'))
        self.pulse.calls.clear()
        self.assertFalse(self.receiver.hard_stop())
        self.assertIn('discard', self.pulse.calls)
        self.assertEqual(self.receiver.snapshot()['blocked_reason'], 'output_stop_unconfirmed')

    def test_radio_reconnect_is_not_a_resume_command(self):
        self.play()
        self.blue.state['connected'] = False
        self.advance()
        self.blue.state['connected'] = True
        self.pulse.frames.append(FRAME)
        self.advance()
        self.assertFalse(self.receiver.snapshot()['output_active'])
        self.assertEqual(len(self.pulse.written), 1)

    def test_new_hard_hold_wins_race_with_slow_external_inspection(self):
        self.assertTrue(self.receiver.resume())
        entered, released = threading.Event(), threading.Event()
        original = self.blue.inspect
        def wait(config):
            entered.set()
            if not released.wait(2):
                raise AssertionError('Test synchronization failed')
            return original(config)
        self.blue.inspect = wait
        self.pulse.frames.append(FRAME)
        worker = threading.Thread(target=self.receiver._step)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.focus['held'] = True
            self.assertTrue(self.receiver.hard_stop())
        finally:
            released.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.pulse.written, [])

    def test_disconnect_and_close_do_not_remove_bonds_or_restart(self):
        self.play()
        self.assertTrue(self.receiver.disconnect_selected())
        self.assertEqual(self.blue.calls[-1], 'disconnect')
        self.assertFalse(self.receiver.snapshot()['connected'])
        self.assertTrue(self.receiver.close())
        count = len(self.blue.calls)
        self.receiver.start()
        self.receiver._step()
        self.assertEqual(len(self.blue.calls), count)


def bluez_reply():
    objects = {
        '/org/bluez/hci0': {'org.bluez.Adapter1': {'Powered': True, 'UUIDs': [A2DP_SINK]}},
        PEER: {'org.bluez.Device1': {'Paired': True, 'Bonded': True, 'Connected': True,
                                    'Blocked': False, 'Adapter': '/org/bluez/hci0', 'UUIDs': [A2DP_SOURCE]}},
        PEER + '/fd0': {'org.bluez.MediaTransport1': {'Device': PEER, 'UUID': A2DP_SINK,
                                                    'Codec': 0, 'State': 'active'}},
    }
    encoded = {path: {iface: {k: {'type': 'v', 'data': value} for k, value in props.items()}
                      for iface, props in interfaces.items()} for path, interfaces in objects.items()}
    return {'type': 'a{oa{sa{sv}}}', 'data': [encoded]}


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.commands = Mock()
        self.bluez_data = bluez_reply()
        self.commands.json.side_effect = lambda argv: copy.deepcopy(self.bluez_data)
        self.bluez = BlueZBackend(self.commands, system=lambda: 'Linux', which=lambda _: '/synthetic/program')

    def test_bluez_admits_only_selected_bond_sbc_sink_transport(self):
        self.assertEqual(self.bluez.inspect(CONFIG)['state'], 'active')
        objects = self.bluez_data['data'][0]
        device = objects[PEER]['org.bluez.Device1']
        for field in ('Paired', 'Bonded'):
            device[field]['data'] = False
            with self.assertRaises(BackendUnavailable):
                self.bluez.inspect(CONFIG)
            device[field]['data'] = True
        for key, invalid in (('Codec', 2), ('UUID', A2DP_SOURCE), ('Device', PEER + '_OTHER')):
            original = objects[PEER + '/fd0']['org.bluez.MediaTransport1'][key]['data']
            objects[PEER + '/fd0']['org.bluez.MediaTransport1'][key]['data'] = invalid
            if key == 'Device':
                self.assertEqual(self.bluez.inspect(CONFIG)['state'], 'idle')
            else:
                with self.assertRaises(BackendUnavailable):
                    self.bluez.inspect(CONFIG)
            objects[PEER + '/fd0']['org.bluez.MediaTransport1'][key]['data'] = original
        calls = [call.args[0] for call in self.commands.json.call_args_list]
        self.assertTrue(all(argv[-1] == 'GetManagedObjects' for argv in calls))
        self.commands.text.assert_not_called()

    def pulse(self):
        self.modules = [
            {'name': 'module-bluez5-discover', 'index': 7, 'argument': 'headset=native enable_native_hsp_hs=false enable_native_hfp_hf=false avrcp_absolute_volume=false'},
            {'name': 'module-echo-cancel', 'index': 31, 'argument': ''},
        ]
        self.cards = [{'index': 4, 'active_profile': 'a2dp_source',
                       'properties': {'bluez.path': PEER, 'device.api': 'bluez'}}]
        self.sources = [{'index': 20, 'card': 4, 'owner_module': 30, 'name': SOURCE[0],
                         'monitor_source': '',
                         'properties': {'bluetooth.protocol': 'a2dp_source', 'bluetooth.codec': 'sbc'}}]
        self.sinks = [{'name': 'echo_processed', 'owner_module': 31}]
        self.sink_inputs = []
        def text(argv, **kwargs):
            if argv[0] == 'systemctl':
                return 'inactive\n' * 5
            if argv[0] == 'dpkg-query':
                return 'pulseaudio=17.0+dfsg1-2+b1\npulseaudio-module-bluetooth=17.0+dfsg1-2+b1\n'
            if argv[-3:] == ['list', 'short', 'modules']:
                # Actual pactl short rows: ID, name, arguments, usage column.
                return ''.join(f"{m['index']}\t{m['name']}\t{m['argument']}\t\n" for m in self.modules)
            return 'Server Name: pulseaudio\nServer Version: 17.0\n'
        self.commands.text.side_effect = text
        self.commands.json.side_effect = lambda argv: {
            'cards': self.cards, 'sources': self.sources,
            'sinks': self.sinks, 'sink-inputs': self.sink_inputs,
        }[argv[-1]]
        return PulseBackend(self.commands, uid=1000, system=lambda: 'Linux',
                            which=lambda _: '/synthetic/program', socket_check=False)

    def test_pulse_route_joins_card_identity_and_rejects_microphones(self):
        pulse = self.pulse()
        self.assertEqual(pulse.check()['server_version'], '17.0')
        self.assertEqual(pulse.selected_source(CONFIG), SOURCE)
        for change in ({'name': 'echo_cancelled'}, {'monitor_source': 'echo_processed'},
                       {'monitor_source': None}, {'monitor_source': 4294967295}, {'card': 9},
                       {'properties': {'bluetooth.protocol': 'headset_head_unit', 'bluetooth.codec': 'sbc'}},
                       {'properties': {'bluetooth.protocol': 'a2dp_source', 'bluetooth.codec': 'aac'}}):
            original = copy.deepcopy(self.sources[0])
            self.sources[0].update(change)
            with self.assertRaises(BackendUnavailable):
                pulse.selected_source(CONFIG)
            self.sources[0] = original
        self.sources[0].pop('monitor_source')
        with self.assertRaisesRegex(BackendUnavailable, 'non_media_source_rejected'):
            pulse.selected_source(CONFIG)
        self.sources[0]['monitor_source'] = ''
        self.cards[0]['properties']['bluez.path'] = PEER + '_WRONG'
        with self.assertRaises(BackendUnavailable):
            pulse.selected_source(CONFIG)

    def test_unsafe_modules_and_server_defaults_are_never_repaired(self):
        pulse = self.pulse()
        for module in ('module-bluetooth-policy', 'module-loopback', 'module-native-protocol-tcp'):
            self.modules.append({'name': module, 'index': 50, 'argument': ''})
            with self.assertRaises(BackendUnavailable):
                pulse.check()
            self.modules.pop()
        self.modules[0]['argument'] = 'headset=native'
        with self.assertRaises(BackendUnavailable):
            pulse.check()
        all_calls = [call.args[0] for call in self.commands.mock_calls if call.args]
        self.assertFalse(any('load-module' in argv or 'set-default-source' in argv for argv in all_calls))

    def test_pulse_module_ids_are_explicit_and_not_list_positions(self):
        pulse = self.pulse()
        self.assertEqual(pulse._list('modules'), self.modules)
        self.assertTrue(pulse.check()['processed_output'])
        self.commands.text.assert_any_call(
            ['pactl', '--server=unix:/run/user/1000/echo-audio/native', 'list', 'short', 'modules'])
        self.assertFalse(any(call.args[0][-1] == 'modules' for call in self.commands.json.call_args_list))

    def test_pulse_module_ids_reject_malformed_and_ambiguous_rows(self):
        pulse = self.pulse()
        for listing in ('module-echo-cancel\t\t\n', '31 module-echo-cancel\n',
                        '-1\tmodule-echo-cancel\t\t\n', '4294967295\tmodule-echo-cancel\t\t\n',
                        '99999999999\tmodule-echo-cancel\t\t\n', '31\tnot-a-module\t\t\n',
                        '31\tmodule-echo-cancel\t\t\n31\tmodule-null-sink\t\t\n'):
            with self.subTest(listing=listing):
                self.commands.text.side_effect = None
                self.commands.text.return_value = listing
                with self.assertRaisesRegex(BackendUnavailable, 'invalid_pulse_response'):
                    pulse._list('modules')

    def test_processed_sink_requires_matching_integer_aec_owner(self):
        pulse = self.pulse()
        for owner in (None, '31', False, 0, 1, 7):
            with self.subTest(owner=owner):
                self.sinks[0]['owner_module'] = owner
                with self.assertRaisesRegex(BackendUnavailable, 'processed_output_missing'):
                    pulse.check()
        self.sinks[0]['owner_module'] = 31
        self.modules[1]['name'] = 'module-null-sink'
        with self.assertRaisesRegex(BackendUnavailable, 'processed_output_missing'):
            pulse.check()

    def test_mismatched_distribution_packages_or_other_audio_manager_are_unsupported(self):
        pulse = self.pulse()
        original = self.commands.text.side_effect
        def mismatched(argv, **kwargs):
            if argv[0] == 'dpkg-query':
                return 'pulseaudio=17.0+dfsg1-2+b1\npulseaudio-module-bluetooth=16.1+dfsg1-2+b1\n'
            return original(argv, **kwargs)
        self.commands.text.side_effect = mismatched
        with self.assertRaisesRegex(BackendUnavailable, 'matching_distribution_modules_required'):
            pulse.check()
        self.commands.text.side_effect = lambda argv, **kw: 'active\n' * 5 if argv[0] == 'systemctl' else original(argv, **kw)
        with self.assertRaisesRegex(BackendUnavailable, 'competing_audio_manager'):
            pulse.check()

    def test_malformed_bluez_json_is_rejected_before_source_selection(self):
        self.commands.json.return_value = {'type': 'a{oa{sa{sv}}}', 'data': [{'invalid': []}]}
        self.commands.json.side_effect = None
        with self.assertRaises(BackendUnavailable):
            self.bluez.inspect(CONFIG)

    def test_selected_disconnect_works_even_if_its_media_profile_is_rejected(self):
        self.bluez_data['data'][0][PEER + '/fd0']['org.bluez.MediaTransport1']['Codec']['data'] = 2
        self.assertTrue(self.bluez.disconnect_selected(CONFIG))
        argv = self.commands.text.call_args.args[0]
        self.assertEqual(argv[-3:], [PEER, 'org.bluez.Device1', 'Disconnect'])
        self.assertNotIn('RemoveDevice', argv)

    def test_real_child_stop_requires_pulse_sink_removal_ack(self):
        pulse = self.pulse()
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=flags)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        pulse.writer = child
        self.sink_inputs = [{'properties': {'application.process.id': str(child.pid)}}]
        self.assertFalse(pulse.stop_output())
        self.assertIsNotNone(child.poll())
        self.sink_inputs.clear()
        self.assertTrue(pulse.stop_output())

    def test_actual_audio_command_builds_only_explicit_one_way_route(self):
        pulse = self.pulse()
        proc = Mock()
        proc.poll.return_value = None
        proc.stdin.fileno.return_value = 10
        proc.stdout.fileno.return_value = 11
        pulse.popen = Mock(return_value=proc)
        with patch('bluetooth_backend.os.set_blocking'), patch('bluetooth_backend.os.write', return_value=4):
            pulse.open_reader(SOURCE[0])
            pulse.write(b'\0' * 4)
        commands = [call.args[0] for call in pulse.popen.call_args_list]
        self.assertIn('--device=' + SOURCE[0], commands[0])
        self.assertEqual(commands[0][0], 'parec')
        self.assertIn('--device=echo_processed', commands[1])
        self.assertIn('--volume=65536', commands[1])
        self.assertTrue(all('--server=unix:/run/user/1000/echo-audio/native' in c for c in commands))
        for bad in ('default', 'echo_cancelled', 'echo_processed.monitor', 'bluez_source.bad;command'):
            with self.assertRaises(BackendUnavailable):
                pulse.open_reader(bad)
        with patch('bluetooth_backend.os.write', return_value=1):
            with self.assertRaisesRegex(BackendUnavailable, 'media_output_congested'):
                pulse.write(b'\0' * 4)


class ConfigurationTests(unittest.TestCase):
    def test_invalid_private_config_never_repairs_or_broadens(self):
        for change in ({'enabled': True}, {'volume': 3}, {'output': 'default'},
                       {'device_path': PEER, 'adapter': 'hci1'}, {'unexpected': 1}):
            with self.assertRaises(ValueError):
                validate_config({**DEFAULT_CONFIG, **change})
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'bluetooth.json'
            path.write_text(json.dumps(CONFIG), encoding='utf8')
            path.chmod(0o600)
            self.assertEqual(load_private_config(path), CONFIG)
            if os.name == 'posix':
                path.chmod(0o644)
                with self.assertRaises(ValueError):
                    load_private_config(path)
            self.assertTrue(path.exists())

    def test_pcm_rejects_unbounded_partial_or_invalid_duck(self):
        for raw, duck in ((b'\0', False), (b'\0' * 3844, False), (b'\0' * 4, 1)):
            with self.assertRaises(ValueError):
                attenuate(raw, duck)

    def test_command_errors_never_return_private_stderr(self):
        run = Mock(return_value=subprocess.CompletedProcess(['synthetic'], 1, b'private stdout', b'private stderr'))
        with self.assertRaisesRegex(BackendUnavailable, '^command_unavailable$'):
            Commands(run).text(['pactl', 'info'])


if __name__ == '__main__':
    unittest.main()
