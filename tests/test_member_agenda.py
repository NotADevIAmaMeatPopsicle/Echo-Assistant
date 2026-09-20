"""Personal calendar voice requests through the real API, with synthetic sources."""
from datetime import datetime, timezone
from threading import Event
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from backend.display_profiles import DisplayProfile
from backend.member_agenda import agenda_request
from tests import test_display_profiles as fixtures
from tests import test_members


class MemberAgendaTests(unittest.TestCase):
    enroll=fixtures.DisplayProfileTests.enroll
    save=fixtures.DisplayProfileTests.save
    profile=fixtures.DisplayProfileTests.profile
    share_sources=fixtures.DisplayProfileTests.share_sources
    account=test_members.MemberTests.account
    share=test_members.MemberTests.share
    login=test_members.MemberTests.login

    def setUp(self):
        fixtures.DisplayProfileTests.setUp(self)
        self.agenda=self.app.state.display_voice.agent.personal.agenda
        self.agenda.clock=lambda:datetime(2026,9,20,14,tzinfo=timezone.utc).timestamp()
        self.share_sources()
        self.person=self.account();self.share(self.person)
        self.client.put('/v1/members/'+self.person['id']+'/profile',headers=self.owner,json={
            'revision':0,'profile':self.profile(calendars=['calendar.shared'])}).raise_for_status()
        self.headers=self.login(self.person)

    def ask(self,text='What is on my agenda today?',**values):
        return self.client.post('/v1/chat',headers=self.headers,json={'text':text,**values})

    def test_shared_agenda_uses_no_household_data_or_model(self):
        self.calls.clear()
        with patch('backend.agent.HermesRuntime.complete',side_effect=AssertionError('Reached shared Hermes')):
            result=self.ask('Give me my daily briefing')
        self.assertEqual(result.status_code,200,result.text)
        body=result.json();self.assertEqual(body['capability'],'calendar_agenda')
        self.assertEqual(body['event_count'],1);self.assertIn('calendar.shared event',body['text'])
        self.assertNotIn('private',result.text);self.assertNotIn('description',result.text)
        self.assertFalse(any('/api/calendars/calendar.private' in url for url in self.calls))
        self.provider.complete.assert_not_called()
        self.assertEqual(self.client.get('/v1/display/briefing?timezone=UTC',headers=self.headers).status_code,403)

    def test_dates_remaining_events_and_partial_failure(self):
        original=self.home._request
        def request(method,path,*args,**kwargs):
            if path=='/api/config':return {'time_zone':'UTC'}
            if path.startswith('/api/calendars/'):
                return [{'summary':title,'start':{'dateTime':start},'end':{'dateTime':end}} for title,start,end in [
                    ('Finished','2026-09-20T09:00:00+00:00','2026-09-20T10:00:00+00:00'),
                    ('Still ongoing','2026-09-20T13:00:00+00:00','2026-09-20T15:00:00+00:00'),
                    ('Tomorrow event','2026-09-21T16:00:00+00:00','2026-09-21T17:00:00+00:00'),
                    ('Outside week','2026-09-27T16:00:00+00:00','2026-09-27T17:00:00+00:00')]]
            return original(method,path,*args,**kwargs)
        with patch.object(self.home,'_request',side_effect=request):
            today=self.ask().json();tomorrow=self.ask('Show my calendar tomorrow').json()
            week=self.ask('Check my schedule this week').json()
        self.assertEqual([e['title'] for e in today['events']],['Still ongoing'])
        self.assertEqual([e['title'] for e in tomorrow['events']],['Tomorrow event'])
        self.assertEqual(week['event_count'],2);self.assertEqual(week['days'],7)
        from backend.home import HomeUnavailable
        def failed(method,path,*args,**kwargs):
            if path.startswith('/api/calendars/'):raise HomeUnavailable('Synthetic failure')
            return original(method,path,*args,**kwargs)
        with patch.object(self.home,'_request',side_effect=failed):result=self.ask().json()
        self.assertTrue(result['partial']);self.assertEqual(result['status'],'unavailable')
        self.assertNotIn('No remaining events',result['text'])

    def test_no_calendars_and_lookup_do_not_fall_through_to_provider(self):
        self.calls.clear()
        response=self.ask(lookup=True)
        self.assertEqual(response.json()['status'],'unavailable');self.assertEqual(self.calls,[])
        self.client.put('/v1/members/'+self.person['id']+'/profile',headers=self.owner,json={
            'revision':1,'profile':self.profile()}).raise_for_status()
        self.headers=self.login(self.person);response=self.ask()
        self.assertIn('No calendars',response.json()['text']);self.provider.complete.assert_not_called()

    def test_account_lock_and_global_revocation_during_read_discard_reply(self):
        original=self.home._request
        def request(method,path,*args,**kwargs):
            value=original(method,path,*args,**kwargs)
            if path.startswith('/api/calendars/'):
                self.app.state.members.lock_session('display:'+self.paired['id'])
            return value
        with patch.object(self.home,'_request',side_effect=request):result=self.ask()
        self.assertIn(result.status_code,[401,409]);self.assertNotIn('calendar.shared event',result.text)
        self.headers=self.login(self.person)
        def revoke(method,path,*args,**kwargs):
            value=original(method,path,*args,**kwargs)
            if path.startswith('/api/calendars/'):
                store=self.agenda.experiences.store;state=store.snapshot()
                state['sources']['calendars']=[];state['sources']['writable_calendars']=[]
                store.save(state['sources'],state['revision'])
            return value
        with patch.object(self.home,'_request',side_effect=revoke):result=self.ask()
        self.assertEqual(result.json()['status'],'unavailable');self.assertNotIn('calendar.shared event',result.text)

    def test_mini_uses_same_account_grants(self):
        self.app.state.members.round_ready=lambda:True
        self.client.put('/v1/round/profile',headers=self.owner,json={
            'revision':0,'profile':DisplayProfile(members=[self.person['id']]).model_dump()}).raise_for_status()
        headers={**self.owner,'X-Echo-Endpoint':'round','X-Echo-Access-Revision':'1'}
        session=self.client.post('/v1/member/session',headers=headers,json={
            'member':self.person['id'],'passcode':self.person['passcode']})
        session.raise_for_status();headers['X-Echo-Access-Revision']=str(session.json()['profile_revision'])
        response=self.client.post('/v1/text',headers=headers,json={'text':'Read my calendar today'})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['event_count'],1)
        self.assertNotIn('private',response.text);self.provider.complete.assert_not_called()

    def test_cancellation_and_bounded_intents(self):
        principal=self.app.state.members.resolve('display:'+self.paired['id'])
        before=self.app.state.members.profile_for(principal);cancel=Event();cancel.set()
        self.calls.clear()
        with self.assertRaises(HTTPException):self.agenda.respond('today',principal,before,cancel=cancel)
        self.assertEqual(self.calls,[])
        self.assertEqual(agenda_request('What’s on my calendar tomorrow?'),'tomorrow')
        for text in ['Delete my calendar','Remember my calendar tomorrow','Search for a calendar app','What is on my calendar next month?']:
            self.assertIsNone(agenda_request(text))


if __name__=='__main__':unittest.main()
