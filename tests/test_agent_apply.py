import base64
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.agent_apply import AgentApply
from backend.agent_runtime import HermesRuntime, RuntimeUnavailable, configuration_fingerprint
from backend.app import create_app
from backend.settings import EchoSettings, SettingsStore, SettingsUpdate


class AgentApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.environment=patch.dict(os.environ,{'ECHO_CONTAINER':'1'})
        self.environment.start();self.addCleanup(self.environment.stop)
        self.store=SettingsStore(self.root)
        self.settings=EchoSettings(provider='azure',agent_runtime='hermes',model='original',
                                   azure_url='https://example.openai.azure.com')
        self.save('original')
        self.runtime=HermesRuntime(self.root,self.store.protector)
        connection={'url':'http://agent:8642','token':'private-'*6,
                    'configuration':configuration_fingerprint(self.settings,{'azure':'synthetic-key'})}
        self.runtime.path.write_text(json.dumps({'protected':base64.b64encode(
            self.store.protector.encrypt(json.dumps(connection).encode())).decode()}))
        self.manager=AgentApply(self.root,self.store)

    def save(self, model, key='synthetic-key'):
        self.settings=self.settings.model_copy(update={'model':model})
        self.store.save(SettingsUpdate(settings=self.settings,api_key=key))

    def worker(self): return AgentApply(self.root,SettingsStore(self.root))

    def test_queue_export_and_ack_from_separate_process_preserve_private_connection(self):
        self.assertEqual(self.manager.status()['status'],'active')
        before=self.runtime.connection()
        self.save('replacement','new-synthetic-key')
        self.assertEqual(self.manager.status()['status'],'pending')
        job=self.manager.start()
        self.assertEqual(self.manager.start()['id'],job['id'])
        self.assertNotIn('synthetic',self.manager.path.read_text())
        settings,keys,_=self.store.snapshot()
        with self.assertRaisesRegex(RuntimeUnavailable,'being applied'):
            self.runtime.complete(settings,keys,[{'role':'user','content':'Hello'}],instructions='Echo')
        exported=self.worker().claim()
        self.assertEqual(exported['provider_key'],'new-synthetic-key')
        self.assertEqual(self.manager.status()['status'],'applying')
        resumed=self.worker().claim()
        self.assertTrue(resumed['resume'])
        self.assertNotIn('provider_key',resumed)
        self.assertIsNone(self.runtime.connection()['configuration'])
        self.assertTrue(self.worker().finish(job['id'],True)['applied'])
        self.assertEqual(self.manager.status()['status'],'active')
        self.assertEqual(self.runtime.connection()['token'],before['token'])
        self.assertFalse(self.worker().finish(job['id'],True)['applied'])

    def test_failure_newer_settings_and_expiry_cannot_ack_old_configuration(self):
        original=self.runtime.connection()
        self.save('first');job=self.manager.start();self.worker().claim()
        self.save('second')
        self.assertFalse(self.worker().finish(job['id'],True)['applied'])
        self.assertEqual(self.runtime.connection(),{**original,'configuration':None})
        job=self.manager.start();self.worker().claim()
        self.assertFalse(self.worker().finish(job['id'],False)['applied'])
        self.assertEqual(self.manager.status()['status'],'failed')
        job=self.manager.start();self.worker().claim()
        with patch('backend.agent_apply.time.time',return_value=time.time()+300):
            self.assertFalse(self.worker().finish(job['id'],True)['applied'])
            self.assertEqual(self.manager.status()['status'],'failed')
        self.assertEqual(self.runtime.connection(),{**original,'configuration':None})

    def test_cancel_before_claim_and_reject_cancel_after_start(self):
        self.save('replacement');self.manager.start();self.manager.cancel()
        self.assertFalse(self.worker().claim()['pending'])
        self.assertEqual(self.manager.status()['status'],'pending')
        self.manager.start();self.worker().claim()
        with self.assertRaisesRegex(ValueError,'already restarting'):self.manager.cancel()

    def test_old_request_is_not_applied_after_settings_change(self):
        self.save('first');self.manager.start();self.save('second')
        self.assertFalse(self.worker().claim()['pending'])
        self.assertEqual(self.manager.status()['status'],'pending')

    def test_browser_status_and_queue_never_return_provider_keys(self):
        self.save('replacement')
        api=TestClient(create_app('a'*40,runtime_root=self.root,settings_store=self.store),base_url='http://127.0.0.1')
        headers={'Authorization':'Bearer '+'a'*40}
        for path in ('/v1/settings/agent','/v1/settings/apply-agent'):
            response=api.get(path) if path.endswith('/agent') else api.post(path)
            self.assertEqual(response.status_code,401)
        result=api.post('/v1/settings/apply-agent',headers=headers)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['status'],'queued')
        self.assertNotIn('synthetic-key',result.text)
        self.assertNotIn('provider_key',api.get('/v1/settings/agent',headers=headers).text)
        self.assertEqual(api.delete('/v1/settings/apply-agent',headers=headers).json()['status'],'pending')


if __name__=='__main__':unittest.main()
