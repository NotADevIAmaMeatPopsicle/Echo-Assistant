import unittest
from concurrent.futures import Future, ThreadPoolExecutor
import json
import httpx
from unittest.mock import Mock
from backend.display import home_lines, HomeDisplay


class HomeDisplayTests(unittest.TestCase):
    def test_tagged_action_round_trip_uses_fake_http_only(self):
        calls=[];write=Mock()
        def handle(request):
            calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
            return httpx.Response(200,json={'status':'accepted'} if request.method=='POST' else {'devices':{}})
        with httpx.Client(base_url='http://round-voice.test',transport=httpx.MockTransport(handle)) as client, ThreadPoolExecutor(max_workers=1) as worker:
            display=HomeDisplay(client,worker,write,clock=lambda:100);display.unit='°F'
            display.receive('EVENT home_action=temp_up request=42')
            display.action.result(timeout=2);display.pump();display.poll.result(timeout=2)
        self.assertEqual(calls,[('POST','/v1/home/thermostat/actions',{'action':'adjust_temperature','value':1,'unit':'°F'}),('GET','/v1/home',None)])
        self.assertEqual([call.args[0] for call in write.call_args_list],[b'HOME_ACK 42 pending\n',b'HOME_ACK 42 accepted\n'])

    def test_tagged_action_matches_its_ack_and_duplicates_do_not_submit(self):
        action, refresh = Future(), Future()
        worker, write = Mock(), Mock()
        worker.submit.side_effect = [action, refresh]
        display = HomeDisplay(Mock(), worker, write, clock=lambda:100)
        display.receive('EVENT home_action=sound_mute request=77')
        display.receive('EVENT home_action=sound_mute request=77')
        display.receive('EVENT home_action=sound_on request=78')
        self.assertEqual(worker.submit.call_count, 1)
        self.assertEqual([call.args[0] for call in write.call_args_list],
                         [b'HOME_ACK 77 pending\n', b'HOME_ACK 77 pending\n', b'HOME_ACK 78 busy\n'])
        action.set_result({'status':'accepted'})
        display.pump()
        self.assertEqual(write.call_args.args[0], b'HOME_ACK 77 accepted\n')
        self.assertIsNone(display.action_request)
        self.assertIs(display.poll, refresh)

    def test_tagged_failures_and_missing_units_never_claim_success(self):
        for result, expected in [({'status':'failed'}, b'HOME_ACK 9 failed\n'),
                                 (RuntimeError('offline'), b'HOME_ACK 9 unavailable\n')]:
            worker, write = Mock(), Mock(); action = Future()
            worker.submit.side_effect = [action, Future()]
            display = HomeDisplay(Mock(), worker, write, clock=lambda:100)
            display.receive('EVENT home_action=mode_cool request=9')
            if isinstance(result, Exception): action.set_exception(result)
            else: action.set_result(result)
            display.pump()
            self.assertEqual(write.call_args.args[0], expected)
        worker, write = Mock(), Mock(); display=HomeDisplay(Mock(), worker, write)
        display.receive('EVENT home_action=temp_up request=10')
        worker.submit.assert_not_called()
        write.assert_called_once_with(b'HOME_ACK 10 unavailable\n')

    def test_invalid_request_ids_and_injected_commands_are_rejected(self):
        worker, write=Mock(), Mock(); display=HomeDisplay(Mock(),worker,write)
        for request in ('0','4294967296','-1','1.5','1\nEVENT home_action=sound_on'):
            display.receive('EVENT home_action=sound_mute request='+request)
        worker.submit.assert_not_called();write.assert_not_called()

    def test_action_completion_discards_the_older_poll(self):
        worker, write = Mock(), Mock(); worker.submit.return_value = Future()
        display = HomeDisplay(Mock(), worker, write, clock=lambda:100)
        stale = Future(); stale.set_result({'devices':{}}); display.poll = stale
        complete = Future(); complete.set_result({'status':'accepted'}); display.action = complete
        display.pump()
        self.assertEqual(write.call_args_list, [unittest.mock.call(b'HOME_RESULT Request accepted\n')])
        self.assertIs(display.poll, worker.submit.return_value)
        worker.submit.assert_called_once_with(display._get)

    def test_missing_or_malformed_data_never_becomes_available(self):
        self.assertTrue(home_lines({})[0].startswith('HOME_TEMP 0 '))
        state = {'devices': {'thermostat': {'status': 'available', 'attributes': {
            'temperature': 70, 'current_temperature': float('nan'), 'min_temp': 45,
            'max_temp': 99, 'temperature_unit': '°F'}}}}
        self.assertTrue(home_lines(state)[0].startswith('HOME_TEMP 0 '))

    def test_off_thermostat_without_target_keeps_mode_available(self):
        state={'devices':{'thermostat':{'status':'available','state':'off','attributes':{
            'temperature':None,'current_temperature':73,'min_temp':45,'max_temp':99,
            'temperature_unit':'°F','hvac_modes':['off','heat','cool','auto']}}}}
        lines=home_lines(state)
        self.assertEqual(lines[0],'HOME_TEMP 0 73 0 F off 45 99\n')
        self.assertEqual(lines[1],'HOME_MODES 1 15\n')

    def test_live_units_and_sound_volume_survive_normalization(self):
        state = {'devices': {
            'thermostat': {'status': 'available', 'state': 'cool', 'attributes': {
                'temperature': 70, 'current_temperature': 71.5, 'min_temp': 45, 'max_temp': 99, 'temperature_unit': '°F'}},
            'soundbar': {'status': 'available', 'state': 'playing', 'attributes': {'volume_level': .17, 'supported_features': 5}}}}
        self.assertEqual(home_lines(state)[:5], ['HOME_TEMP 1 71.5 70 F cool 45 99\n', 'HOME_MODES 1 0\n', 'HOME_SOUND 1 playing 17 5 -1\n', 'HOME_WEATHER 0 0 - -1 Unknown_conditions\n', 'HOME_LIGHTS 0 0 0 0 '+'0'*64+'\n'])

    def test_weather_preserves_units_and_missing_humidity_is_unknown(self):
        state = {'devices':{'weather':{'status':'available', 'state':'partlycloudy',
                 'attributes':{'temperature':20.5, 'temperature_unit':'°C', 'humidity':None}}}}
        self.assertEqual(home_lines(state)[3], 'HOME_WEATHER 1 20.5 C -1 Partly_cloudy\n')
        state['devices']['weather']['attributes']['humidity'] = 48.5
        self.assertEqual(home_lines(state)[3], 'HOME_WEATHER 1 20.5 C 48 Partly_cloudy\n')

    def test_invalid_weather_is_unavailable_and_cannot_inject_commands(self):
        state = {'devices':{'weather':{'status':'available', 'state':'sunny\nVOL+',
                 'attributes':{'temperature':float('nan'), 'temperature_unit':'°F', 'humidity':101}}}}
        self.assertEqual(home_lines(state)[3], 'HOME_WEATHER 0 0 F -1 Unknown_conditions\n')
        state['devices']['weather']['attributes']['temperature'] = 69
        state['devices']['weather']['status'] = 'unavailable'
        self.assertTrue(home_lines(state)[3].startswith('HOME_WEATHER 0 '))

    def test_off_thermostat_still_advertises_modes_and_unknown_volume_stays_unknown(self):
        state = {'devices': {
            'thermostat': {'status': 'available', 'state': 'off', 'attributes': {'hvac_modes': ['off', 'heat', 'cool', 'auto', 'bogus']}},
            'soundbar': {'status': 'available', 'state': 'off', 'attributes': {'supported_features': 12, 'is_volume_muted': False}}}}
        lines = home_lines(state)
        self.assertTrue(lines[0].startswith('HOME_TEMP 0 '))
        self.assertEqual(lines[1], 'HOME_MODES 1 15\n')
        self.assertEqual(lines[2], 'HOME_SOUND 1 off -1 12 0\n')

    def test_new_touch_actions_are_explicit_and_serialized(self):
        for action, expected in [('mode_heat', ('thermostat', 'set_mode', 'heat')),
                                 ('sound_up', ('soundbar', 'adjust_volume', .02)),
                                 ('sound_down', ('soundbar', 'adjust_volume', -.02)),
                                 ('sound_mute', ('soundbar', 'mute', True)),
                                 ('sound_unmute', ('soundbar', 'mute', False))]:
            worker, write = Mock(), Mock()
            worker.submit.return_value = Future()
            display = HomeDisplay(Mock(), worker, write)
            display.receive('EVENT home_action=' + action)
            self.assertEqual(worker.submit.call_args.args[1:], expected)
            display.receive('EVENT home_action=' + action)
            worker.submit.assert_called_once()
            self.assertEqual(write.call_args.args[0], b'HOME_RESULT Busy - please wait\n')
        worker = Mock()
        display = HomeDisplay(Mock(), worker, Mock())
        for action in ('mode_invalid', 'sound_volume=100', 'mode_heat\nEVENT home_action=sound_on'):
            display.receive('EVENT home_action=' + action)
        worker.submit.assert_not_called()
