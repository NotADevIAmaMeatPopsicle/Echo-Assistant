"""Synthetic Google OAuth and scoped agenda reads. No real account or network."""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs,urlsplit

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from backend.app import create_app
from backend.google_calendar import GoogleCalendars,GoogleConfig,READ_SCOPES,CALLBACK
from backend.experiences import Experiences,SourceStore
from backend.home import HomeBridge,HomeConfig,HomeUnavailable
from backend.linux_protection import LinuxProtector


def configuration():
    return GoogleConfig(revision=0,client_id='123-example.apps.googleusercontent.com',client_secret='synthetic-client-secret',
                        redirect_uri='https://echo.example.com'+CALLBACK)


class GoogleTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.;self.calls=[];self.interrupt=None
        self.remote=[{'id':'example-calendar@example.com','summary':'Sample calendar','timeZone':'UTC','accessRole':'owner'}]
        self.rows=[{'id':'provider-event','summary':'Sample meeting','start':{'dateTime':'2026-09-22T10:00:00+00:00'},
                    'end':{'dateTime':'2026-09-22T11:00:00+00:00'}}]
        self.token_scope=' '.join(READ_SCOPES)
        self.transport=SimpleNamespace(json=self.request)
        self.google=GoogleCalendars(None,None,self.transport,lambda:self.now)
        self.google.configure(configuration())

    def request(self,method,url,**kwargs):
        self.calls.append((method,url,deepcopy(kwargs)))
        if url.endswith('/token'):
            return {'access_token':'synthetic-access-token','refresh_token':'synthetic-refresh-token','scope':self.token_scope,'expires_in':3600}
        if url.endswith('/calendarList'):return {'items':deepcopy(self.remote)}
        if self.interrupt:self.interrupt()
        return {'items':deepcopy(self.rows)}

    def approve(self,google=None):
        google=google or self.google
        flow=google.begin('Sample account','owner-session','1'*64);query=parse_qs(urlsplit(flow['url']).query)
        google.callback(query['state'][0],'synthetic-code','')
        return flow

    def connected(self):
        f=self.approve();account=self.google.finish(f['id'],'owner-session','1'*64);self.google.sync(account['id']);return account

    def test_pkce_state_and_read_only_permissions(self):
        flow=self.google.begin('Sample account','owner-session','1'*64);query=parse_qs(urlsplit(flow['url']).query)
        self.assertEqual(query['scope'][0],' '.join(READ_SCOPES));self.assertEqual(query['code_challenge_method'],['S256'])
        self.assertNotIn(query['state'][0],repr(self.google.flows))
        self.google.callback(query['state'][0],'synthetic-code','')
        verifier=self.calls[0][2]['data']['code_verifier']
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(challenge,query['code_challenge'][0]);self.assertEqual(self.google.accounts,[])
        self.assertEqual(self.google.flow_status(flow['id'],'owner-session','1'*64)['status'],'approved')
        with self.assertRaises(HTTPException):self.google.callback(query['state'][0],'replayed-code','')
        self.assertEqual(len(self.calls),1)

    def test_finish_requires_original_owner_session_and_is_one_use(self):
        flow=self.approve()
        with self.assertRaises(HTTPException):self.google.finish(flow['id'],'different-session','1'*64)
        with self.assertRaises(HTTPException):self.google.finish(flow['id'],'owner-session','2'*64)
        self.google.finish(flow['id'],'owner-session','1'*64)
        with self.assertRaises(HTTPException):self.google.finish(flow['id'],'owner-session','1'*64)
        self.assertEqual(len(self.google.accounts),1)

    def test_cancel_decline_expiry_and_missing_scope_do_not_link(self):
        flow=self.google.begin('Sample','owner-session','1'*64);query=parse_qs(urlsplit(flow['url']).query)
        self.google.callback(query['state'][0],'','access_denied')
        self.assertEqual(self.google.flow_status(flow['id'],'owner-session','1'*64)['status'],'declined')
        with self.assertRaises(HTTPException):self.google.finish(flow['id'],'owner-session','1'*64)
        self.google.cancel(flow['id'],'owner-session','1'*64);self.token_scope=READ_SCOPES[0]
        with self.assertRaises(HomeUnavailable):self.approve()
        self.now+=601;self.google.prune();self.assertFalse(self.google.flows);self.assertFalse(self.google.accounts)

    def test_cancel_during_provider_exchange_discards_result(self):
        flow=self.google.begin('Sample','owner-session','1'*64);query=parse_qs(urlsplit(flow['url']).query)
        original=self.transport.json
        def cancelled(*args,**kwargs):
            self.google.cancel(flow['id'],'owner-session','1'*64);return original(*args,**kwargs)
        self.transport.json=cancelled
        with self.assertRaises(HTTPException):self.google.callback(query['state'][0],'synthetic-code','')
        self.assertFalse(self.google.accounts);self.assertFalse(self.google.flows)

    def test_encrypted_connection_survives_restart_without_access_token(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);key=root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600);protector=LinuxProtector(key)
            google=GoogleCalendars(root,protector,self.transport,lambda:self.now);google.configure(configuration())
            f=self.approve(google);a=google.finish(f['id'],'owner-session','1'*64);google.sync(a['id'])
            raw=google.path.read_bytes()
            for text in (b'synthetic-refresh-token',b'synthetic-client-secret',b'Sample calendar'):self.assertNotIn(text,raw)
            restored=GoogleCalendars(root,protector,self.transport,lambda:self.now)
            self.assertEqual(restored.settings()['accounts'][0]['calendar_count'],1)
            self.assertFalse(restored.access);self.assertFalse(restored.flows)
            self.assertNotIn('refresh_token',json.dumps(restored.settings()))
            restored.disconnect(a['id']);self.assertEqual(GoogleCalendars(root,protector).settings()['accounts'],[])

    def test_inventory_is_not_automatically_shared_and_works_without_ha(self):
        account=self.connected();catalog=self.google.catalog();self.assertEqual(len(catalog),1)
        entity=catalog[0]['entity_id'];self.assertNotIn('@',entity)
        exp=Experiences(HomeBridge(HomeConfig()),SourceStore(None,None),google=self.google)
        self.assertEqual(exp.agenda('2026-09-22')['events'],[])
        exp.save_sources({'calendars':[entity]},0)
        result=exp.agenda('2026-09-22');self.assertEqual(result['events'][0]['title'],'Sample meeting')
        self.assertIsNone(result['events'][0]['reference'])
        self.assertEqual(result['events'][0]['change_scopes'],{'edit':[],'delete':[]})
        with self.assertRaises(ValueError):exp.save_sources({'calendars':[entity],'writable_calendars':[entity]},1)
        self.assertTrue(all(call[0]=='GET' or call[1].endswith('/token') for call in self.calls))
        self.google.disconnect(account['id']);self.assertFalse(self.google.catalog())

    def test_remote_resource_ids_are_quoted_and_revocation_discards_result(self):
        self.remote[0]['id']='odd/calendar?#name@example.com';account=self.connected();entity=self.google.catalog()[0]['entity_id']
        self.google.events(entity,'2026-09-22T00:00:00Z','2026-09-23T00:00:00Z')
        self.assertIn('odd%2Fcalendar%3F%23name%40example.com',self.calls[-1][1])
        self.interrupt=lambda:self.google.disconnect(account['id'])
        with self.assertRaises(HomeUnavailable):self.google.events(entity,'2026-09-22T00:00:00Z','2026-09-23T00:00:00Z')

    def test_missing_inventory_tokens_or_partial_events_fail_explicitly(self):
        self.connected();entity=self.google.catalog()[0]['entity_id']
        self.transport.json=lambda *a,**k:{'items':[],'nextPageToken':'more'}
        with self.assertRaises(HomeUnavailable):self.google.events(entity,'2026-09-22T00:00:00Z','2026-09-23T00:00:00Z')
        self.google.access.clear();self.transport.json=lambda *a,**k:{'access_token':'x','expires_in':False}
        with self.assertRaises(HomeUnavailable):self.google.events(entity,'a','b')

    def test_config_change_does_not_reuse_another_clients_secret(self):
        config=configuration();config.revision=1;config.client_id='123-other.apps.googleusercontent.com';config.client_secret=SecretStr('')
        with self.assertRaises(HTTPException):self.google.configure(config)
        self.connected();config=configuration();config.revision=1
        with self.assertRaises(HTTPException):self.google.configure(config)

    def test_validation_and_invalid_redirects(self):
        for uri in ['http://echo.example.com'+CALLBACK,'https://user:pass@echo.example.com'+CALLBACK,'https://echo.example.com/wrong','https://echo.example.com'+CALLBACK+'?x=1']:
            with self.assertRaises(ValueError):GoogleConfig(revision=0,redirect_uri=uri)
        self.connected();entity=self.google.catalog()[0]['entity_id'];self.google.enabled=False
        with self.assertRaises(HTTPException):self.google.begin('Sample','owner-session','1'*64)
        with self.assertRaises(HomeUnavailable):self.google.events(entity,'2026-09-22T00:00:00Z','2026-09-23T00:00:00Z')
        self.assertEqual(self.google.catalog(),[])


