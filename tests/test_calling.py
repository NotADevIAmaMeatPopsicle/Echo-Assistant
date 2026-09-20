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

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.calling import CallSettings, CallSettingsUpdate, CallStore, Calling, LiveKit, jwt
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

    def test_deployment_binding_reaches_real_app_call_response(self):
        origin='wss://calls.private.example:8443'
        with patch.dict(os.environ,{'ECHO_CALLING_PRIVATE_ORIGIN':origin}):
            app=create_app('x'*40)
        requests=[]
        def accept(request):
            requests.append(request)
            return httpx.Response(200,json={})
        app.state.calling.provider.transport=httpx.MockTransport(accept)
        client=TestClient(app)
        body=update().model_dump(mode='json')
        body.update(url=origin,api_key='example-key',api_secret='synthetic-secret-'*3,allowed_displays=[])
        self.assertEqual(client.put('/v1/calling/settings',headers=self.auth,json=body).status_code,200)
        response=client.post('/v1/calling/start',headers=self.auth,json={'client':'1'*32})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIs(response.json()['private_transport'],True)
        self.assertEqual(str(requests[0].url),'http://echo-calling:7880/twirp/livekit.RoomService/CreateRoom')
        self.assertEqual(response.json()['url'],origin)


class PrivateCallingTransportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        def accept(request):
            self.requests.append(request)
            return httpx.Response(200, json={})
        self.transport = httpx.MockTransport(accept)
        self.private = 'wss://calls.private.example:8443'
        self.store = CallStore(None, None)
        values = update().model_dump()
        values['url'] = self.private
        self.store.save(CallSettingsUpdate.model_validate(values))

    def test_only_canonical_private_origins_are_accepted(self):
        for origin in ('', 'wss://calls.private.example', self.private, 'wss://127.0.0.1:8443', 'wss://[::1]:8443'):
            with self.subTest(origin=origin):
                self.assertEqual(LiveKit(origin).private_origin, origin)
        for origin in (None, False, 'http://echo-calling:7880', 'https://calls.private.example',
                       'WSS://calls.private.example', 'wss://Calls.private.example',
                       'wss://calls.private.example/', 'wss://calls.private.example/path',
                       'wss://calls.private.example?', 'wss://calls.private.example#',
                       'wss://calls.private.example?token=private', 'wss://user:secret@calls.private.example',
                       'wss://calls.private.example:443', 'wss://calls.private.example:08443',
                       'wss://calls.private.example:0', 'wss://calls.private.example:65536',
                       'wss://calls.private.example.', 'wss://calls..example', 'wss://-calls.example',
                       'wss://[fe80::1%eth0]:8443', 'wss://[fe80::1%25eth0]:8443',
                       'wss://[0:0:0:0:0:0:0:1]:8443', 'wss://127.000.000.001:8443',
                       'wss://calls.private.example\n', ' wss://calls.private.example'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                LiveKit(origin)

    def test_private_admin_uses_fixed_http_and_keeps_admin_token_out_of_response(self):
        provider = LiveKit(self.private, transport=self.transport)
        provider.request(self.store.state, 'CreateRoom', {'name':'synthetic-room'})
        request = self.requests[-1]
        self.assertEqual(str(request.url), 'http://echo-calling:7880/twirp/livekit.RoomService/CreateRoom')
        token = request.headers['Authorization'].removeprefix('Bearer ')
        payload = json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'=='))
        self.assertEqual(payload['video'], {'roomCreate':True})
        self.assertEqual(payload['sub'], 'echo-server')
        self.assertNotIn(token, str(request.url))
        self.assertNotIn(token, request.content.decode())
        self.assertNotIn(self.store.state.api_secret.get_secret_value(), request.headers['Authorization'])

    def test_similar_or_public_origins_keep_https_admin_and_no_private_mode(self):
        provider = LiveKit(self.private, transport=self.transport)
        for origin in ('wss://calls.private.example', 'wss://calls.private.example:9443',
                       'wss://CALLS.private.example:8443', 'wss://calls.private.example.evil:8443',
                       'wss://project.livekit.cloud'):
            with self.subTest(origin=origin):
                settings = self.store.state.model_copy(update={'url':origin})
                self.assertFalse(provider.private_transport(settings))
                provider.request(settings, 'DeleteRoom', {'room':'synthetic-room'})
                self.assertEqual(str(self.requests[-1].url), 'https://'+origin[6:].lower()+'/twirp/livekit.RoomService/DeleteRoom')
        unbound = LiveKit(transport=self.transport)
        self.assertFalse(unbound.private_transport(self.store.state))
        unbound.request(self.store.state, 'CreateRoom', {})
        self.assertEqual(self.requests[-1].url.scheme, 'https')

    def test_private_start_join_only_expose_server_derived_mode(self):
        app = create_app('x'*40)
        app.state.calling.store = self.store
        app.state.calling.provider = LiveKit(self.private, transport=self.transport)
        auth = {'Authorization':'Bearer '+'x'*40}
        with TestClient(app) as client:
            start = client.post('/v1/calling/start', headers=auth, json={'client':'1'*32})
            self.assertEqual(start.status_code, 200, start.text)
            started = start.json()
            joined = client.post('/v1/calling/join', headers=auth, json={'client':'2'*32,'code':started['code']})
            self.assertEqual(joined.status_code, 200, joined.text)
            for response in (started, joined.json()):
                self.assertIs(response['private_transport'], True)
                self.assertEqual(response['url'], self.private)
                self.assertNotIn('echo-calling', json.dumps(response))
                self.assertNotIn(self.requests[0].headers['Authorization'].removeprefix('Bearer '), json.dumps(response))
                self.assertNotIn(self.store.state.api_secret.get_secret_value(), json.dumps(response))
                payload = json.loads(base64.urlsafe_b64decode(response['token'].split('.')[1]+'=='))
                self.assertNotIn('roomCreate', payload['video'])
            self.assertNotIn('private_transport', client.get('/v1/calling', headers=auth).json())
            self.assertNotIn('private_transport', client.get('/v1/calling/settings', headers=auth).json())
            pulse = client.post('/v1/calling/'+started['id']+'/pulse', headers=auth, json={'client':'1'*32})
            self.assertEqual(pulse.status_code, 200)
            self.assertNotIn('private_transport', pulse.json())
            ended = client.post('/v1/calling/'+started['id']+'/end', headers=auth, json={'client':'1'*32})
            self.assertEqual(ended.status_code, 200)
            self.assertEqual(str(self.requests[-1].url), 'http://echo-calling:7880/twirp/livekit.RoomService/DeleteRoom')

    def test_public_start_join_and_owner_settings_cannot_select_private_admin(self):
        displays = SimpleNamespace(profile_for=lambda p:{'profile':{'mode':'household'},'profile_revision':0})
        for origin in ('', 'wss://different.private.example:8443'):
            with self.subTest(private_origin=origin):
                calls = Calling(self.store, displays, LiveKit(origin, transport=self.transport), clock=lambda:1000)
                started = calls.start('owner', '1'*32)
                joined = calls.join('owner', '2'*32, started['code'])
                self.assertNotIn('private_transport', started)
                self.assertNotIn('private_transport', joined)
                self.assertEqual(self.requests[-1].url.scheme, 'https')
                calls.end(started['id'], 'owner', '1'*32)
        for field in ('private_origin', 'private_transport', 'admin_url'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                CallSettingsUpdate.model_validate({**update().model_dump(),field:'http://arbitrary.internal'})

    def test_private_provider_errors_are_redacted_and_delete_404_remains_success(self):
        def fail(request):
            return httpx.Response(503, text='private-response-'+self.store.state.api_secret.get_secret_value())
        provider = LiveKit(self.private, transport=httpx.MockTransport(fail))
        with self.assertRaises(HTTPException) as error:
            provider.request(self.store.state, 'CreateRoom', {})
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn('private-response', error.exception.detail)
        self.assertNotIn('echo-calling', error.exception.detail)
        self.assertNotIn(self.store.state.api_secret.get_secret_value(), error.exception.detail)
        provider = LiveKit(self.private, transport=httpx.MockTransport(lambda request:httpx.Response(404)))
        self.assertIsNone(provider.request(self.store.state, 'DeleteRoom', {}))


if __name__=='__main__':unittest.main()
