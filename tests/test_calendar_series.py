"""Occurrence selection and write boundaries against synthetic calendar data."""
from copy import deepcopy
import hashlib
import json
from unittest import TestCase
from unittest.mock import Mock

from pydantic import ValidationError
from backend.calendar_events import CalendarEvent,CalendarWriter,EventReference
from backend.calendar_reference import event_reference,change_scopes
from backend.experiences import ExperienceConflict
from backend.home import HomeUnavailable
import tests.test_calendar_changes as changes


class CalendarSeriesTests(TestCase):
    setUp=changes.CalendarChangesTests.setUp
    managed=changes.CalendarChangesTests.managed

    def series(self,*,all_day=False):
        self.managed()
        self.original.update(rrule='FREQ=WEEKLY;COUNT=12;BYDAY=TU',recurrence_id='opaque-provider-instance')
        if all_day:self.original.update(start={'date':'2026-09-22'},end={'date':'2026-09-23'})
        self.ref=event_reference(self.original,'calendar.demo','2026-09-22')

    def test_occurrence_is_exact_and_does_not_replace_repeat_pattern(self):
        self.series();self.writer.change('edit',self.ref,self.event,1,'a'*32,'owner',scope='occurrence')
        command=self.writer.command.call_args.args[0]
        self.assertEqual(command['recurrence_id'],'opaque-provider-instance')
        self.assertNotIn('recurrence_range',command);self.assertNotIn('rrule',command['event'])
        self.assertEqual(command['uid'],'event-1')

    def test_following_scope_and_time_zone_are_explicit(self):
        self.series()
        with self.assertRaises(ValueError):self.writer.change('edit',self.ref,{**self.event,'timezone':'UTC'},1,'a'*32,'owner',scope='following')
        self.writer.command.assert_not_called()
        response=self.writer.change('edit',self.ref,self.event,1,'a'*32,'owner',scope='following')
        self.assertIn('selected and following',response['text'])
        self.assertEqual(self.writer.command.call_args.args[0]['recurrence_range'],'THISANDFUTURE')
        self.assertNotIn('rrule',self.writer.command.call_args.args[0]['event'])

    def test_delete_series_omits_occurrence_but_rechecks_selected_version(self):
        self.series();self.original['summary']='Changed'
        with self.assertRaises(ExperienceConflict):self.writer.change('delete',self.ref,None,1,'b'*32,'owner',scope='series')
        self.writer.command.assert_not_called();self.original['summary']='Original'
        result=self.writer.change('delete',self.ref,None,1,'b'*32,'owner',scope='series')
        self.assertIn('entire series',result['text'])
        self.assertEqual(self.writer.command.call_args.args[0],{'type':'calendar/event/delete','entity_id':'calendar.demo','uid':'event-1'})
        with self.assertRaises(ExperienceConflict):self.writer.change('delete',self.ref,None,1,'b'*32,'owner',scope='following')

    def test_repeated_uid_only_targets_matching_occurrence_and_rejects_duplicates(self):
        self.series();other=deepcopy(self.original);other['recurrence_id']='other-occurrence'
        request=self.home._request
        rows=[other,deepcopy(self.original)]
        self.home._request=lambda method,path,body=None:deepcopy(rows) if path.startswith('/api/calendars/') else request(method,path,body)
        self.writer.change('delete',self.ref,None,1,'c'*32,'owner',scope='occurrence')
        self.assertEqual(self.writer.command.call_args.args[0]['recurrence_id'],self.ref['recurrence_id'])
        rows.append(deepcopy(self.original))
        with self.assertRaises(ExperienceConflict):self.writer.change('delete',self.ref,None,1,'d'*32,'owner',scope='occurrence')
        self.assertEqual(self.writer.command.call_count,1)

    def test_no_scope_guess_no_fabricated_occurrence_no_rule_rewrite(self):
        self.series()
        with self.assertRaises(ValueError):self.writer.change('edit',self.ref,self.event,1,'a'*32,'owner')
        with self.assertRaises(ValueError):self.writer.change('edit',self.ref,self.event,1,'a'*32,'owner',scope='series')
        with self.assertRaises(ValueError):self.writer.change('edit',self.ref,{**self.event,'recurrence':{'frequency':'daily'}},1,'a'*32,'owner',scope='following')
        without={k:v for k,v in self.ref.items() if k!='recurrence_id'}
        with self.assertRaises(ValueError):self.writer.change('delete',without,None,1,'a'*32,'owner',scope='occurrence')
        self.original.pop('recurrence_id')
        self.assertEqual(change_scopes(self.original),{'edit':[],'delete':['series']})
        with self.assertRaises(ValidationError):EventReference.model_validate({**self.ref,'recurrence_id':'invalid\ncommand'})
        self.writer.command.assert_not_called()

    def test_all_day_opaque_ids_and_uncertain_retry_survive_restart(self):
        self.series(all_day=True);self.writer.command.side_effect=HomeUnavailable('lost reply')
        value=self.writer.change('delete',self.ref,None,1,'f'*32,'owner',scope='following')
        self.assertEqual(value['status'],'unconfirmed')
        command=Mock();again=CalendarWriter(self.exp,self.root,self.protector,command=command)
        self.assertEqual(again.change('delete',self.ref,None,1,'f'*32,'owner',scope='following')['status'],'unconfirmed')
        command.assert_not_called()

    def test_old_single_event_receipt_still_deduplicates(self):
        self.managed();event=CalendarEvent.model_validate(self.event)
        payload={'type':'calendar/event/update','entity_id':'calendar.demo','uid':'event-1','event':event.websocket_event()}
        digest=hashlib.sha256(json.dumps({'command':payload,'reference':self.ref},sort_keys=True).encode()).hexdigest()
        self.writer.commit({hashlib.sha256(('a'*32).encode()).hexdigest():{'digest':digest,'status':'accepted'}})
        self.assertEqual(self.writer.change('edit',self.ref,self.event,1,'a'*32,'owner')['status'],'accepted')
        self.writer.command.assert_not_called()

    def test_creation_permission_does_not_grant_series_changes(self):
        self.series();self.sources.save({'calendars':['calendar.demo'],'writable_calendars':['calendar.demo']},1)
        with self.assertRaises(PermissionError):self.writer.change('delete',self.ref,None,2,'a'*32,'owner',scope='series')
        self.writer.command.assert_not_called()

    def test_counted_or_unknown_series_preserves_start_and_all_day_type(self):
        self.series()
        moved={**self.event,'start':'2026-09-22T12:00','end':'2026-09-22T13:00'}
        for rule in ('FREQ=WEEKLY;COUNT=12;BYDAY=TU',None,''):
            self.original['rrule']=rule
            self.ref=event_reference(self.original,'calendar.demo','2026-09-22')
            with self.assertRaisesRegex(ValueError,'remaining occurrences'):
                self.writer.change('edit',self.ref,moved,1,'9'*32,'owner',scope='following')
        with self.assertRaisesRegex(ValueError,'all-day setting'):
            self.writer.change('edit',self.ref,{**self.event,'all_day':True,'start':'2026-09-22','end':'2026-09-23'},1,'9'*32,'owner',scope='following')
        self.writer.command.assert_not_called()
        self.assertEqual(self.writer.receipts,{})
        self.writer.change('edit',self.ref,{**self.event,'title':'Longer meeting','end':'2026-09-22T12:00'},1,'9'*32,'owner',scope='following')
        self.assertEqual(self.writer.command.call_args.args[0]['event']['end'],'2026-09-22T12:00:00-04:00')

    def test_single_occurrence_can_move_but_all_day_counted_following_cannot(self):
        self.series(all_day=True)
        moved={**self.event,'all_day':True,'start':'2026-09-23','end':'2026-09-24'}
        with self.assertRaisesRegex(ValueError,'remaining occurrences'):
            self.writer.change('edit',self.ref,moved,1,'8'*32,'owner',scope='following')
        self.writer.change('edit',self.ref,moved,1,'8'*32,'owner',scope='occurrence')
        self.assertNotIn('recurrence_range',self.writer.command.call_args.args[0])

    def test_unbounded_series_can_move_following_start(self):
        self.series();self.original['rrule']='FREQ=WEEKLY;BYDAY=TU'
        self.ref=event_reference(self.original,'calendar.demo','2026-09-22')
        self.writer.change('edit',self.ref,{**self.event,'start':'2026-09-22T12:00','end':'2026-09-22T13:00'},1,'7'*32,'owner',scope='following')
        self.assertEqual(self.writer.command.call_args.args[0]['event']['start'],'2026-09-22T12:00:00-04:00')
