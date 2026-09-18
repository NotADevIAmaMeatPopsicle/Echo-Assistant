import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.home import HomeBridge, HomeConfig, HomeUnavailable


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.climate = {"state": "heat", "attributes": {"temperature": 70,
            "min_temp": 50, "max_temp": 88, "hvac_modes": ["off", "heat", "cool"]}}
        self.soundbar = {"state": "playing", "attributes": {"supported_features": 4 | 8 | 1,
            "volume_level": .1, "media_title": "Example"}}
        self.config = HomeConfig(True, "http://192.168.1.2:8123", "private-token",
            {"thermostat": "climate.example", "soundbar": "media_player.example", "weather": "weather.example"})

        def request(req):
            self.requests.append(req)
            self.assertEqual(req.headers["Authorization"], "Bearer private-token")
            if req.url.path == "/api/config":
                return httpx.Response(200, json={"unit_system": {"temperature": "°F"}})
            if req.url.path == "/api/states/climate.example":
                return httpx.Response(200, json=self.climate)
            if req.url.path == "/api/states/media_player.example":
                return httpx.Response(200, json=self.soundbar)
            if req.url.path == "/api/states/weather.example":
                return httpx.Response(200, json={"state": "unavailable", "attributes": {}})
            if req.url.path.startswith("/api/services/"):
                return httpx.Response(200, json=[])
            return httpx.Response(404)

        self.bridge = HomeBridge(self.config, httpx.MockTransport(request))

    def test_disabled_adapter_never_connects_and_preserves_bindings(self):
        config = HomeConfig(entities={"thermostat": "climate.example"})
        def forbidden(_):
            self.fail("A disabled adapter must not make a request")
        bridge = HomeBridge(config, httpx.MockTransport(forbidden))
        self.assertEqual(bridge.snapshot()["devices"]["thermostat"]["status"], "not_configured")
        with self.assertRaises(HomeUnavailable): bridge.act("thermostat", "set_temperature", 70, "°F")

    def test_local_origins_only(self):
        for url in ("https://example.com", "http://8.8.8.8", "http://127.0.0.1@8.8.8.8",
                    "http://192.168.1.2/path", "http://192.168.1.2#fragment",
                    "http://user:password@192.168.1.2"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                HomeConfig(True, url, "token", {"thermostat": "climate.example"})
        with self.assertRaises(ValueError):
            HomeConfig(entities={"thermostat": "climate.example/../../services"})

    def test_unavailable_state_and_attribute_filter(self):
        self.climate["attributes"]["private_attribute"] = "do not expose"
        snapshot = self.bridge.snapshot()
        self.assertNotIn("private_attribute", snapshot["devices"]["thermostat"]["attributes"])
        self.assertEqual(snapshot["devices"]["weather"]["status"], "unavailable")

    def test_thermostat_units_bounds_and_current_mode(self):
        for value, unit in ((70, "°C"), (89, "°F"), (True, "°F"), (float("nan"), "°F")):
            with self.assertRaises(ValueError): self.bridge.act("thermostat", "set_temperature", value, unit)
        self.assertFalse(any(r.method == "POST" for r in self.requests))
        result = self.bridge.act("thermostat", "set_temperature", 72, "°F")
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(json.loads(self.requests[-1].content), {"entity_id": "climate.example", "temperature": 72})
        self.climate["state"] = "heat_cool"
        with self.assertRaises(ValueError): self.bridge.act("thermostat", "set_temperature", 71, "°F")
        with self.assertRaises(ValueError): self.bridge.act("thermostat", "set_mode", "auto")

    def test_soundbar_capabilities_and_exact_services(self):
        self.bridge.act("soundbar", "pause")
        self.assertEqual(self.requests[-1].url.path, "/api/services/media_player/media_pause")
        for action, value in (("next", None), ("volume", 1.1), ("volume", True), ("mute", "false")):
            with self.assertRaises(ValueError): self.bridge.act("soundbar", action, value)
        self.bridge.act("soundbar", "mute", True)
        self.assertTrue(json.loads(self.requests[-1].content)["is_volume_muted"])

    def test_relative_volume_uses_fresh_state_bounds_and_current_capabilities(self):
        self.soundbar['attributes']['volume_level'] = .17
        self.bridge.act('soundbar', 'adjust_volume', .02)
        self.assertEqual(json.loads(self.requests[-1].content)['volume_level'], .19)
        self.soundbar['attributes']['volume_level'] = .99
        self.bridge.act('soundbar', 'adjust_volume', .02)
        self.assertEqual(json.loads(self.requests[-1].content)['volume_level'], 1)
        self.soundbar['attributes']['volume_level'] = .01
        self.bridge.act('soundbar', 'adjust_volume', -.02)
        self.assertEqual(json.loads(self.requests[-1].content)['volume_level'], 0)
        for value in (.5, True, float('nan')):
            with self.assertRaises(ValueError): self.bridge.act('soundbar', 'adjust_volume', value)
        self.soundbar['attributes']['volume_level'] = None
        with self.assertRaises(HomeUnavailable): self.bridge.act('soundbar', 'adjust_volume', .02)
        self.soundbar['attributes']['supported_features'] = 0
        with self.assertRaises(ValueError): self.bridge.act('soundbar', 'adjust_volume', .02)

    def test_mode_write_rechecks_supported_modes(self):
        self.bridge.act('thermostat', 'set_mode', 'heat')
        self.assertEqual(json.loads(self.requests[-1].content)['hvac_mode'], 'heat')
        self.climate['attributes']['hvac_modes'] = ['off']
        before = sum(r.method == 'POST' for r in self.requests)
        with self.assertRaises(ValueError): self.bridge.act('thermostat', 'set_mode', 'heat')
        self.assertEqual(sum(r.method == 'POST' for r in self.requests), before)

    def test_redirect_failure_does_not_forward_token(self):
        calls = []
        def redirect(req):
            calls.append(req)
            return httpx.Response(302, headers={"Location": "http://8.8.8.8/"})
        bridge = HomeBridge(self.config, httpx.MockTransport(redirect))
        with self.assertRaises(HomeUnavailable): bridge.act("soundbar", "pause")
        self.assertEqual(len(calls), 1)

    def test_config_does_not_require_or_read_credentials_when_disabled(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "local").mkdir()
            (root / "local/home.json").write_text('{"enabled":false,"entities":{"soundbar":"media_player.example"}}')
            config = HomeConfig.load(root)
            self.assertFalse(config.enabled)
            self.assertEqual(config.token, "")

    def test_api_auth_unavailable_and_accepted_are_distinct(self):
        client = TestClient(create_app("a" * 32, self.bridge))
        headers = {"Authorization": "Bearer " + "a" * 32}
        path = "/v1/home/soundbar/actions"
        self.assertEqual(client.get("/v1/home").status_code, 401)
        self.assertEqual(client.post(path, json={"action": "pause"}).status_code, 401)
        response = client.post(path, json={"action": "volume", "value": .05}, headers=headers)
        self.assertEqual(response.json()["status"], "accepted")
        self.soundbar["state"] = "unavailable"
        self.assertEqual(client.post(path, json={"action": "pause"}, headers=headers).status_code, 503)

    def test_spoken_home_queries_read_current_state_without_writes(self):
        self.climate['attributes']['current_temperature'] = 68
        result = self.bridge.answer('What is the temperature?')
        self.assertEqual(result['text'], 'Indoors 68°F, set 70°F')
        self.assertEqual(self.bridge.answer('Is the soundbar on?')['text'], 'Soundbar is playing')
        self.assertEqual(self.bridge.answer('What is the weather?')['status'], 'unavailable')
        self.assertIsNone(self.bridge.answer('Change every device'))
        self.assertFalse(any(r.method=='POST' for r in self.requests))

    def test_explicit_voice_control_and_temperature_adjustment(self):
        result = self.bridge.answer('Set the thermostat to seventy two degrees')
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(json.loads(self.requests[-1].content)['temperature'], 72)
        self.bridge.act('thermostat', 'adjust_temperature', -1, '°F')
        self.assertEqual(json.loads(self.requests[-1].content)['temperature'], 69)
        with self.assertRaises(ValueError): self.bridge.act('thermostat', 'adjust_temperature', 10, '°F')
        self.assertEqual(self.bridge.answer('Pause the soundbar')['status'], 'accepted')
        before = len(self.requests)
        self.assertIsNone(self.bridge.answer('Maybe pause every soundbar'))
        self.assertEqual(len(self.requests), before)

    def test_spoken_soundbar_controls_use_exact_fresh_capabilities_and_payloads(self):
        self.soundbar['attributes']['supported_features'] = 4 | 8 | 16 | 32
        cases = [
            ('Set the soundbar volume to twenty five percent.', 'volume_set', {'volume_level': .25}),
            ('set soundbar volume to zero percent', 'volume_set', {'volume_level': 0}),
            ('set soundbar volume to one hundred percent', 'volume_set', {'volume_level': 1}),
            ('set soundbar volume to 42 percent', 'volume_set', {'volume_level': .42}),
            ('Set the soundbar volume to 20%.', 'volume_set', {'volume_level': .2}),
            ('Mute the sound bar', 'volume_mute', {'is_volume_muted': True}),
            ('UNMUTE  the soundbar!', 'volume_mute', {'is_volume_muted': False}),
            ('turn the soundbar volume up', 'volume_set', {'volume_level': .12}),
            ('turn down the soundbar', 'volume_set', {'volume_level': .08}),
            ('next track on the soundbar', 'media_next_track', {}),
            ('play the previous song on sound bar', 'media_previous_track', {}),
        ]
        for phrase, service, values in cases:
            with self.subTest(phrase=phrase):
                self.requests.clear()
                result = self.bridge.answer(phrase)
                self.assertEqual(result['status'], 'accepted')
                self.assertEqual([r.method for r in self.requests], ['GET', 'POST'])
                self.assertEqual(self.requests[-1].url.path, '/api/services/media_player/' + service)
                self.assertEqual(json.loads(self.requests[-1].content), {'entity_id': 'media_player.example', **values})
                self.assertEqual(type(json.loads(self.requests[-1].content).get('is_volume_muted', False)), bool)

    def test_voice_controls_reject_unavailable_unsupported_or_invalid_volume(self):
        for phrase in ('set soundbar volume to 101 percent', 'set soundbar volume to banana percent'):
            with self.subTest(phrase=phrase):
                self.assertEqual(self.bridge.answer(phrase)['status'], 'unavailable')
        self.soundbar['attributes']['supported_features'] = 0
        for phrase in ('mute soundbar', 'set soundbar volume to ten percent',
                       'turn up the soundbar', 'next song on the soundbar'):
            self.assertEqual(self.bridge.answer(phrase)['status'], 'unavailable')
        self.soundbar['attributes']['supported_features'] = 4 | 8
        self.soundbar['attributes']['volume_level'] = None
        self.assertEqual(self.bridge.answer('turn down soundbar')['status'], 'unavailable')
        self.soundbar['state'] = 'unavailable'
        self.assertEqual(self.bridge.answer('unmute soundbar')['status'], 'unavailable')
        self.assertFalse(any(r.method == 'POST' for r in self.requests))

    def test_soundbar_voice_never_guesses_target_or_interprets_negation(self):
        for phrase in ('mute', 'volume down', 'set volume to fifty percent',
                       'do not mute the soundbar', 'maybe turn up the soundbar',
                       'unmute every soundbar', 'next track', 'pause music',
                       'set soundbar volume to ten percent and play music',
                       'set soundbar volume to -1 percent'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(self.bridge.answer(phrase))
        self.assertEqual(self.requests, [])

    def test_spoken_volume_and_mute_queries_require_real_values_and_never_write(self):
        self.soundbar['attributes']['volume_level'] = .17
        self.soundbar['attributes']['is_volume_muted'] = False
        self.assertEqual(self.bridge.answer("What's the sound bar volume?")['text'], 'Soundbar volume is 17 percent.')
        self.assertEqual(self.bridge.answer('Is the soundbar muted?')['text'], 'Soundbar is not muted.')
        self.soundbar['attributes']['is_volume_muted'] = True
        self.assertEqual(self.bridge.answer('Is the soundbar muted?')['text'], 'Soundbar is muted.')
        for value in (None, True, float('nan'), -1, 1.1, '0.2'):
            self.soundbar['attributes']['volume_level'] = value
            self.assertEqual(self.bridge.answer('What is the soundbar volume?')['status'], 'unavailable')
        for value in (None, 0, 1, 'false'):
            self.soundbar['attributes']['is_volume_muted'] = value
            self.assertEqual(self.bridge.answer('Is the soundbar muted?')['status'], 'unavailable')
        self.assertFalse(any(r.method == 'POST' for r in self.requests))

    def test_authenticated_text_api_routes_soundbar_commands_without_real_hardware(self):
        client = TestClient(create_app('a' * 32, self.bridge))
        phrase = {'text': 'Set soundbar volume to nineteen percent'}
        self.assertEqual(client.post('/v1/text', json=phrase).status_code, 401)
        self.assertEqual(self.requests, [])
        result = client.post('/v1/text', json=phrase, headers={'Authorization': 'Bearer ' + 'a' * 32})
        self.assertEqual(result.json()['status'], 'accepted')
        self.assertEqual(json.loads(self.requests[-1].content), {'entity_id': 'media_player.example', 'volume_level': .19})


if __name__ == "__main__": unittest.main()
