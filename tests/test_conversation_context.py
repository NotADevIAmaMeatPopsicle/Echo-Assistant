"""Quick local turns and AI replies share bounded, clearable, volatile context."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.agent import EchoAgent
from backend.app import create_app
from backend.core import Assistant, TimerStorageUnavailable
from backend.settings import EchoSettings, SettingsStore, SettingsUpdate


class RecordingProvider:
    def __init__(self, blocking=False):
        self.calls = []; self.entered = Event(); self.release = Event()
        if not blocking: self.release.set()

    def complete(self, settings, keys, messages, **kwargs):
        self.calls.append(deepcopy(messages)); self.entered.set()
        if not self.release.wait(5): raise AssertionError('Test did not release the provider')
        return 'Synthetic answer.'


def configured():
    store = SettingsStore()
    store.save(SettingsUpdate(settings=EchoSettings(provider='local', model='synthetic')))
    return store


class ContextTests(unittest.TestCase):
    def test_built_in_results_reach_model_and_copies_cannot_mutate_context(self):
        provider = RecordingProvider(); agent = EchoAgent(configured(), provider)
        token, _ = agent.context('device')
        result = {'status':'complete','capability':'timer','timer_id':'a'*32,'timer_action':'started','text':'Timer set.'}
        agent.record_local('Set a timer.', result, 'device', token)
        copy = agent.messages('device'); copy[-1]['local_result']['timer_id'] = 'b'*32
        self.assertEqual(agent.messages('device')[-1]['local_result']['timer_id'], 'a'*32)
        self.assertEqual(agent.respond('What did we just do?')['status'], 'complete')
        self.assertEqual(provider.calls[-1][1], {'role':'assistant','content':'Timer set.'})
        self.assertEqual(agent.messages('browser'), [])

    def test_fast_turn_and_read_do_not_wait_for_model_or_get_overwritten(self):
        provider = RecordingProvider(blocking=True); agent = EchoAgent(configured(), provider)
        with ThreadPoolExecutor(max_workers=2) as pool:
            model = pool.submit(agent.respond, 'Slow question')
            try:
                self.assertTrue(provider.entered.wait(1))
                def quick():
                    token, _ = agent.context('device')
                    agent.record_local('Time?', {'status':'complete','capability':'clock','text':'It is noon.'}, 'device', token)
                    return agent.messages('device')
                self.assertEqual(len(pool.submit(quick).result(timeout=1)), 2)
            finally: provider.release.set()
            self.assertEqual(model.result(timeout=2)['status'], 'complete')
        self.assertEqual([x['content'] for x in agent.messages('device')],
                         ['Time?', 'It is noon.', 'Slow question', 'Synthetic answer.'])

    def test_clear_during_reply_is_immediate_and_old_reply_cannot_restore_history(self):
        provider = RecordingProvider(blocking=True); agent = EchoAgent(configured(), provider)
        with ThreadPoolExecutor(max_workers=2) as pool:
            model = pool.submit(agent.respond, 'Old question')
            try:
                self.assertTrue(provider.entered.wait(1))
                pool.submit(agent.clear, 'device').result(timeout=1)
                token, _ = agent.context('device')
                agent.record_local('New time?', {'status':'complete','capability':'clock','text':'Noon.'}, 'device', token)
            finally: provider.release.set()
            self.assertEqual(model.result(timeout=2)['status'], 'unavailable')
        self.assertEqual([x['content'] for x in agent.messages('device')], ['New time?', 'Noon.'])

    def test_expiry_settings_and_memory_invalidate_pending_local_results(self):
        store = configured(); agent = EchoAgent(store, RecordingProvider())
        response = {'status':'complete','capability':'clock','text':'Noon.'}
        for change in ('expiry','settings','memory'):
            with self.subTest(change=change):
                token, _ = agent.context('device')
                agent.record_local('Old question', response, 'device', token)
                if change == 'expiry':
                    stamp, messages = agent.history['device']; agent.history['device'] = (stamp-1801,messages)
                elif change == 'settings':
                    store.save(SettingsUpdate(settings=EchoSettings(provider='local',model='changed')))
                else: agent.memory.save('My favorite color is blue.')
                self.assertEqual(agent.messages('device'), [])
                self.assertFalse(agent.record_local('Late result', response, 'device', token))

    def test_all_context_including_tokens_is_bounded(self):
        agent = EchoAgent(configured(), RecordingProvider())
        response = {'status':'complete','capability':'clock','text':'Noon.'}
        for number in range(20):
            token, _ = agent.context(str(number))
            for _ in range(8): agent.record_local('Time?', response, str(number), token)
        self.assertEqual(len(agent.history), 16); self.assertEqual(len(agent.context_tokens), 16)
        self.assertEqual(len(agent.messages('19')), 12)
        agent.clear(); self.assertFalse(agent.history); self.assertFalse(agent.context_tokens)


class TimerContextTests(unittest.TestCase):
    def test_countdown_finished_and_dismissed_target_never_uses_another_timer(self):
        now = [0]; assistant = Assistant(clock=lambda: now[0])
        result = assistant.respond('set a timer for two minutes')
        other = assistant.start_timer(500)
        now[0] = 30.5
        self.assertEqual(assistant.respond('how long is left', timer_context=result)['text'],
                         'That timer has 1 minute and 30 seconds left.')
        now[0] = 121
        self.assertEqual(assistant.respond('how long is left', timer_context=result)['text'], 'That timer has finished.')
        self.assertEqual(assistant.respond('cancel it', timer_context=result)['timer_action'], 'dismissed')
        self.assertEqual(assistant.respond('cancel it', timer_context=result)['timer_action'], 'missing')
        self.assertEqual([t['id'] for t in assistant.timer_states()], [other])

    def test_ambiguous_or_contextless_pronouns_do_not_dismiss_timers(self):
        assistant = Assistant(); assistant.start_timer(300); assistant.start_timer(600)
        self.assertEqual(assistant.respond('cancel my timer')['text'], 'Choose a timer on the display.')
        self.assertEqual(assistant.respond('cancel that timer')['status'], 'unavailable')
        self.assertEqual(assistant.respond('cancel it')['capability'], 'conversation')
        self.assertEqual(assistant.respond('check my timer')['text'], 'Choose a timer on the display.')
        self.assertEqual(len(assistant.timer_states()), 2)

    def test_failed_dismissal_does_not_claim_success(self):
        assistant = Assistant(); result = assistant.respond('timer for five minutes')
        with patch.object(assistant, '_save', side_effect=OSError):
            with self.assertRaises(TimerStorageUnavailable): assistant.respond('cancel it', timer_context=result)
        self.assertEqual(len(assistant.timer_states()), 1)


class ContextApiTests(unittest.TestCase):
    def setUp(self):
        self.provider = RecordingProvider(); self.store = configured()
        self.client = TestClient(create_app('t'*32, settings_store=self.store, provider=self.provider))
        self.addCleanup(self.client.close)
        self.auth = {'Authorization':'Bearer '+'t'*32}

    def text(self, message):
        response = self.client.post('/v1/text', headers=self.auth, json={'text':message})
        self.assertEqual(response.status_code, 200); return response.json()

    def test_device_followups_context_and_browser_isolation(self):
        first = self.text('set a timer for ten minutes')
        second = self.text('set a timer for twenty minutes')
        self.assertEqual(self.text('how long is left')['timer_id'], second['timer_id'])
        self.assertEqual(self.text('cancel it')['timer_id'], second['timer_id'])
        self.assertEqual(self.text('cancel it')['timer_action'], 'missing')
        self.text('What did we just cancel?')
        self.assertTrue(any(m['content']=='Your timer is dismissed.' for m in self.provider.calls[-1]))
        self.assertEqual([t['id'] for t in self.client.get('/v1/state',headers=self.auth).json()['timers']], [first['timer_id']])
        browser = {'X-Echo-Request':'1'}
        ticket = self.client.post('/v1/ui/ticket', headers=self.auth).json()['ticket']
        self.client.post('/v1/ui/session', json={'ticket':ticket}, headers=browser)
        self.assertEqual(self.client.get('/v1/chat').json()['messages'], [])
        result = self.client.post('/v1/text', headers=browser, json={'text':'cancel that timer'}).json()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(len(self.client.get('/v1/state').json()['timers']), 1)

    def test_local_http_command_and_history_work_while_model_is_busy(self):
        self.provider.release.clear()
        with ThreadPoolExecutor(max_workers=2) as pool:
            model = pool.submit(self.text, 'A slow synthetic question')
            try:
                self.assertTrue(self.provider.entered.wait(1))
                result = pool.submit(self.text, 'set a timer for ten minutes').result(timeout=1)
                self.assertEqual(result['capability'], 'timer')
                history = pool.submit(self.client.get, '/v1/chat', headers=self.auth).result(timeout=1).json()
                self.assertEqual(len(history['messages']), 2)
            finally: self.provider.release.set()
            self.assertEqual(model.result(timeout=2)['status'], 'complete')
        self.assertEqual(len(self.client.get('/v1/chat',headers=self.auth).json()['messages']), 4)

    def test_clear_removes_pronoun_target_but_preserves_actual_timer(self):
        self.text('set a timer for ten minutes')
        self.client.delete('/v1/chat',headers=self.auth)
        self.assertEqual(self.text('cancel that timer')['status'], 'unavailable')
        self.assertEqual(len(self.client.get('/v1/state',headers=self.auth).json()['timers']), 1)


if __name__ == '__main__': unittest.main()
