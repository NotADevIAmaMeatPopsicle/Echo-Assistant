import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.core import Assistant

class CoreTests(unittest.TestCase):
    def test_timer_finishes_and_can_be_dismissed(self):
        now = [100.0]
        assistant = Assistant(lambda: now[0])
        timer = assistant.start_timer(30, "Tea")
        self.assertEqual(assistant.timer_states()[0]["remaining_seconds"], 30)
        now[0] = 140
        self.assertTrue(assistant.timer_states()[0]["finished"])
        self.assertTrue(assistant.dismiss_timer(timer))
        self.assertFalse(assistant.dismiss_timer(timer))

    def test_timer_bounds_and_capacity(self):
        assistant = Assistant()
        for value in (0, -1, 86401, True, 2.2):
            with self.assertRaises(ValueError): assistant.start_timer(value)
        for _ in range(16): assistant.start_timer(1)
        with self.assertRaises(ValueError): assistant.start_timer(1)

    def test_supported_intent_and_unconfigured_conversation(self):
        assistant = Assistant()
        self.assertEqual(assistant.respond("Set a timer for 5 minutes.")["capability"], "timer")
        self.assertEqual(assistant.respond("What time is it?")["status"], "complete")
        self.assertEqual(assistant.respond("Tell me a story")["status"], "unavailable")

    def test_spoken_timer_numbers(self):
        assistant = Assistant()
        self.assertEqual(assistant.respond("set a timer for five minutes")["status"], "complete")
        self.assertEqual(assistant.respond("start a timer for twenty two seconds")["status"], "complete")
        self.assertEqual(round(assistant.timer_states()[0]["remaining_seconds"]), 300)
        with self.assertRaises(ValueError): assistant.respond("set a timer for zero seconds")

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app("a"*32))
        self.headers = {"Authorization": "Bearer " + "a"*32}

    def test_auth_blocks_read_and_mutation(self):
        self.assertEqual(self.client.get("/v1/state").status_code, 401)
        self.assertEqual(self.client.post("/v1/timers", json={"seconds": 5}).status_code, 401)

    def test_timer_lifecycle_through_api(self):
        result = self.client.post("/v1/timers", json={"seconds": 5}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        timer = result.json()["id"]
        self.assertEqual(len(self.client.get("/v1/state", headers=self.headers).json()["timers"]), 1)
        self.assertEqual(self.client.delete("/v1/timers/"+timer, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/v1/state", headers=self.headers).json()["timers"], [])

    def test_validation_and_truthful_health(self):
        self.assertEqual(self.client.post("/v1/timers", json={"seconds": True}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post("/v1/text", json={"text": " "}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get("/health").json()["speech_to_text"], "not_configured")

    def test_waiting_listener_never_claims_connected_microphone_or_volume(self):
        with TemporaryDirectory() as directory:
            client = TestClient(create_app('a'*32, runtime_root=Path(directory)), base_url='http://127.0.0.1')
            with patch('backend.app.voice_status', return_value={
                    'status': 'connecting', 'transport': 'wifi', 'engine': 'vosk-local',
                    'phrases': ['hey echo', 'okay echo']}):
                state = client.get('/health').json()
            self.assertEqual(state['device_transport'], 'wifi_waiting')
            self.assertEqual(state['speech_to_text'], 'waiting_for_device')
            self.assertIsNone(state['speaker_muted'])
            self.assertEqual(state['speech_worker'], 'unavailable')

if __name__ == "__main__": unittest.main()
