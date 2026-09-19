import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from backend.agent import EchoAgent, Provider
from backend.app import create_app
from backend.settings import EchoSettings, SettingsStore, SettingsUpdate, SettingsUnavailable, WindowsProtector
from backend.whisper import WhisperCommand
from backend.speech_restart import SpeechRestart


class FakeProtector:
    def encrypt(self, data): return b'test-only:'+base64.b64encode(data)
    def decrypt(self, data): return base64.b64decode(data.removeprefix(b'test-only:'))


class SettingsTests(unittest.TestCase):
    def test_saved_credentials_are_write_only_and_survive_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); store = SettingsStore(root, FakeProtector())
            result = store.save(SettingsUpdate(settings=EchoSettings(provider='openai', model='test-model'), api_key='private-test-key'))
            self.assertNotIn('private-test-key', json.dumps(result))
            self.assertNotIn('private-test-key', (root/'local/echo-settings.json').read_text())
            restored = SettingsStore(root, FakeProtector())
            self.assertEqual(restored.snapshot()[1]['openai'], 'private-test-key')
            restored.save(SettingsUpdate(settings=EchoSettings(provider='anthropic'), api_key='second-key'))
            self.assertTrue(restored.public()['credentials']['openai'])
            restored.save(SettingsUpdate(settings=EchoSettings(provider='openai'), clear_key=True))
            self.assertNotIn('openai', restored.snapshot()[1])
            self.assertTrue(restored.public()['credentials']['anthropic'])

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_real_windows_credential_roundtrip(self):
        protector = WindowsProtector()
        encrypted = protector.encrypt(b'synthetic-test-key')
        self.assertNotIn(b'synthetic-test-key', encrypted)
        self.assertEqual(protector.decrypt(encrypted), b'synthetic-test-key')

    def test_failed_write_preserves_active_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(Path(folder), FakeProtector())
            with patch.object(Path, 'replace', side_effect=PermissionError):
                with self.assertRaises(SettingsUnavailable):
                    store.save(SettingsUpdate(settings=EchoSettings(model='different')))
            self.assertEqual(store.settings.model, '')

    def test_corrupt_settings_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'local/echo-settings.json'; path.parent.mkdir(); path.write_text('bad')
            with self.assertRaises(SettingsUnavailable): SettingsStore(Path(folder))
            self.assertEqual(path.read_text(), 'bad')

    def test_remote_endpoints_and_credentials_in_urls_rejected(self):
        for endpoint in ['https://example.com:443/v1','http://8.8.8.8:11434/v1', 'http://user:pass@localhost:11434/v1',
                         'http://localhost:11434/v1?key=secret', 'http://0.0.0.0:11434/v1', 'http://localhost/v1']:
            with self.assertRaises(ValueError): EchoSettings(local_url=endpoint)
        self.assertEqual(EchoSettings(local_url='http://192.0.2.38:11434/v1/').local_url, 'http://192.0.2.38:11434/v1')

    def test_azure_endpoint_requires_known_https_resource_and_persists_write_only_key(self):
        for endpoint in ('http://example.openai.azure.com','https://example.com','https://user:secret@example.openai.azure.com',
                         'https://example.openai.azure.com.evil.test','https://example.openai.azure.com/?key=secret',
                         'https://example.openai.azure.com/private','https://example.openai.azure.com:444'):
            with self.assertRaises(ValueError): EchoSettings(azure_url=endpoint)
        with self.assertRaises(ValueError): EchoSettings(provider='azure')
        settings=EchoSettings(provider='azure',model='deployed',azure_url='https://example.openai.azure.com/')
        self.assertEqual(settings.azure_url,'https://example.openai.azure.com/openai/v1')
        with tempfile.TemporaryDirectory() as folder:
            store=SettingsStore(Path(folder),FakeProtector())
            result=store.save(SettingsUpdate(settings=settings,api_key='private-azure-test-key'))
            self.assertTrue(result['credentials']['azure'])
            self.assertNotIn('private-azure-test-key',json.dumps(result))
            self.assertEqual(SettingsStore(Path(folder),FakeProtector()).snapshot()[1]['azure'],'private-azure-test-key')


