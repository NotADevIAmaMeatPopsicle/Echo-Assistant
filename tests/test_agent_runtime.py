import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
import httpx
from backend.agent import EchoAgent
from backend.agent_runtime import HermesRuntime, RuntimeUnavailable, configuration_fingerprint
from backend.settings import EchoSettings, SettingsStore, SettingsUpdate, default_protector


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = EchoSettings(provider='azure', agent_runtime='hermes', model='test-deployment',
                                     azure_url='https://example.openai.azure.com/openai/v1')
        self.keys = {'azure': 'synthetic-key'}
        self.protector = default_protector()
        value = {'url': 'http://127.0.0.1:18643', 'token': 'synthetic-' * 5,
                 'configuration': configuration_fingerprint(self.settings, self.keys)}
        path = self.root / 'local/remote-agent.json'
        path.parent.mkdir()
        path.write_text(json.dumps({'protected': base64.b64encode(
            self.protector.encrypt(json.dumps(value).encode())).decode()}))
        self.calls = []

    def runtime(self, handler, **kwargs):
        def wrapped(request):
            self.calls.append(request)
            return handler(request)
        return HermesRuntime(self.root, self.protector, transport=httpx.MockTransport(wrapped), **kwargs)

    def complete(self, runtime, **kwargs):
        return runtime.complete(self.settings, self.keys,
            [{'role':'user','content':'First question'}, {'role':'assistant','content':'First answer'},
             {'role':'user','content':'Follow up'}], instructions='Be Echo.', **kwargs)

    def test_native_run_preserves_context_and_requires_terminal_success(self):
        def handler(request):
            if request.method == 'POST':
                body = json.loads(request.content)
                self.assertEqual(body['input'], 'Follow up')
                self.assertEqual(len(body['conversation_history']), 2)
                self.assertTrue(request.headers['Idempotency-Key'])
                self.assertNotIn('synthetic-key', request.content.decode())
                return httpx.Response(202, json={'run_id':'run_123'})
            return httpx.Response(200, json={'status':'completed','completed':True,'output':'Answer'})
        runtime = self.runtime(handler)
        self.assertEqual(self.complete(runtime), 'Answer')
        self.assertEqual(runtime.activity()['state'], 'completed')

    def test_partial_result_never_becomes_success(self):
        def handler(request):
            if request.url.path.endswith('/stop'): return httpx.Response(202, json={})
            return httpx.Response(200, json=({'run_id':'run_123'} if request.method == 'POST'
                else {'status':'completed','partial':True,'output':'Pretend done'}))
        with self.assertRaisesRegex(RuntimeUnavailable, 'part'):
            self.complete(self.runtime(handler))
        self.assertTrue(self.calls[-1].url.path.endswith('/stop'))

    def test_public_progress_tracks_streamed_tools_without_exposing_payloads(self):
        polls = 0; stages = []
        def handler(request):
            nonlocal polls
            if request.method == 'POST': return httpx.Response(202,json={'run_id':'run_123'})
            if request.url.path.endswith('/events'):
                events = [{'event':'tool.started','tool':'echo_home_devices','arguments':'private'},
                          {'event':'tool.completed','output':'private'},
                          {'event':'tool.started','tool':'echo_home_action','reasoning':'private'}]
                return httpx.Response(200,content=''.join('data: '+json.dumps(e)+'\n\n' for e in events))
            polls += 1
            return httpx.Response(200,json={'status':'running'} if polls == 1 else {'status':'completed','output':'Done'})
        self.assertEqual(self.complete(self.runtime(handler),progress=stages.append),'Done')
        self.assertIn('checking',stages); self.assertIn('acting',stages)
        self.assertEqual(stages[-1],'completed')
        self.assertNotIn('private',str(stages))

    def test_transient_status_timeout_recovers_same_run_without_readmission(self):
        polls=0
        def handler(request):
            nonlocal polls
            if request.method=='POST':return httpx.Response(202,json={'run_id':'run_123'})
            if request.url.path=='/v1/runs/run_123':
                polls+=1
                if polls==1:raise httpx.ReadTimeout('Synthetic observation timeout',request=request)
            return httpx.Response(200,json={'status':'completed','completed':True,'output':'Verified answer'})
        runtime=self.runtime(handler)
        self.assertEqual(self.complete(runtime),'Verified answer')
        self.assertEqual(polls,2)
        self.assertEqual(len([r for r in self.calls if r.method=='POST']),1)
        self.assertEqual(runtime.activity()['state'],'completed')

    def test_unreachable_status_retains_original_deadline_and_stops_run(self):
        def handler(request):
            if request.method=='POST':return httpx.Response(202,json={'run_id':'run_123'})
            raise httpx.ConnectError('Synthetic unavailable status',request=request)
        runtime=self.runtime(handler,timeout=.05)
        with self.assertRaisesRegex(RuntimeUnavailable,'too long'):self.complete(runtime)
        self.assertEqual(len([r for r in self.calls if r.url.path=='/v1/runs']),1)
        self.assertTrue(self.calls[-1].url.path.endswith('/stop'))

    def test_cancellation_during_missing_status_stops_existing_run(self):
        cancel=Event()
        def handler(request):
            if request.method=='POST':return httpx.Response(202,json={'run_id':'run_123'})
            if request.url.path=='/v1/runs/run_123':cancel.set()
            raise httpx.ReadTimeout('Synthetic observation timeout',request=request)
        with self.assertRaisesRegex(RuntimeUnavailable,'cancelled'):
            self.complete(self.runtime(handler),cancel=cancel)
        self.assertEqual(len([r for r in self.calls if r.url.path=='/v1/runs']),1)
        self.assertTrue(self.calls[-1].url.path.endswith('/stop'))

    def test_cancellation_after_admission_stops_the_admitted_run(self):
        cancel = Event()
        def handler(request):
            if request.url.path == '/v1/runs':
                cancel.set()
                return httpx.Response(202, json={'run_id':'run_123'})
            return httpx.Response(202, json={})
        runtime = self.runtime(handler)
        with self.assertRaisesRegex(RuntimeUnavailable, 'cancelled'):
            self.complete(runtime, cancel=cancel)
        self.assertTrue(self.calls[-1].url.path.endswith('/stop'))
        self.assertEqual(runtime.activity()['state'], 'cancelled')

    def test_rejected_stop_is_unconfirmed(self):
        cancel = Event()
        def handler(request):
            if request.url.path == '/v1/runs':
                cancel.set()
                return httpx.Response(202, json={'run_id':'run_123'})
            return httpx.Response(503, json={})
        runtime = self.runtime(handler)
        stages = []
        with self.assertRaises(RuntimeUnavailable): self.complete(runtime, cancel=cancel, progress=stages.append)
        self.assertEqual(runtime.activity()['state'], 'unconfirmed')
        self.assertEqual(stages[-1], 'unconfirmed')

    def test_changed_credentials_fail_before_network(self):
        runtime = self.runtime(lambda _: self.fail('Unexpected request'))
        self.keys['azure'] = 'replacement'
        with self.assertRaisesRegex(RuntimeUnavailable, 'Apply'): self.complete(runtime)

    def test_invalid_run_identifier_cannot_change_request_target(self):
        runtime = self.runtime(lambda _: httpx.Response(202, json={'run_id':'run_../settings'}))
        with self.assertRaisesRegex(RuntimeUnavailable, 'reference'): self.complete(runtime)
        # No GET or stop request may be made with an unvalidated ID.
        self.assertEqual(len(self.calls), 1)

    def test_runtime_timeout_requests_stop(self):
        def handler(request):
            if request.url.path.endswith('/stop'): return httpx.Response(202, json={})
            return httpx.Response(200, json={'run_id':'run_123'} if request.method == 'POST' else {'status':'running'})
        with self.assertRaisesRegex(RuntimeUnavailable, 'too long'):
            self.complete(self.runtime(handler, timeout=.05))
        self.assertTrue(self.calls[-1].url.path.endswith('/stop'))

    def test_echo_uses_runtime_but_preserves_explicit_lookup_and_memory(self):
        store = SettingsStore(self.root)
        store.save(SettingsUpdate(settings=self.settings, api_key='synthetic-key'))
        agent = EchoAgent(store)
        calls = []
        class Runtime:
            def complete(self, *args, **kwargs):
                calls.append(kwargs); return 'Hermes answer'
        class Direct:
            def complete(self, *args, **kwargs): return 'Sourced lookup route'
        agent.runtime = Runtime(); agent.provider = Direct()
        self.assertEqual(agent.respond('Hello')['text'], 'Hermes answer')
        self.assertEqual(agent.respond('Look up the Moon')['text'], 'Sourced lookup route')
        self.assertEqual(agent.respond('Remember that I prefer tea')['capability'], 'memory')
        self.assertEqual(len(calls), 1)
