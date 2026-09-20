"""Calendar change checks against a synthetic Home Assistant, never a live calendar."""
from copy import deepcopy
import json
from unittest import TestCase
from unittest.mock import Mock,patch
from pydantic import ValidationError
import tests.test_daily_calendar as daily_checks
from backend.calendar_events import CalendarEvent,CalendarWriter,Recurrence
from backend.calendar_reference import event_version
from backend.calendar_transport import calendar_command
from backend.experiences import ExperienceConflict
from backend.home import HomeUnavailable


class CalendarChangesTests(TestCase):
    setUp=daily_checks.DailyCalendarTests.setUp
    grant=daily_checks.DailyCalendarTests.grant

    def managed(self):
        self.state['attributes']['supported_features']=7
        self.exp.save_sources({'calendars':['calendar.demo'],'writable_calendars':['calendar.demo'],'managed_calendars':['calendar.demo']},0)
        self.original={'uid':'event-1','summary':'Original','description':'Keep these notes','location':'Park',
            'start':{'dateTime':'2026-09-22T10:00:00-04:00'},'end':{'dateTime':'2026-09-22T11:00:00-04:00'}}
        original_request=self.home._request
        self.home._request=lambda method,path,body=None: [deepcopy(self.original)] if path.startswith('/api/calendars/') else ({'time_zone':'America/New_York'} if path=='/api/config' else original_request(method,path,body))
        self.ref={'calendar':'calendar.demo','uid':'event-1','on_date':'2026-09-22','version':event_version(self.original)}
        self.writer.command=Mock(return_value='accepted')

    def test_edit_rechecks_event_and_survives_restart_without_duplicate(self):
        self.managed();result=self.writer.change('edit',self.ref,self.event,1,'c'*32,'display:example')
        self.assertEqual(result['status'],'accepted');body=self.writer.command.call_args.args[0]
        self.assertEqual(body['type'],'calendar/event/update');self.assertEqual(body['uid'],'event-1')
        self.assertEqual(body['event']['start'],'2026-09-22T10:00:00-04:00')
        command=Mock();reloaded=CalendarWriter(self.exp,self.root,self.protector,command=command)
        self.assertEqual(reloaded.change('edit',self.ref,self.event,1,'c'*32,'new-session')['status'],'accepted');command.assert_not_called()
        with self.assertRaises(ExperienceConflict):reloaded.change('delete',self.ref,None,1,'c'*32,'new-session')

    def test_stale_series_and_missing_grants_never_dispatch(self):
        self.managed();self.original['summary']='Changed elsewhere'
        with self.assertRaises(ExperienceConflict):self.writer.change('delete',self.ref,None,1,'d'*32,'display:example')
        self.original['summary']='Original';self.original['rrule']='FREQ=DAILY'
        with self.assertRaises(ExperienceConflict):self.writer.change('edit',self.ref,self.event,1,'d'*32,'display:example')
        self.sources.save({'calendars':['calendar.demo'],'writable_calendars':['calendar.demo']},1)
        with self.assertRaises(PermissionError):self.writer.change('delete',self.ref,None,2,'d'*32,'display:example')
        self.writer.command.assert_not_called()

    def test_delete_uncertain_response_is_not_repeated_and_capability_is_live(self):
        self.managed();self.state['attributes']['supported_features']=1
        with self.assertRaises(HomeUnavailable):self.writer.change('delete',self.ref,None,1,'d'*32,'display:example')
        self.writer.command.assert_not_called();self.state['attributes']['supported_features']=7
        self.writer.command.side_effect=HomeUnavailable('Synthetic lost response')
        for _ in range(2):self.assertEqual(self.writer.change('delete',self.ref,None,1,'d'*32,'display:example')['status'],'unconfirmed')
        self.assertEqual(self.writer.command.call_count,1)

    def test_recurrence_uses_websocket_and_bounded_rule(self):
        self.managed();event={**self.event,'recurrence':{'frequency':'weekly','interval':2,'count':12}}
        self.assertEqual(self.writer.create(event,1,'e'*32,'display:example')['status'],'accepted')
        self.assertEqual(self.writer.command.call_args.args[0]['event']['rrule'],'FREQ=WEEKLY;INTERVAL=2;COUNT=12')
        self.assertEqual(self.writer.create(event,1,'e'*32,'display:example')['status'],'accepted');self.assertEqual(self.writer.command.call_count,1)
        with self.assertRaises(ValueError):self.writer.create({**event,'timezone':'UTC'},1,'f'*32,'display:example')
        with self.assertRaises(ValidationError):Recurrence(frequency='weekly',count=0)
        with self.assertRaises(ValidationError):Recurrence(frequency='secondly',count=100)
        self.writer.command.return_value='rejected'
        self.assertEqual(self.writer.create({**event,'all_day':True,'start':'2026-09-22','end':'2026-09-23'},1,'f'*32,'display:example')['status'],'rejected')
        self.assertFalse(CalendarWriter(self.exp,self.root,self.protector).error)

    def test_agenda_identity_and_grants_are_scoped(self):
        self.managed();result=self.exp.agenda('2026-09-22')['events'][0]
        self.assertEqual(result['reference'],self.ref);self.assertEqual(result['description'],'Keep these notes')
        source=self.exp.sources()['items'][0];self.assertTrue(source['editable']);self.assertTrue(source['deletable'])
        self.original['recurrence_id']='20260922T140000Z'
        recurring=self.exp.agenda('2026-09-22')['events'][0]
        self.assertEqual(recurring['reference']['recurrence_id'],'20260922T140000Z')
        self.assertEqual(recurring['change_scopes']['edit'],['occurrence','following'])
        self.assertTrue(self.exp.agenda('2026-09-22')['events'][0]['recurring'])

    def test_websocket_auth_and_no_retries_or_private_errors(self):
        self.managed();ws=Mock();ws.recv.side_effect=[json.dumps({'type':'auth_required'}),json.dumps({'type':'auth_ok'}),json.dumps({'type':'result','id':1,'success':True})]
        with patch('websockets.sync.client.connect') as connect:
            connect.return_value.__enter__.return_value=ws
            self.assertEqual(calendar_command(self.home.config,{'type':'calendar/event/delete','entity_id':'calendar.demo','uid':'synthetic'}),'accepted')
            self.assertIsNone(connect.call_args.kwargs['proxy']);self.assertEqual(ws.send.call_count,2)
            self.assertNotIn('token',connect.call_args.args[0])
        ws.reset_mock();ws.recv.side_effect=RuntimeError('private-token-in-server-error')
        with patch('websockets.sync.client.connect') as connect:
            connect.return_value.__enter__.return_value=ws
            with self.assertRaises(HomeUnavailable) as error:calendar_command(self.home.config,{'type':'calendar/event/delete'})
            self.assertNotIn('private-token',str(error.exception));connect.assert_called_once();ws.send.assert_not_called()

    def test_paired_api_requires_separate_management_grant_and_guest_denies_it(self):
        from fastapi.testclient import TestClient
        from backend.app import create_app
        from backend.settings import SettingsStore
        self.managed()
        with TestClient(create_app('o'*40,home=self.home,settings_store=SettingsStore(protector=self.protector))) as client:
            owner={'Authorization':'Bearer '+'o'*40}
            code=client.post('/v1/displays/pairing',headers=owner,json={'name':'Synthetic display'}).json()['code']
            paired=client.post('/v1/displays/enroll',json={'code':code}).json()
            display={'Authorization':'Display '+paired['credential']}
            selected={'calendars':['calendar.demo'],'writable_calendars':['calendar.demo']}
            self.assertEqual(client.put('/v1/display/source-settings',headers=owner,json={'revision':0,'sources':selected}).status_code,200)
            body={'operation':'delete','reference':self.ref,'revision':1,'request_id':'1'*32}
            self.assertEqual(client.post('/v1/display/calendar/change',headers=display,json=body).status_code,403)
            selected['managed_calendars']=['calendar.demo']
            self.assertEqual(client.put('/v1/display/source-settings',headers=owner,json={'revision':1,'sources':selected}).status_code,200)
            body['revision']=2
            with patch('backend.calendar_events.calendar_command',return_value='accepted') as command:
                response=client.post('/v1/display/calendar/change',headers=display,json=body)
                self.assertEqual(response.status_code,200,response.text);command.assert_called_once()
            self.assertEqual(client.put('/v1/displays/'+paired['id']+'/profile',headers=owner,json={'revision':0,'profile':{'mode':'guest'}}).status_code,200)
            self.assertEqual(client.post('/v1/display/calendar/change',headers=display,json=body).status_code,403)
