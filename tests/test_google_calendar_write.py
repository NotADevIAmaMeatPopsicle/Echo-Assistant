"""Reviewed Google writes against a synthetic provider; no real accounts or network."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event,RLock,Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit

import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.calendar_events import CalendarWriter
from backend.calendar_reference import event_reference
from backend.experiences import Experiences,SourceStore,ExperienceConflict,ExperienceUnavailable
from backend.google_calendar import GoogleCalendars,GoogleTransport,GoogleRejected,READ_SCOPES,WRITE_SCOPE
from backend.google_calendar_write import GoogleCalendarWriter,editable_event
from backend.home import HomeBridge,HomeConfig,HomeUnavailable
from backend.linux_protection import LinuxProtector
from tests.test_google_calendar import configuration


class WriteFixture:
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        key=self.root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600);self.protector=LinuxProtector(key)
        self.calls=[];self.failure=None;self.interrupt=None;self.role='owner'
        self.scopes=' '.join((READ_SCOPES[0],WRITE_SCOPE))
        self.remote='synthetic/calendar@example.com'
        self.items={
            'single':{'id':'single','etag':'"single-v1"','summary':'Appointment','description':'Keep notes','location':'Park',
                'start':{'dateTime':'2026-09-22T10:00:00-04:00','timeZone':'America/New_York'},
                'end':{'dateTime':'2026-09-22T11:00:00-04:00','timeZone':'America/New_York'}},
            'master':{'id':'master','etag':'"master-v1"','summary':'Weekly studio','recurrence':['RRULE:FREQ=WEEKLY;COUNT=10'],
                'start':{'dateTime':'2026-09-01T10:00:00-04:00','timeZone':'America/New_York'},
                'end':{'dateTime':'2026-09-01T11:00:00-04:00','timeZone':'America/New_York'}},
            'occurrence_20260922':{'id':'occurrence_20260922','etag':'"occurrence-v1"','summary':'Weekly studio',
                'recurringEventId':'master','originalStartTime':{'dateTime':'2026-09-22T10:00:00-04:00'},
                'start':{'dateTime':'2026-09-22T10:00:00-04:00','timeZone':'America/New_York'},
                'end':{'dateTime':'2026-09-22T11:00:00-04:00','timeZone':'America/New_York'}}}
        self.transport=SimpleNamespace(json=self.request)
        self.google=GoogleCalendars(None,None,self.transport);self.google.configure(configuration())
        self.connect()
        self.entity=self.google.catalog()[0]['entity_id']
        self.exp=Experiences(HomeBridge(HomeConfig()),SourceStore(self.root,self.protector),google=self.google)
        self.exp.save_sources({'calendars':[self.entity],'writable_calendars':[self.entity],'managed_calendars':[self.entity]},0)
        self.writer=CalendarWriter(self.exp,self.root,self.protector)
        self.event={'calendar':self.entity,'title':'Reviewed appointment','start':'2026-09-22T10:00',
                    'end':'2026-09-22T11:00','timezone':'America/New_York'}
        self.calls.clear()

    def connect(self,write=True):
        flow=self.google.begin('Synthetic account','owner','a'*64,write)
        self.google.callback(parse_qs(urlsplit(flow['url']).query)['state'][0],'synthetic-code','')
        account=self.google.finish(flow['id'],'owner','a'*64);self.google.sync(account['id'])
        return account

    def request(self,method,url,**kwargs):
        self.calls.append((method,url,deepcopy(kwargs)))
        if self.interrupt:self.interrupt(method,url)
        if url.endswith('/token'):
            return {'access_token':'synthetic-access','refresh_token':'synthetic-refresh','scope':self.scopes,'expires_in':3600}
        if '/calendarList' in url:
            row={'id':self.remote,'summary':'Synthetic calendar','timeZone':'America/New_York','accessRole':self.role}
            return {'items':[row]} if url.endswith('/calendarList') else row
        if method=='GET':
            return {'items':[deepcopy(self.items['single']),deepcopy(self.items['occurrence_20260922'])]} if url.endswith('/events') else deepcopy(self.items[url.rsplit('/',1)[1]])
        if self.failure=='lost':raise HomeUnavailable('Synthetic response loss')
        if self.failure=='etag':raise GoogleRejected('Synthetic precondition rejection')
        if self.failure=='malformed':return {}
        if method=='DELETE':return {}
        payload=kwargs['json'];uid=payload.get('id') or url.rsplit('/',1)[1]
        return {**deepcopy(self.items.get(uid,{})),**deepcopy(payload),'id':uid,'etag':'"accepted-v2"'}

    def reference(self,uid='single'):
        return event_reference(self.google.event_row(self.items[uid]),self.entity,'2026-09-22')

    def writes(self):return [c for c in self.calls if c[0] in {'POST','PATCH','DELETE'} and not c[1].endswith('/token')]


class GoogleWriteTests(WriteFixture,unittest.TestCase):
    def test_optional_consent_is_explicit_and_scope_denial_cannot_link(self):
        flow=self.google.begin('Read only','owner','b'*64)
        self.assertEqual(set(parse_qs(urlsplit(flow['url']).query)['scope'][0].split()),set(READ_SCOPES))
        self.google.callback(parse_qs(urlsplit(flow['url']).query)['state'][0],'code','')
        account=self.google.finish(flow['id'],'owner','b'*64)
        self.assertFalse(self.google.account(account['id'])['write_access'])
        flow=self.google.begin('Write requested','owner','c'*64,True)
        self.assertIn(WRITE_SCOPE,parse_qs(urlsplit(flow['url']).query)['scope'][0].split())
        self.scopes=' '.join(READ_SCOPES)
        with self.assertRaises(HomeUnavailable):self.google.callback(parse_qs(urlsplit(flow['url']).query)['state'][0],'code','')
        self.assertEqual(len(self.google.accounts),2)

    def test_create_recurring_with_provider_id_separate_grants_and_no_invitations(self):
        event={**self.event,'recurrence':{'frequency':'weekly','interval':2,'count':10}}
        self.assertEqual(self.writer.create(event,1,'1'*32,'owner')['status'],'accepted')
        method,url,options=self.writes()[0];payload=options['json']
        self.assertEqual(method,'POST');self.assertIn('synthetic%2Fcalendar%40example.com',url)
        self.assertEqual(payload['id'],'echo'+hashlib.sha256(('1'*32).encode()).hexdigest())
        self.assertEqual(payload['recurrence'],['RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=10'])
        self.assertEqual(options['params'],{'sendUpdates':'none'});self.assertNotIn('attendees',payload)
        self.assertNotIn(b'Reviewed appointment',self.writer.path.read_bytes())

    def test_read_only_echo_grants_provider_role_and_validation_mode_deny(self):
        self.google.accounts[0]['write_access']=False
        with self.assertRaises(PermissionError):self.writer.create(self.event,1,'1'*32,'owner')
        self.google.accounts[0]['write_access']=True;self.role='reader'
        with self.assertRaises(PermissionError):self.writer.create(self.event,1,'1'*32,'owner')
        self.role='owner';self.exp.store.save({'calendars':[self.entity]},1)
        with self.assertRaises(PermissionError):self.writer.create(self.event,2,'1'*32,'owner')
        with self.assertRaises(PermissionError):self.writer.change('delete',self.reference(),None,2,'1'*32,'owner')
        self.writer.enabled=False
        with self.assertRaises(PermissionError):self.writer.create(self.event,2,'1'*32,'owner')
        self.assertEqual(self.writes(),[])

    def test_single_and_occurrence_crud_preserves_provider_fields_and_conditions(self):
        for index,uid in enumerate(('single','occurrence_20260922')):
            scope='single' if index==0 else 'occurrence'
            ref=self.reference(uid)
            self.assertEqual(self.writer.change('edit',ref,self.event,1,str(index+1)*32,'owner',scope=scope)['status'],'accepted')
            method,url,options=self.writes()[-1]
            self.assertEqual(method,'PATCH');self.assertTrue(url.endswith('/'+uid))
            self.assertEqual(options['headers']['If-Match'],self.items[uid]['etag'])
            self.assertEqual(set(options['json']),{'summary','description','location','start','end'})
            self.assertEqual(self.writer.change('delete',ref,None,1,str(index+3)*32,'owner',scope=scope)['status'],'accepted')
            self.assertEqual(self.writes()[-1][0],'DELETE')

    def test_master_review_uses_original_dates_and_moved_series_omits_count(self):
        master=GoogleCalendarWriter(self.writer).master(self.reference('occurrence_20260922'),1)
        self.assertEqual(master['editor_event']['start'],'2026-09-01T10:00')
        self.assertEqual(master['reference']['uid'],'master');self.assertIn('COUNT=10',master['repeat_summary'])
        replacement={**master['editor_event'],'start':'2026-09-02T12:00','end':'2026-09-02T13:00'}
        self.assertEqual(self.writer.change('edit',master['reference'],replacement,1,'1'*32,'owner',scope='series')['status'],'accepted')
        options=self.writes()[-1][2];self.assertNotIn('recurrence',options['json'])
        self.assertEqual(options['headers']['If-Match'],'"master-v1"')
        self.assertEqual(self.items['master']['recurrence'],['RRULE:FREQ=WEEKLY;COUNT=10'])
        self.assertEqual(self.writer.change('delete',self.reference('occurrence_20260922'),None,1,'2'*32,'owner',scope='series')['status'],'accepted')
        self.assertTrue(self.writes()[-1][1].endswith('/master'))

    def test_master_all_day_and_dst_fold_review_preserve_original_bounds(self):
        for start,end,expected,fold in [({'date':'2026-09-01'},{'date':'2026-09-03'},'2026-09-01',0),
                ({'dateTime':'2026-11-01T01:30:00-05:00','timeZone':'America/New_York'},
                 {'dateTime':'2026-11-01T02:30:00-05:00'},'2026-11-01T01:30',1)]:
            self.items['master'].update(start=start,end=end)
            master=GoogleCalendarWriter(self.writer).master(self.reference('occurrence_20260922'),1)
            self.assertEqual(master['editor_event']['start'],expected);self.assertEqual(master['editor_event']['start_fold'],fold)
        self.items['master']['start']['timeZone']='Invalid/Zone'
        with self.assertRaisesRegex(ValueError,'unsupported time zone'):
            GoogleCalendarWriter(self.writer).master(self.reference('occurrence_20260922'),1)

    def test_unreviewed_master_following_attendees_and_malformed_events_deny(self):
        ref=self.reference('occurrence_20260922')
        for scope in ('series','following'):
            with self.assertRaises(ValueError):self.writer.change('edit',ref,self.event,1,'1'*32,'owner',scope=scope)
        for fields in ({'attendees':[{'email':'synthetic@example.com'}]},{'attendeesOmitted':True},
                       {'organizer':None},{'eventType':'birthday'},{'end':{}},{'recurrence':[{}]}):
            original=self.items['single'];ref=self.reference()
            self.items['single']={**original,**fields}
            self.assertFalse(editable_event(self.items['single']))
            with self.assertRaises(ValueError):self.writer.change('delete',ref,None,1,'1'*32,'owner')
            self.items['single']=original
        self.assertEqual(self.writes(),[])

    def test_stale_etag_before_and_during_dispatch_is_never_retried(self):
        ref=self.reference();self.items['single']['etag']='"changed"'
        with self.assertRaises(ExperienceConflict):self.writer.change('delete',ref,None,1,'1'*32,'owner')
        self.assertEqual(self.writes(),[]);self.failure='etag';ref=self.reference()
        for _ in range(2):self.assertEqual(self.writer.change('delete',ref,None,1,'1'*32,'owner')['status'],'rejected')
        self.assertEqual(len(self.writes()),1)

    def test_unknown_response_and_restart_do_not_repeat_any_operation(self):
        for index,operation in enumerate(('create','edit','delete')):
            with self.subTest(operation=operation):
                request_id=str(index+1)*32;self.failure='lost'
                def run(writer):
                    return writer.create(self.event,1,request_id,'owner') if operation=='create' else writer.change(operation,self.reference(),self.event if operation=='edit' else None,1,request_id,'owner')
                self.assertEqual(run(self.writer)['status'],'unconfirmed')
                loaded=CalendarWriter(self.exp,self.root,self.protector)
                self.assertEqual(run(loaded)['status'],'unconfirmed');self.assertEqual(len(self.writes()),index+1)

    def test_pending_receipt_and_parallel_retry_dispatch_only_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.writer.create(self.event,1,'1'*32,'owner'),range(2)))
        self.assertEqual([r['status'] for r in results],['accepted','accepted']);self.assertEqual(len(self.writes()),1)
        key=hashlib.sha256(('1'*32).encode()).hexdigest()
        self.writer.commit({key:{**self.writer.receipts[key],'status':'pending'}})
        loaded=CalendarWriter(self.exp,self.root,self.protector)
        self.assertEqual(loaded.create(self.event,1,'1'*32,'owner')['status'],'unconfirmed')
        with self.assertRaises(ExperienceConflict):loaded.create({**self.event,'title':'Different'},1,'1'*32,'owner')
        self.assertEqual(len(self.writes()),1)

    def test_account_grant_update_and_dispatch_follow_the_same_lock_order(self):
        member_lock=RLock();attempted=Event();finished=Event();results=[]
        class AccessLock:
            def __enter__(self):attempted.set();member_lock.acquire()
            def __exit__(self,*args):member_lock.release()
        def validate():
            with member_lock:pass
        def dispatch():
            try:results.append(self.writer.create(self.event,1,'1'*32,'owner',validate=validate,access_lock=AccessLock()))
            except Exception as error:results.append(error)
            finally:finished.set()
        with member_lock:
            worker=Thread(target=dispatch,daemon=True);worker.start()
            self.assertTrue(attempted.wait(2))
            # The calendar request must wait on member_lock without retaining
            # source.lock, which the simultaneous grant update needs next.
            acquired=self.exp.store.lock.acquire(timeout=2)
            try:self.assertTrue(acquired,'Calendar dispatch inverted member/source locks')
            finally:
                if acquired:self.exp.store.lock.release()
        self.assertTrue(finished.wait(3));worker.join(1)
        self.assertEqual(results[0]['status'],'accepted');self.assertEqual(len(self.writes()),1)

    def test_malformed_success_and_receipt_failure_remain_unconfirmed_without_retry(self):
        self.failure='malformed'
        self.assertEqual(self.writer.create(self.event,1,'1'*32,'owner')['status'],'unconfirmed')
        self.assertEqual(self.writer.create(self.event,1,'1'*32,'owner')['status'],'unconfirmed')
        self.assertEqual(len(self.writes()),1)
        original=self.writer.commit
        def commit(receipts):
            if any(r['status']!='pending' for k,r in receipts.items() if k!=hashlib.sha256(('1'*32).encode()).hexdigest()):
                raise ExperienceUnavailable('Synthetic receipt failure')
            original(receipts)
        self.failure=None
        with patch.object(self.writer,'commit',side_effect=commit):
            with self.assertRaises(ExperienceUnavailable):self.writer.create(self.event,1,'2'*32,'owner')
        loaded=CalendarWriter(self.exp,self.root,self.protector)
        self.assertEqual(loaded.create(self.event,1,'2'*32,'owner')['status'],'unconfirmed');self.assertEqual(len(self.writes()),2)


class GoogleWriteApiTests(WriteFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.app=create_app('x'*40);self.client=TestClient(self.app)
        self.owner={'Authorization':'Bearer '+'x'*40}
        google=self.app.state.google_calendars;google.transport=self.transport;google.configure(configuration())
        google.commit(google.config,self.google.accounts);self.google=google
        result=self.client.put('/v1/display/source-settings',headers=self.owner,json={'revision':0,'sources':{
            'calendars':[self.entity],'writable_calendars':[self.entity],'managed_calendars':[self.entity]}})
        self.assertEqual(result.status_code,200,result.text)
        self.displays=self.app.state.calling.displays
        self.paired=self.displays.enroll(self.displays.pairing('Synthetic display')['code'])
        self.display={'Authorization':'Display '+self.paired['credential']};self.calls.clear()

    def bodies(self):
        return {'events':{'revision':1,'request_id':'1'*32,'event':self.event},
                'change':{'revision':1,'request_id':'2'*32,'operation':'delete','reference':self.reference()},
                'master':{'revision':1,'reference':self.reference('occurrence_20260922')}}

    def test_guest_and_personal_deny_all_writes_and_master_review(self):
        profile={'mode':'guest','calendars':[self.entity]}
        self.displays.save_profile(self.paired['id'],profile,0)
        for endpoint,body in self.bodies().items():
            self.assertEqual(self.client.post('/v1/display/calendar/'+endpoint,headers=self.display,json=body).status_code,403)
        member=self.app.state.members.create('Synthetic member')
        self.displays.save_profile(self.paired['id'],{'members':[member['id']]},1)
        self.app.state.members.login('display:'+self.paired['id'],member['id'],member['passcode'])
        for endpoint,body in self.bodies().items():
            self.assertEqual(self.client.post('/v1/display/calendar/'+endpoint,headers=self.display,json=body).status_code,403)
        self.assertEqual(self.writes(),[])

    def test_session_revocation_during_read_prevents_dispatch_and_master_disclosure(self):
        for endpoint in ('events','master'):
            pair=self.displays.enroll(self.displays.pairing('Synthetic display')['code'])
            headers={'Authorization':'Display '+pair['credential']}
            self.interrupt=lambda method,url:self.displays.revoke(pair['id']) if '/calendarList/' in url else None
            response=self.client.post('/v1/display/calendar/'+endpoint,headers=headers,json=self.bodies()[endpoint])
            self.assertEqual(response.status_code,401,response.text);self.assertNotIn('Weekly studio',response.text)
        self.assertEqual(self.writes(),[])

    def test_revocation_after_dispatch_returns_retry_safe_error_and_receipt(self):
        self.interrupt=lambda method,url:self.displays.revoke(self.paired['id']) if method=='POST' and url.endswith('/events') else None
        body=self.bodies()['events']
        response=self.client.post('/v1/display/calendar/events',headers=self.display,json=body)
        self.assertEqual(response.status_code,503,response.text)
        self.interrupt=None
        response=self.client.post('/v1/display/calendar/events',headers=self.owner,json=body)
        self.assertEqual(response.json()['status'],'accepted');self.assertEqual(len(self.writes()),1)

    def test_master_api_returns_reviewed_original_fields_and_conditional_write(self):
        response=self.client.post('/v1/display/calendar/master',headers=self.display,json=self.bodies()['master'])
        self.assertEqual(response.status_code,200,response.text);master=response.json()
        self.assertEqual(master['editor_event']['start'],'2026-09-01T10:00')
        response=self.client.post('/v1/display/calendar/change',headers=self.display,json={
            'revision':1,'request_id':'3'*32,'operation':'edit','scope':'series',
            'reference':master['reference'],'event':master['editor_event']})
        self.assertEqual(response.json()['status'],'accepted');self.assertNotIn('recurrence',self.writes()[0][2]['json'])


class GoogleWriteTransportTests(unittest.TestCase):
    def test_412_is_definitive_and_only_204_confirms_deletion(self):
        real_client=httpx.Client
        for status,method,expected in ((412,'PATCH',GoogleRejected),(200,'DELETE',HomeUnavailable),(204,'PATCH',HomeUnavailable)):
            with self.subTest(status=status,method=method):
                transport=httpx.MockTransport(lambda request:httpx.Response(status,json={}))
                with patch('backend.google_calendar.httpx.Client',side_effect=lambda **kwargs:real_client(transport=transport,**kwargs)):
                    with self.assertRaises(expected):GoogleTransport().json(method,'https://www.googleapis.com/calendar/v3/calendars/example/events/event')
        with patch('backend.google_calendar.httpx.Client',side_effect=lambda **kwargs:real_client(transport=httpx.MockTransport(lambda request:httpx.Response(204)),**kwargs)):
            self.assertEqual(GoogleTransport().json('DELETE','https://www.googleapis.com/calendar/v3/calendars/example/events/event'),{})


if __name__=='__main__':unittest.main()