class ProviderTests(unittest.TestCase):
    def make(self, provider='openai', response=None, code=200):
        self.calls = []
        def request(req):
            self.calls.append(req)
            return httpx.Response(code, json=response or {'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Hello, human.'}]}]})
        store = SettingsStore(protector=FakeProtector())
        store.save(SettingsUpdate(settings=EchoSettings(provider=provider, model='test-model'), api_key='synthetic-key'))
        agent = EchoAgent(store, Provider(httpx.MockTransport(request)))
        return store, agent

    def test_openai_responses_personality_and_no_server_storage(self):
        _, agent = self.make()
        result = agent.respond('Hello', 'a')
        self.assertEqual(result['text'], 'Hello, human.')
        req = self.calls[0]; body = json.loads(req.content)
        self.assertEqual(str(req.url), 'https://api.openai.com/v1/responses')
        self.assertFalse(body['store'])
        self.assertIn('relaxed Jarvis', body['instructions'])
        self.assertNotIn('tools', body)
        self.assertEqual(req.headers['Authorization'], 'Bearer synthetic-key')

    def test_anthropic_system_and_text_blocks(self):
        _, agent = self.make('anthropic', {'content':[{'type':'text','text':'All set.'}]})
        self.assertEqual(agent.respond('Hi')['text'], 'All set.')
        req = self.calls[0]; body = json.loads(req.content)
        self.assertEqual(str(req.url), 'https://api.anthropic.com/v1/messages')
        self.assertIn('system', body); self.assertEqual(body['messages'][0]['role'], 'user')
        self.assertEqual(req.headers['anthropic-version'], '2023-06-01')

    def test_local_chat_endpoint(self):
        _, agent = self.make('local', {'choices':[{'message':{'content':'Local hello.'}}]})
        self.assertEqual(agent.respond('Hi')['text'], 'Local hello.')
        req = self.calls[0]
        self.assertEqual(str(req.url), 'http://127.0.0.1:11434/v1/chat/completions')
        self.assertEqual(json.loads(req.content)['messages'][0]['role'], 'system')

    def test_azure_uses_resource_deployments_api_key_and_stateless_responses(self):
        calls=[]
        def request(req):
            calls.append(req)
            if req.url.path.endswith('/deployments'):
                return httpx.Response(200,json={'data':[{'id':'echo-brain','model':'gpt-5.6-terra','status':'succeeded'},
                    {'id':'art','model':'gpt-image-2','status':'succeeded'},
                    {'id':'pending','model':'gpt-5.5','status':'creating'}]})
            return httpx.Response(200,json={'output':[{'type':'message','role':'assistant',
                'content':[{'type':'output_text','text':'Azure hello.'}]}]})
        settings=EchoSettings(provider='azure',model='echo-brain',azure_url='https://example.openai.azure.com')
        provider=Provider(httpx.MockTransport(request)); keys={'azure':'synthetic-azure-key'}
        self.assertEqual(provider.models(settings,keys),['echo-brain'])
        self.assertEqual(str(calls[0].url),'https://example.openai.azure.com/openai/deployments?api-version=2023-03-15-preview')
        self.assertEqual(provider.complete(settings,keys,[{'role':'user','content':'Hello'}]),'Azure hello.')
        req=calls[1]; body=json.loads(req.content)
        self.assertEqual(str(req.url),'https://example.openai.azure.com/openai/v1/responses')
        self.assertEqual(req.headers['api-key'],'synthetic-azure-key')
        self.assertNotIn('authorization',req.headers)
        self.assertFalse(body['store']); self.assertEqual(body['model'],'echo-brain')
        store=SettingsStore(protector=FakeProtector()); store.save(SettingsUpdate(settings=settings,api_key=keys['azure']))
        self.assertTrue(EchoAgent(store,provider).status()['cloud'])
        self.assertEqual(EchoAgent(store,provider).status()['status'],'configured')

    def test_disabled_never_connects_and_errors_do_not_echo_provider_body(self):
        store, agent = self.make(code=401, response={'error':'synthetic-key leaked by remote error'})
        self.assertNotIn('synthetic-key', agent.respond('Hi')['text'])
        self.assertEqual(len(self.calls), 1)
        store.save(SettingsUpdate(settings=EchoSettings()))
        self.assertEqual(agent.respond('Hi')['status'], 'unavailable')
        self.assertEqual(len(self.calls), 1)

    def test_memory_is_bounded_isolated_clearable_and_resets_on_settings_change(self):
        store, agent = self.make()
        for i in range(10): agent.respond('Hello '+str(i), 'a')
        self.assertLessEqual(len(agent.history['a'][1]), 12)
        agent.respond('Isolated', 'b')
        self.assertEqual(len(json.loads(self.calls[-1].content)['input']), 1)
        agent.clear('a'); self.assertNotIn('a', agent.history)
        store.save(SettingsUpdate(settings=EchoSettings(provider='openai', model='changed-model')))
        agent.respond('New provider context', 'b')
        self.assertEqual(len(json.loads(self.calls[-1].content)['input']), 1)

    def test_model_list_and_response_bounds(self):
        store, agent = self.make(response={'data':[{'id':'b'},{'id':'a'},{'id':'a'},{}]})
        self.assertEqual(agent.provider.models(*store.snapshot()[:2]), ['a','b'])
        _, agent = self.make(response={'choices':[]})
        self.assertEqual(agent.respond('Hi')['status'], 'unavailable')


