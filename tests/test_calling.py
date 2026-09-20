"""Synthetic calling credentials, authorization and lifecycle; never use audio or a provider."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.calling import CallSettings, CallSettingsUpdate, CallStore, Calling, jwt
from backend.linux_protection import LinuxProtector
from backend.display_auth import allowed


def update(**kwargs):
    return CallSettingsUpdate(revision=0, enabled=True, url='wss://calls.example.com',
                              api_key='example-key', api_secret='synthetic-secret-'*3, allowed_displays=['a'*32], **kwargs)


class CallingTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.;self.revision=0;self.mode='household';self.sent=[];self.fail=False
        self.displays=SimpleNamespace(profile_for=lambda p:{'profile':{'mode':self.mode},'profile_revision':self.revision})
        self.store=CallStore(None,None);self.store.save(update())
        def request(s,method,body):
            self.sent.append((method,body))
            if self.fail:raise HTTPException(502,'Unavailable')
        self.calls=Calling(self.store,self.displays,SimpleNamespace(request=request),lambda:self.now)
        self.principal='display:'+'a'*32;self.client='1'*32

    def start(self):return self.calls.start(self.principal,self.client)

    def test_short_token_limits_room_and_sources(self):
        call=self.start();parts=call['token'].split('.')
        payload=json.loads(base64.urlsafe_b64decode(parts[1]+'=='))
        expected=hmac.new(self.store.state.api_secret.get_secret_value().encode(),'.'.join(parts[:2]).encode(),hashlib.sha256).digest()
        self.assertEqual(base64.urlsafe_b64decode(parts[2]+'=='),expected)
        self.assertEqual(payload['exp'],1060);self.assertNotIn('roomCreate',payload['video'])
        self.assertEqual(payload['video']['room'],'echo-'+call['id'])
        self.assertEqual(payload['video']['canPublishSources'],['microphone','camera'])
        self.assertFalse(payload['video']['canPublishData'])
        self.assertNotIn(self.principal,call['token'])
        self.assertEqual(self.sent[0][1]['max_participants'],2)

    def test_invite_single_use_and_not_room_name(self):
        c=self.start();other=self.calls.join('owner','2'*32,c['code'])
        self.assertEqual(other['id'],c['id']);self.assertNotIn('code',other)
        with self.assertRaises(HTTPException):self.calls.join('owner','3'*32,c['code'])
        self.assertNotEqual(c['code'],c['id'])
        self.assertNotIn(c['code'],repr(self.calls.calls))

    def test_expired_or_stale_invite(self):
        c=self.start();self.now+=21
        with self.assertRaises(HTTPException):self.calls.join('owner','2'*32,c['code'])
        self.calls.tick();self.assertFalse(self.calls.calls)

    def test_heartbeat_and_timeout_cleanup(self):
        c=self.start();self.now+=15;self.calls.pulse(c['id'],self.principal,self.client)
        self.now+=15;self.calls.tick();self.assertTrue(self.calls.calls)
        self.now+=6;self.calls.tick();self.assertFalse(self.calls.calls)
        self.assertEqual(self.sent[-1][0],'DeleteRoom')

    def test_revoke_guest_and_changed_revision_end_calls(self):
        for change in ('grant','mode','revision'):
            with self.subTest(change=change):
                self.setUp();self.start()
                if change=='grant':self.store.state.allowed_displays=[]
                elif change=='mode':self.mode='guest'
                else:self.revision+=1
                self.calls.tick();self.assertFalse(self.calls.calls)

    def test_end_requires_call_membership(self):
        c=self.start()
        with self.assertRaises(HTTPException):self.calls.end(c['id'],'other','2'*32)
        self.calls.end(c['id'],self.principal,self.client);self.assertFalse(self.calls.calls)

    def test_same_paired_display_cannot_start_another_tab(self):
        self.start()
        with self.assertRaises(HTTPException):self.calls.start(self.principal,'2'*32)

    def test_timeout_create_and_failed_delete_are_retried(self):
        self.fail=True
        with self.assertRaises(HTTPException):self.start()
        self.calls.tick();self.assertTrue(self.calls.calls)
        self.fail=False;self.now+=11;self.calls.tick();self.assertFalse(self.calls.calls)

    def test_invitation_and_call_lifetimes(self):
        c=self.start();self.now+=121
        self.calls.pulse(c['id'],self.principal,self.client);self.calls.tick();self.assertFalse(self.calls.calls)
        c=self.start();self.calls.join('owner','2'*32,c['code']);self.now+=901
        with self.assertRaises(HTTPException):self.calls.pulse(c['id'],self.principal,self.client)
        self.calls.tick();self.assertFalse(self.calls.calls)

    def test_storage_redaction_encryption_and_retaining_keys(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);key=root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
            protector=LinuxProtector(key);store=CallStore(root,protector);store.save(update())
            self.assertNotIn(b'example-key',store.path.read_bytes())
            saved=CallStore(root,protector);self.assertEqual(saved.state.api_key.get_secret_value(),'example-key')
            self.assertNotIn('api_key',saved.snapshot());self.assertNotIn('api_secret',saved.snapshot())
            saved.save(CallSettingsUpdate(revision=1,enabled=False,url='wss://calls.example.com',allowed_displays=[]))
            self.assertTrue(saved.snapshot()['credentials_saved'])
            saved.save(CallSettingsUpdate(revision=2,enabled=False,url='',allowed_displays=[],clear_credentials=True))
            self.assertFalse(saved.snapshot()['credentials_saved'])
            store.path.write_text('broken')
            with self.assertRaises(HTTPException):CallStore(root,protector).snapshot()
            self.assertEqual(store.path.read_text(),'broken')

    def test_unsafe_origins_and_credential_reuse_rejected(self):
        for url in ['https://calls.example.com','wss://user:pass@calls.example.com','wss://calls.example.com/path','wss://calls.example.com?token=x','wss://calls.example.com\r\nanything']:
            with self.subTest(url=url),self.assertRaises(ValueError):CallSettings(revision=0,url=url)
        with self.assertRaises(HTTPException):self.store.save(CallSettingsUpdate(revision=1,enabled=True,url='wss://different.example.com',allowed_displays=[]))

    def test_not_enabled_in_validation_or_for_unapproved_displays(self):
        self.assertFalse(self.calls.status('display:'+'b'*32)['allowed'])
        with self.assertRaises(HTTPException):self.calls.start('display:'+'b'*32,self.client)
        self.calls.enabled=False
        with self.assertRaises(HTTPException):self.start()
        self.assertEqual(self.calls.origins(),[])

    def test_cloud_regional_connections_are_provider_scoped(self):
        self.assertNotIn('wss://*.livekit.cloud',self.calls.origins())
        self.store.state.url='wss://project.livekit.cloud'
        self.assertIn('wss://*.livekit.cloud',self.calls.origins())
        self.store.state.url='wss://project.livekit.cloud.example.com'
        self.assertNotIn('wss://*.livekit.cloud',self.calls.origins())


class CallingApiTests(unittest.TestCase):
    def setUp(self):
        self.app=create_app('x'*40);self.client=TestClient(self.app);self.auth={'Authorization':'Bearer '+'x'*40}
        self.app.state.calling.provider=SimpleNamespace(request=lambda *args:None)

    def test_authenticated_opt_in_and_owner_only_settings(self):
        self.assertEqual(self.client.get('/v1/calling').status_code,401)
        self.assertFalse(self.client.get('/v1/calling',headers=self.auth).json()['enabled'])
        self.assertEqual(self.client.post('/v1/calling/start',headers=self.auth,json={'client':'1'*32}).status_code,409)
        body=update().model_dump(mode='json');body.update(api_key='example-key',api_secret='synthetic-secret-'*3,allowed_displays=[])
        self.assertEqual(self.client.put('/v1/calling/settings',headers=self.auth,json=body).status_code,200)
        response=self.client.post('/v1/calling/start',headers=self.auth,json={'client':'1'*32})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.put('/v1/calling/settings',headers=self.auth,json={**body,'revision':1}).status_code,409)
        self.assertTrue(allowed('POST','/v1/calling/start'));self.assertFalse(allowed('PUT','/v1/calling/settings'))

    def test_csp_only_adds_configured_provider_on_display(self):
        self.app.state.calling.store.save(update())
        headers=self.client.get('/display').headers
        self.assertIn("connect-src 'self' wss://calls.example.com https://calls.example.com",headers['Content-Security-Policy'])
        self.assertNotIn('calls.example.com',self.client.get('/settings').headers['Content-Security-Policy'])
        self.assertNotIn('unsafe-eval',headers['Content-Security-Policy'])

    def test_malformed_settings_do_not_echo_secret(self):
        result=self.client.put('/v1/calling/settings',headers=self.auth,json={'api_secret':'do-not-echo-this'})
        self.assertEqual(result.status_code,422);self.assertNotIn('do-not-echo-this',result.text)

    def test_guest_and_unapproved_pair_cannot_call(self):
        displays=self.app.state.calling.displays
        pair=displays.enroll(displays.pairing('Example display')['code'])
        headers={'Authorization':'Display '+pair['credential']}
        self.app.state.calling.store.save(update())
        self.assertEqual(self.client.post('/v1/calling/start',headers=headers,json={'client':'1'*32}).status_code,403)
        self.assertEqual(self.client.get('/v1/calling/settings',headers=headers).status_code,403)
        profile=displays.profile_for('display:'+pair['id']);profile['profile']['mode']='guest'
        displays.save_profile(pair['id'],profile['profile'],0)
        self.assertEqual(self.client.get('/v1/calling',headers=headers).status_code,403)

    def test_lifespan_starts_and_stops_cleanup(self):
        with TestClient(self.app) as client:self.assertEqual(client.get('/health').status_code,200)


if __name__=='__main__':unittest.main()
