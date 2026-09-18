from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.core import Assistant, TimerStorageUnavailable


class TimerPersistenceTests(unittest.TestCase):
    def test_damaged_state_is_retained_without_disabling_clock(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'timers.json'
            path.write_text('{broken', encoding='utf-8')
            assistant = Assistant(storage=path)
            self.assertEqual(assistant.respond('what time is it')['status'], 'complete')
            with self.assertRaises(TimerStorageUnavailable): assistant.start_timer(10)
            with self.assertRaises(TimerStorageUnavailable): assistant.timer_states()
            with self.assertRaises(TimerStorageUnavailable): assistant.respond('cancel my timer')
            self.assertEqual(path.read_text(encoding='utf-8'), '{broken')

    def test_failed_atomic_save_rolls_back_new_timer(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'timers.json'
            assistant = Assistant(storage=path)
            first = assistant.start_timer(30)
            before = path.read_bytes()
            with patch.object(Path, 'replace', side_effect=OSError('disk unavailable')):
                with self.assertRaises(TimerStorageUnavailable): assistant.start_timer(10)
            self.assertEqual(list(assistant.timers), [first])
            self.assertEqual(path.read_bytes(), before)

    def test_api_reports_timer_storage_unavailable(self):
        with TemporaryDirectory() as folder:
            root = Path(folder); (root/'local').mkdir()
            (root/'local/timers.json').write_text('{broken', encoding='utf-8')
            client = TestClient(create_app('a'*32, runtime_root=root), base_url='http://127.0.0.1')
            headers = {'Authorization': 'Bearer '+'a'*32}
            self.assertEqual(client.get('/health').json()['timers'], 'unavailable')
            self.assertEqual(client.get('/v1/state', headers=headers).status_code, 503)
            self.assertEqual(client.post('/v1/text', json={'text': 'what time is it'}, headers=headers).status_code, 200)

    def test_restart_retains_remaining_time_and_alarm_ack(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'timers.json'
            first = Assistant(clock=lambda: 10, wall_clock=lambda: 1000, storage=path)
            timer = first.start_timer(30)
            second = Assistant(clock=lambda: 200, wall_clock=lambda: 1020, storage=path)
            self.assertEqual(second.timer_states()[0]['remaining_seconds'], 10)
            third = Assistant(clock=lambda: 5, wall_clock=lambda: 1040, storage=path)
            self.assertTrue(third.timer_states()[0]['finished'])
            self.assertFalse(third.timer_states()[0]['notified'])
            self.assertTrue(third.acknowledge_timer(timer))
            fourth = Assistant(clock=lambda: 0, wall_clock=lambda: 1041, storage=path)
            self.assertTrue(fourth.timer_states()[0]['notified'])
            fourth.dismiss_timer(timer)
            self.assertEqual(Assistant(storage=path).timer_states(), [])

    def test_running_timer_cannot_be_acknowledged(self):
        assistant = Assistant(clock=lambda: 0)
        timer = assistant.start_timer(10)
        self.assertFalse(assistant.acknowledge_timer(timer))
