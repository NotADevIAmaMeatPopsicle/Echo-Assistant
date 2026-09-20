"""Actual-app personal Google seams with fake OAuth/calendar and temporary recovery."""
import base64
from datetime import datetime, timezone
from functools import partial
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.member_google import MemberGoogle
from tests import test_display_profiles as display_fixtures
from tests import test_members as member_fixtures
from tests.test_google_calendar import configuration
from tests.test_member_google import PrivateFixture
from tests.test_recovery_archive import record
from tools.recovery_archive import FILES, LIMITS, read_archive, write_archive
from tools.recovery_restore import restore


BASE='/v1/member/calendar/google'
CLIENT='a'*64


class MemberGoogleIntegrationTests(unittest.TestCase):
    with_runtime=True
    enroll=display_fixtures.DisplayProfileTests.enroll
    save=display_fixtures.DisplayProfileTests.save
    profile=display_fixtures.DisplayProfileTests.profile
    account=member_fixtures.MemberTests.account
    share=member_fixtures.MemberTests.share
    login=member_fixtures.MemberTests.login

    def setUp(self):
        display_fixtures.DisplayProfileTests.setUp(self)
        self.google_calls=[]
        self.fake=SimpleNamespace(calls=self.google_calls,interrupt=None)
        self.transport=SimpleNamespace(json=partial(PrivateFixture.request,self.fake))
        self.google=self.app.state.google_calendars;self.google.transport=self.transport
        config=configuration()
        response=self.client.put('/v1/calendar/google',headers=self.owner,json={
            'revision':config.revision,'client_id':config.client_id,
            'client_secret':config.client_secret.get_secret_value(),'redirect_uri':config.redirect_uri})
        self.assertEqual(response.status_code,200,response.text)
        self.service=self.app.state.member_google;self.members=self.app.state.members
        self.alice=self.account('Synthetic Alice');self.bob=self.account('Synthetic Bob')
        self.share(self.alice,self.bob);self.personal=self.login(self.alice)
        self.agenda=self.app.state.display_voice.agent.personal.agenda
        self.agenda.clock=lambda:datetime(2026,9,22,13,tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.agenda.experiences.store.snapshot()['sources']['calendars'],[])
        self.assertEqual(self.members.profile_for(self.members.resolve('display:'+self.paired['id']))['profile']['calendars'],[])

    def begin(self,headers=None,label='alice private label'):
        response=self.client.post(BASE+'/flows',headers=headers or self.personal,json={'label':label,'client':CLIENT})
        self.assertEqual(response.status_code,200,response.text)
        flow=response.json();flow['callback_state']=parse_qs(urlsplit(flow['url']).query)['state'][0]
        return flow

    def link(self,headers=None,identity='alice',select=True):
        headers=headers or self.personal;flow=self.begin(headers,identity+' private label')
        # The provider callback deliberately has no owner/display authentication.
        callback=self.client.get('/v1/calendar/google/callback',params={'state':flow['callback_state'],'code':identity})
        self.assertEqual(callback.status_code,200,callback.text)
        status=self.client.get(BASE+'/flows/'+flow['id'],headers=headers,params={'client':CLIENT})
        self.assertEqual(status.json()['status'],'approved',status.text)
        response=self.client.post(BASE+'/flows/'+flow['id']+'/finish',headers=headers,json={'client':CLIENT})
        self.assertEqual(response.status_code,200,response.text);account=response.json()
        response=self.client.post(BASE+'/accounts/'+account['id']+'/sync',headers=headers)
        self.assertEqual(response.status_code,200,response.text)
        settings=self.client.get(BASE,headers=headers).json();entity=settings['calendars'][-1]['entity_id']
        self.assertFalse(settings['calendars'][-1]['selected'])
        if select:self.select(headers,[entity],settings['revision'])
        return account,entity

    def select(self,headers,calendars,revision=None):
        if revision is None:revision=self.client.get(BASE,headers=headers).json()['revision']
        response=self.client.put(BASE+'/selection',headers=headers,json={'revision':revision,'calendars':calendars})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def view(self,headers=None):
        return self.client.get('/v1/display/agenda',headers=headers or self.personal,params={'start':'2026-09-22','days':1})

    def test_real_callback_explicit_selection_and_private_only_display_and_chat(self):
        _,entity=self.link(select=False)
        self.assertEqual(self.view().json()['events'],[])
        self.assertEqual(self.client.get('/v1/display/sources',headers=self.personal).json()['items'],[])
        self.select(self.personal,[entity])
        sources=self.client.get('/v1/display/sources',headers=self.personal)
        self.assertEqual([row['entity_id'] for row in sources.json()['items']],[entity])
        self.assertFalse(any(sources.json()['items'][0][key] for key in ('writable','editable','deletable')))
        response=self.view();self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([event['title'] for event in response.json()['events']],['alice event'])
        event=response.json()['events'][0]
        self.assertIsNone(event['reference']);self.assertIsNone(event['invitation_reference'])
        with patch('backend.agent.HermesRuntime.complete',side_effect=AssertionError('Private agenda reached shared Hermes')):
            reply=self.client.post('/v1/chat',headers=self.personal,json={'text':'What is on my agenda today?'})
        self.assertEqual(reply.status_code,200,reply.text);self.assertEqual(reply.json()['capability'],'calendar_agenda')
        self.assertEqual(reply.json()['event_count'],1);self.assertIn('alice event',reply.json()['text'])
        self.provider.complete.assert_not_called()
        self.assertEqual(self.client.get('/v1/display/briefing?timezone=UTC',headers=self.personal).status_code,403)
        self.assertEqual(self.google.accounts,[])
        self.google_calls.clear()
        for path in ('/v1/display/source-settings','/v1/display/sources','/v1/display/agenda?start=2026-09-22&days=1','/v1/display/briefing?timezone=UTC'):
            result=self.client.get(path,headers=self.owner)
            self.assertEqual(result.status_code,200,result.text)
            self.assertNotIn(entity,result.text);self.assertNotIn('alice event',result.text);self.assertNotIn('alice private label',result.text)
        self.assertEqual(self.google_calls,[],'Household discovery/briefing must not query private credentials')

    def test_other_person_household_and_guest_cannot_see_or_control_namespace(self):
        account,entity=self.link();flow=self.begin(label='Another private Alice account')
        other=self.login(self.bob)
        self.assertEqual(self.client.get(BASE,headers=other).json()['accounts'],[])
        self.assertEqual(self.view(other).json()['events'],[])
        self.assertEqual(self.client.get(BASE+'/flows/'+flow['id'],headers=other,params={'client':CLIENT}).status_code,404)
        self.assertEqual(self.client.post(BASE+'/flows/'+flow['id']+'/finish',headers=other,json={'client':CLIENT}).status_code,404)
        self.assertEqual(self.client.put(BASE+'/selection',headers=other,json={'revision':0,'calendars':[entity]}).status_code,422)
        self.assertEqual(self.client.delete(BASE+'/accounts/'+account['id'],headers=other).status_code,404)
        self.assertEqual(self.client.post(BASE+'/accounts/'+account['id']+'/sync',headers=other).status_code,503)
        self.client.delete('/v1/member/session',headers=other).raise_for_status()
        self.google_calls.clear()
        for headers in (self.owner,self.guest):
            for method,path,body in [('GET',BASE,None),('POST',BASE+'/flows',{'label':'No access','client':CLIENT}),
                    ('PUT',BASE+'/selection',{'revision':0,'calendars':[entity]}),('DELETE',BASE+'/accounts/'+account['id'],None)]:
                result=self.client.request(method,path,headers=headers,json=body)
                self.assertEqual(result.status_code,403,result.text)
            self.assertEqual(self.view(headers).json()['events'],[])
        self.assertEqual(self.save(self.profile(),revision=1).status_code,200)
        for method,path,body in [('GET',BASE,None),('POST',BASE+'/flows',{'label':'No access','client':CLIENT}),
                ('PUT',BASE+'/selection',{'revision':0,'calendars':[entity]}),('DELETE',BASE+'/accounts/'+account['id'],None)]:
            self.assertEqual(self.client.request(method,path,headers=self.guest,json=body).status_code,403)
        self.assertEqual(self.view(self.guest).json()['events'],[])
        self.assertEqual(self.google_calls,[])
        self.assertEqual(self.service.records[self.alice['id']]['selection']['calendars'],[entity])

    def test_actual_logout_and_session_expiry_cancel_anonymous_callback_flows(self):
        for expire in (False,True):
            with self.subTest(expire=expire):
                self.personal=self.login(self.alice);flow=self.begin();self.google_calls.clear()
                if expire:
                    with patch.object(self.members,'clock',return_value=self.members.clock()+901):
                        session=self.client.get('/v1/display/session',headers=self.guest)
                        self.assertEqual(session.status_code,200,session.text)
                        self.assertNotIn('member',session.json())
                else:
                    self.client.delete('/v1/member/session',headers=self.personal).raise_for_status()
                self.assertEqual(self.service.flows,{})
                self.assertEqual(self.service.providers[self.alice['id']].flows,{})
                callback=self.client.get('/v1/calendar/google/callback',params={'state':flow['callback_state'],'code':'alice'})
                self.assertGreaterEqual(callback.status_code,400)
                self.assertEqual(self.google_calls,[])
                self.assertEqual(self.service.providers[self.alice['id']].accounts,[])

    def test_owner_deletion_removes_encrypted_member_namespace_and_pending_flow(self):
        self.link();self.begin(label='Pending deleted member')
        self.assertIn(self.alice['id'],self.service.records)
        result=self.client.request('DELETE','/v1/members/'+self.alice['id'],headers=self.owner,json={'revision':0})
        self.assertEqual(result.status_code,200,result.text)
        self.assertNotIn(self.alice['id'],self.service.records)
        self.assertNotIn(self.alice['id'],self.service.providers)
        self.assertEqual(self.service.flows,{})
        restored=MemberGoogle(self.members,self.google,self.root,self.protector)
        self.assertNotIn(self.alice['id'],restored.records)
        self.assertIn(self.bob['id'],self.members.records)
        self.assertNotIn(b'refresh-alice',self.service.path.read_bytes())

    def test_actual_display_and_conversation_discard_mid_fetch_private_selection_change(self):
        _,entity=self.link()
        for chat in (False,True):
            with self.subTest(chat=chat):
                self.select(self.personal,[entity])
                principal=self.members.resolve('display:'+self.paired['id'])
                def interrupt(method,url):
                    if method=='GET' and url.endswith('/events'):
                        self.service.select(principal,[],self.service.settings(principal)['revision'])
                self.fake.interrupt=interrupt
                try:
                    response=(self.client.post('/v1/chat',headers=self.personal,json={'text':'What is on my agenda today?'}) if chat else self.view())
                finally:self.fake.interrupt=None
                self.assertEqual(response.status_code,200 if chat else 409,response.text)
                if chat:self.assertEqual(response.json()['status'],'unavailable')
                self.assertNotIn('alice event',response.text)
        self.provider.complete.assert_not_called()

    def test_encrypted_registry_roundtrip_restores_private_selection_in_fresh_app(self):
        account,entity=self.link();key=base64.b64encode((self.root/'key').read_bytes()).decode()
        self.assertIn('echo-member-google.json',FILES);self.assertEqual(LIMITS['echo-member-google.json'],8_000_000)
        names=('echo-members.json','echo-google-calendar.json','echo-member-google.json')
        payload={'kind':'echo-remote','version':2,'created_at':1.0,
            'files':{name:record((self.root/'local'/name).read_bytes()) for name in names},'photos':{},
            'bootstrap':{'api':{'storage_key':key},'agent':{}}}
        archive=self.root/'private-registry.echo-backup'
        write_archive(archive,payload,self.protector,lambda _:self.fail('No photo was included'))
        for text in (b'refresh-alice',b'alice private label',entity.encode()):self.assertNotIn(text,archive.read_bytes())
        loaded=read_archive(archive,self.protector)
        replacement=self.root/'replacement';destination=replacement/'local';destination.mkdir(parents=True)
        header={'names':FILES,'limits':LIMITS,'files':loaded['files'],'photos':{},'storage_key':key}
        restore(destination,io.BytesIO(json.dumps(header).encode()+b'\n'))
        fresh=create_app('replacement-token-'*3,home=self.home,home_catalog=self.catalog,home_access_store=self.access,
            settings_store=self.settings,provider=self.provider,runtime_root=replacement)
        fresh.state.google_calendars.transport=self.transport
        client=TestClient(fresh,base_url='http://localhost');self.addCleanup(client.close)
        self.assertEqual(fresh.state.members.sessions,{})
        self.assertEqual(fresh.state.member_google.flows,{})
        owner={'Authorization':'Bearer '+'replacement-token-'*3}
        login=client.post('/v1/member/session',headers=owner,json={'member':self.alice['id'],'passcode':self.alice['passcode']})
        self.assertEqual(login.status_code,200,login.text)
        headers={**owner,'X-Echo-Profile-Revision':str(login.json()['profile_revision'])}
        settings=client.get(BASE,headers=headers)
        self.assertEqual(settings.status_code,200,settings.text)
        self.assertEqual(settings.json()['accounts'][0]['id'],account['id'])
        self.assertEqual(settings.json()['calendars'][0]['entity_id'],entity)
        self.assertTrue(settings.json()['calendars'][0]['selected'])
        agenda=client.get('/v1/display/agenda',headers=headers,params={'start':'2026-09-22','days':1})
        self.assertEqual(agenda.status_code,200,agenda.text)
        self.assertEqual([event['title'] for event in agenda.json()['events']],['alice event'])
        self.assertEqual(fresh.state.google_calendars.accounts,[])


if __name__=='__main__':unittest.main()