class GoogleApiTests(unittest.TestCase):
    def setUp(self):
        self.app=create_app('x'*40);self.client=TestClient(self.app);self.auth={'Authorization':'Bearer '+'x'*40}
        helper=GoogleTests();helper.setUp();self.google=self.app.state.google_calendars;self.google.transport=helper.transport
        self.google.configure(configuration())

    def test_owner_only_setup_and_callback_state_requirements(self):
        self.assertEqual(self.client.get('/v1/calendar/google').status_code,401)
        self.assertEqual(self.client.get(CALLBACK,params={'state':'z'*43,'code':'secret-code'}).status_code,400)
        self.assertNotIn('secret-code',self.client.get(CALLBACK,params={'state':'z'*43,'code':'secret-code'}).text)
        displays=self.app.state.calling.displays;pair=displays.enroll(displays.pairing('Sample display')['code'])
        self.assertEqual(self.client.get('/v1/calendar/google',headers={'Authorization':'Display '+pair['credential']}).status_code,403)

    def test_full_callback_and_finish_never_return_tokens(self):
        result=self.client.post('/v1/calendar/google/flows',headers=self.auth,json={'label':'Sample','client':'1'*64});self.assertEqual(result.status_code,200)
        flow=result.json();state=parse_qs(urlsplit(flow['url']).query)['state'][0]
        callback=self.client.get(CALLBACK,params={'state':state,'code':'synthetic-code'});self.assertEqual(callback.status_code,200)
        self.assertNotIn('synthetic-code',callback.text)
        status=self.client.get('/v1/calendar/google/flows/'+flow['id'],headers=self.auth,params={'client':'1'*64});self.assertEqual(status.json()['status'],'approved')
        self.assertNotIn('token',status.text)
        result=self.client.post('/v1/calendar/google/flows/'+flow['id']+'/finish',headers=self.auth,json={'client':'1'*64})
        self.assertEqual(result.status_code,200);self.assertNotIn('token',result.text)
        account=result.json()['id'];self.assertEqual(self.client.post('/v1/calendar/google/accounts/'+account+'/sync',headers=self.auth,json={}).status_code,200)
        value=self.client.get('/v1/calendar/google',headers=self.auth)
        self.assertEqual(value.json()['accounts'][0]['calendar_count'],1);self.assertNotIn('synthetic-client-secret',value.text)

    def test_shared_google_calendar_respects_guest_grant_intersection(self):
        flow=self.google.begin('Shared account','owner-session','1'*64)
        state=parse_qs(urlsplit(flow['url']).query)['state'][0];self.google.callback(state,'synthetic-code','')
        account=self.google.finish(flow['id'],'owner-session','1'*64);self.google.sync(account['id'])
        entity=self.google.catalog()[0]['entity_id']
        self.assertEqual(self.client.put('/v1/display/source-settings',headers=self.auth,json={'revision':0,'sources':{'calendars':[entity]}}).status_code,200)
        displays=self.app.state.calling.displays;pair=displays.enroll(displays.pairing('Sample guest')['code']);headers={'Authorization':'Display '+pair['credential']}
        profile=displays.profile_for('display:'+pair['id'])['profile'];profile['mode']='guest'
        displays.save_profile(pair['id'],profile,0)
        self.assertEqual(self.client.get('/v1/display/agenda?start=2026-09-22',headers=headers).json()['events'],[])
        profile['calendars']=[entity];displays.save_profile(pair['id'],profile,1)
        result=self.client.get('/v1/display/agenda?start=2026-09-22',headers=headers)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['events'][0]['title'],'Sample meeting')
        self.google.disconnect(account['id'])
        self.assertEqual(self.client.get('/v1/display/agenda?start=2026-09-22',headers=headers).json()['events'],[])


if __name__=='__main__':unittest.main()