class WebTests(unittest.TestCase):
    def setUp(self):
        self.store = SettingsStore(protector=FakeProtector())
        self.calls = []
        def request(req):
            self.calls.append(req)
            return httpx.Response(200, json={'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Just chilling.'}]}]})
        self.client = TestClient(create_app('t'*32, settings_store=self.store, provider=Provider(httpx.MockTransport(request))))
        self.auth = {'Authorization':'Bearer '+'t'*32}
        self.browser = {'X-Echo-Request':'1', 'Origin':'http://testserver'}

    def login(self):
        ticket = self.client.post('/v1/ui/ticket', headers=self.auth).json()['ticket']
        response = self.client.post('/v1/ui/session', json={'ticket':ticket}, headers=self.browser)
        self.assertEqual(response.status_code, 200)
        self.assertIn('httponly', response.headers['set-cookie'].lower())
        return ticket

    def test_ticket_bearer_gate_replay_logout_and_cookie_csrf(self):
        self.assertEqual(self.client.post('/v1/ui/ticket').status_code,401)
        ticket = self.login()
        self.assertEqual(self.client.post('/v1/ui/session',json={'ticket':ticket},headers=self.browser).status_code,401)
        self.assertEqual(self.client.get('/v1/settings').status_code,200)
        self.assertEqual(self.client.post('/v1/chat',json={'text':'Hello'}).status_code,403)
        self.assertEqual(self.client.post('/v1/chat',json={'text':'Hello'},headers={**self.browser,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.delete('/v1/ui/session',headers=self.browser).status_code,200)
        self.assertEqual(self.client.get('/v1/settings').status_code,401)

    def test_secrets_are_redacted_even_on_validation_error(self):
        self.login()
        bad = self.client.put('/v1/settings',headers=self.browser,json={'settings':{'provider':'invented'},'api_key':'never-reflect-me'})
        self.assertEqual(bad.status_code,422); self.assertNotIn('never-reflect-me',bad.text)
        good = self.client.put('/v1/settings',headers=self.browser,json={'settings':{'provider':'openai','model':'test-model'},'api_key':'never-reflect-me'})
        self.assertEqual(good.status_code,200); self.assertNotIn('never-reflect-me',good.text)
        self.assertNotIn('never-reflect-me',self.client.get('/v1/settings').text)

    def test_browser_and_device_timer_commands_use_local_service_without_provider(self):
        self.login()
        self.store.save(SettingsUpdate(settings=EchoSettings(provider='openai',model='test-model'),api_key='fake-key'))
        response = self.client.post('/v1/chat',headers=self.browser,json={'text':'set a timer for five minutes'})
        self.assertEqual(response.json()['capability'],'timer')
        self.assertEqual(len(self.client.get('/v1/chat').json()['messages']),2)
        self.assertEqual(self.client.get('/v1/chat',headers=self.auth).json()['messages'],[])
        self.assertEqual(len(self.client.get('/v1/state').json()['timers']),1)
        response = self.client.post('/v1/text',headers=self.auth,json={'text':'set a timer for five minutes'})
        self.assertEqual(response.json()['capability'],'timer'); self.assertEqual(len(self.calls),0)
        response = self.client.post('/v1/text',headers=self.auth,json={'text':'tell me a joke'})
        self.assertEqual(response.json()['capability'],'conversation'); self.assertEqual(len(self.calls),1)

    def test_real_ui_assets_and_host_boundary(self):
        for path in ['/','/settings','/assets/app.js','/assets/style.css']:
            response = self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertIn("frame-ancestors 'none'",response.headers['content-security-policy'])
        self.assertEqual(self.client.get('/v1/settings',headers={**self.auth,'Host':'evil.example'}).status_code,400)


class WhisperBoundaryTests(unittest.TestCase):
    def test_pcm_limit_and_native_confidence_not_vosk_confidence(self):
        class Endpoint:
            def Reset(self): pass
            def AcceptWaveform(self, pcm): return True
        class Client:
            def transcribe(self, pcm): return 'quality-gated native transcription'
            def close(self): pass
        command = WhisperCommand(Endpoint(),Client())
        command.AcceptWaveform(b'\0\0'*100)
        self.assertEqual(command.decode(),'quality-gated native transcription')
        self.assertEqual(command.pcm,bytearray())
        command.AcceptWaveform(b'\0'*(16000*2*8+2))
        self.assertIsNone(command.decode())

    def test_decode_overflow_and_cancel_do_not_deliver_stale_command(self):
        import threading
        import time
        from backend.recognition import Recognition
        class Detector:
            def reset(self): pass
        class Command:
            def __init__(self): self.entered = threading.Event(); self.release = threading.Event()
            def Reset(self): pass
            def AcceptWaveform(self, pcm): return True
            def decode(self):
                self.entered.set(); self.release.wait(2); return 'turn off the thermostat'
        command = Command(); worker = Recognition(detector=Detector(), command=command)
        try:
            worker.set_mode('listening'); worker.submit(b'utterance')
            self.assertTrue(command.entered.wait(1))
            for _ in range(100): worker.submit(b'new microphone frames')
            self.assertEqual(worker.health()['dropped'],0)
            self.assertEqual(worker.health()['queue'],0)
            worker.set_mode(None); command.release.set()
            deadline = time.monotonic()+1
            while worker.decoding.is_set() and time.monotonic()<deadline: time.sleep(.001)
            self.assertEqual(worker.poll(),[])
        finally: command.release.set(); worker.close()


class SpeechRestartTests(unittest.TestCase):
    def test_busy_device_rejects_restart(self):
        with patch('backend.speech_restart.voice_status',return_value={'status':'music'}):
            with self.assertRaises(ValueError): SpeechRestart(Path('unused')).start()

    def test_restart_uses_fixed_launcher_without_play_music_or_volume(self):
        with tempfile.TemporaryDirectory() as folder, patch('backend.speech_restart.request_stop') as stop, \
                patch('backend.speech_restart.subprocess.run') as run, \
                patch('backend.speech_restart.voice_status',return_value={'status':'armed','engine':'whisper-base.en-local'}):
            run.return_value.returncode=0
            restart=SpeechRestart(Path(folder)); restart.lock.acquire(); restart._run()
            self.assertEqual(restart.state,'ready')
            stop.assert_called_once_with(Path(folder),'voice')
            args=run.call_args.args[0]
            self.assertEqual(args[-1],'start')
            self.assertNotIn('-PlayMusic',args)

    def test_restart_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as folder, patch('backend.speech_restart.request_stop',side_effect=OSError):
            restart=SpeechRestart(Path(folder)); restart.lock.acquire(); restart._run()
            self.assertEqual(restart.state,'failed')


if __name__ == '__main__': unittest.main()
