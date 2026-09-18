from concurrent.futures import Future
import unittest
from unittest.mock import patch
from backend.alarms import Alarms


class Worker:
    def __init__(self): self.calls = []
    def submit(self, function, *args):
        future = Future()
        self.calls.append((function, args, future))
        return future


class AlarmTests(unittest.TestCase):
    def setUp(self):
        self.worker = Worker(); self.lines = []
        self.alarms = Alarms(None, self.worker, self.lines.append)
        self.alarms.available = True
        self.alarms.timers = [{'id': 'a', 'remaining_seconds': 0, 'finished': True, 'notified': False}]
        self.alarms.next_poll = float('inf')

    def test_only_successful_delivery_acknowledges(self):
        self.alarms.pump()
        self.assertEqual(len(self.worker.calls), 1)
        self.worker.calls[0][2].set_result(b'\0\0')
        self.assertEqual(self.alarms.take(), b'\0\0')
        self.assertIsNone(self.alarms.action)
        self.alarms.finished()
        self.assertEqual(self.worker.calls[-1][1], ('POST', '/v1/timers/a/ack'))

    def test_dismiss_cancels_pending_speech(self):
        self.alarms.pump()
        self.assertTrue(self.alarms.receive('EVENT timer_action=dismiss'))
        self.assertIsNone(self.alarms.take())
        self.assertTrue(self.worker.calls[0][2].cancelled())
        self.assertEqual(self.worker.calls[-1][1], ('DELETE', '/v1/timers/a'))

    def test_dismissing_another_timer_does_not_stop_alarm(self):
        self.alarms.pump()
        self.alarms.timers.append({'id': 'b', 'remaining_seconds': 10, 'finished': False, 'notified': False})
        self.alarms.index = 1
        self.assertFalse(self.alarms.receive('EVENT timer_action=dismiss'))
        self.assertEqual(self.alarms.delivering, 'a')

    def test_failed_synthesis_backs_off_without_ack(self):
        self.alarms.pump()
        self.worker.calls[0][2].set_exception(RuntimeError('unavailable'))
        self.assertIsNone(self.alarms.take())
        self.alarms.pump()
        self.assertEqual(len(self.worker.calls), 1)
        self.assertIsNone(self.alarms.delivering)

    def test_failed_state_is_not_reported_as_zero_timers(self):
        future = Future(); future.set_exception(RuntimeError('offline'))
        self.alarms.poll = future
        self.alarms.pump()
        self.assertEqual(self.lines[-1], b'TIMER_UNAVAILABLE\n')

    def test_touch_creation_waits_for_api_then_selects_new_timer(self):
        self.alarms.timers = []
        stale = Future(); stale.set_result({'timers': []}); self.alarms.poll = stale
        self.alarms.receive('EVENT timer_start=900')
        self.alarms.receive('EVENT timer_start=900')
        self.assertEqual(len(self.worker.calls), 1)
        self.assertEqual(self.worker.calls[0][1], ('POST', '/v1/timers', {'seconds':900, 'label':'15 minute timer'}))
        self.assertNotIn(b'TIMER_RESULT Timer started\n', self.lines)
        self.worker.calls[0][2].set_result({'id':'new'})
        self.alarms.pump()
        self.assertIn(b'TIMER_RESULT Timer started\n', self.lines)
        self.assertEqual(self.alarms.select_id, 'new')
        self.worker.calls[-1][2].set_result({'timers':[
            {'id':'older','remaining_seconds':300,'finished':False,'notified':False},
            {'id':'new','label':'15 minute timer','remaining_seconds':900,'finished':False,'notified':False}]})
        self.alarms.pump()
        self.assertEqual(self.alarms.index, 1)
        self.assertIn(b'TIMER_LABEL 15 minute timer\n', self.lines)

    def test_invalid_unavailable_or_full_timer_requests_do_not_mutate(self):
        self.alarms.timers = []
        for seconds in ('0', '59', '61', '7201', '9999', '-60', 'true'):
            self.alarms.receive('EVENT timer_start='+seconds)
        self.assertEqual(self.worker.calls, [])
        self.alarms.available = False; self.alarms.receive('EVENT timer_start=300')
        self.assertEqual(self.worker.calls, [])
        self.assertIn(b'TIMER_RESULT Timer service unavailable\n', self.lines)
        self.alarms.available = True; self.alarms.timers = [{}]*16
        self.alarms.receive('EVENT timer_start=300')
        self.assertEqual(self.worker.calls, [])
        self.assertIn(b'TIMER_RESULT Dismiss a timer first\n', self.lines)

    def test_failed_create_never_claims_success(self):
        self.alarms.timers = []; self.alarms.receive('EVENT timer_start=60')
        self.worker.calls[0][2].set_exception(RuntimeError('storage unavailable'))
        self.alarms.pump()
        self.assertIn(b'TIMER_RESULT Timer request failed\n', self.lines)
        self.assertNotIn(b'TIMER_RESULT Timer started\n', self.lines)
        self.assertIsNone(self.alarms.select_id)

    def test_touch_request_reaches_real_api_and_persisted_timer_state(self):
        from fastapi.testclient import TestClient
        from backend.app import create_app
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory, TestClient(create_app('t'*40, runtime_root=Path(directory)), base_url='http://127.0.0.1') as client:
            client.headers['Authorization'] = 'Bearer '+'t'*40
            self.alarms.client = client; self.alarms.timers = []
            self.alarms.receive('EVENT timer_start=300')
            function, args, future = self.worker.calls[0]
            future.set_result(function(*args)); self.alarms.pump()
            state = client.get('/v1/state').json()['timers']
            self.assertEqual(len(state), 1)
            self.assertEqual(state[0]['label'], '5 minute timer')
            self.assertGreater(state[0]['remaining_seconds'], 295)
            self.assertTrue((Path(directory)/'local/timers.json').is_file())


if __name__ == '__main__': unittest.main()
