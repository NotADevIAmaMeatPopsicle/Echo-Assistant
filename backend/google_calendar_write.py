"""Reviewed Google event writes with conditional updates and durable receipts."""
from datetime import datetime
from contextlib import nullcontext
import hashlib
import json
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from fastapi import HTTPException

from .calendar_reference import event_reference, event_version, change_scopes
from .experiences import ExperienceConflict, ExperienceUnavailable, temporal
from .home import HomeUnavailable
from .google_calendar import GoogleRejected


def editable_event(item):
    # Invitations and special Google event types require a separate review UI.
    if not isinstance(item,dict):return False
    try:
        _,all_day,start=temporal(item['start']);_,end_day,end=temporal(item['end'])
        if all_day!=end_day or end<=start:return False
    except (KeyError,ValueError,TypeError,AttributeError):return False
    return (isinstance(item,dict) and isinstance(item.get('id'),str)
            and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,512}',item['id']))
            and isinstance(item.get('etag'),str) and 0<len(item['etag'])<=512
            and not any(ord(c)<32 or ord(c)>126 for c in item['etag'])
            and item.get('status')!='cancelled' and item.get('eventType','default')=='default'
            and not item.get('attendees') and not item.get('attendeesOmitted') and not item.get('locked')
            and isinstance(item.get('organizer',{}),dict)
            and item.get('organizer',{}).get('self',True) is True
            and (not item.get('recurringEventId') or isinstance(item['recurringEventId'],str)
                 and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,512}',item['recurringEventId'])))
            and (not item.get('recurrence') or isinstance(item['recurrence'],list)
                 and all(isinstance(rule,str) and len(rule)<=2000 for rule in item['recurrence'])))


class GoogleCalendarWriter:
    def __init__(self,writer,validate=None,access_lock=None):
        self.writer=writer;self.google=writer.experiences.google;self.validate=validate or (lambda:None)
        # Account grant updates take the member lock before the source lock.
        # Keep that order when a request reauthorizes inside these operations.
        self.access_lock=access_lock or nullcontext()

    def policy(self,entity,revision,create=False):
        self.validate()
        if not self.writer.enabled:raise PermissionError('Calendar changes are disabled on the validation host')
        if not self.google or not self.google.enabled or not self.google.owns(entity):
            raise PermissionError('Direct Google calendar changes are unavailable')
        if self.writer.error:raise ExperienceUnavailable('Calendar receipts are unreadable. Changes are paused.')
        policy=self.writer.experiences.store.snapshot()
        if entity not in policy['sources']['writable_calendars' if create else 'managed_calendars']:
            raise PermissionError('The owner has not approved these calendar changes')
        if policy['revision']!=revision:raise ExperienceConflict('Calendar permissions changed. Reload before making a change.')
        self.google.require()
        found=next(((a,c) for a in self.google.accounts for c in a['calendars'] if c['entity_id']==entity),None)
        if not found or not found[0].get('write_access',False):raise PermissionError('Reconnect this Google account with calendar editing enabled')
        return found

    def provider(self,account,calendar):
        current=self.google.get(account['id'],'users/me/calendarList/'+quote(calendar['id'],safe=''))
        if current.get('accessRole') not in {'writer','owner'} or current.get('deleted'):
            raise PermissionError('Google no longer permits changes to this calendar')

    @staticmethod
    def path(calendar,uid=None):
        if uid is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,512}',uid):raise ValueError('Invalid Google event identifier')
        return 'calendars/'+quote(calendar['id'],safe='')+'/events'+('/'+quote(uid,safe='') if uid else '')

    def current(self,account,calendar,reference):
        item=self.google.get(account['id'],self.path(calendar,reference.uid))
        if not editable_event(item):raise ValueError('This event needs the Google Calendar editor, including any guest or special-event controls')
        row=self.google.event_row(item)
        if item['id']!=reference.uid or event_version(row)!=reference.version or (row.get('recurrence_id') or None)!=reference.recurrence_id:
            raise ExperienceConflict('The event changed elsewhere. Refresh the agenda and review it again.')
        return item

    @staticmethod
    def fields(event):
        bounds=event.bounds()
        result={'summary':event.title,'description':event.description,'location':event.location}
        for field in ('start','end'):
            result[field]=({'date':bounds[field+'_date']} if event.all_day else
                           {'dateTime':bounds[field+'_date_time'],'timeZone':event.timezone})
        return result

    def master(self,reference,revision):
        from .calendar_events import EventReference
        reference=EventReference.model_validate(reference)
        if not self.google or not self.google.owns(reference.calendar):raise ValueError('Direct series review is available for Google calendars')
        with self.access_lock,self.writer.lock,self.writer.experiences.store.lock,self.google.lock:
            account,calendar=self.policy(reference.calendar,revision);self.provider(account,calendar)
            selected=self.current(account,calendar,reference)
            item=(self.google.get(account['id'],self.path(calendar,selected['recurringEventId']))
                  if selected.get('recurringEventId') else selected)
            if (not editable_event(item) or not item.get('recurrence') or item.get('recurringEventId')
                or item['id']!=(selected.get('recurringEventId') or selected['id'])):
                raise ValueError('This series cannot be edited here. Use Google Calendar.')
            zone=item.get('start',{}).get('timeZone') or calendar['timezone']
            try:zone_info=ZoneInfo(zone)
            except (ZoneInfoNotFoundError,ValueError,TypeError):raise ValueError('This series has an unsupported time zone. Edit it in Google Calendar.') from None
            all_day='date' in item.get('start',{});fields={}
            for name in ('start','end'):
                if all_day:fields[name]=item[name]['date'];fields[name+'_fold']=0
                else:
                    when=datetime.fromisoformat(item[name]['dateTime'].replace('Z','+00:00')).astimezone(zone_info)
                    if when.second or when.microsecond:raise ValueError('This series uses sub-minute times. Edit it in Google Calendar.')
                    fields[name]=when.strftime('%Y-%m-%dT%H:%M');fields[name+'_fold']=when.fold
            editor={'calendar':reference.calendar,'title':item.get('summary','Untitled event'),
                    'description':item.get('description',''),'location':item.get('location',''),
                    'all_day':all_day,'timezone':zone,**fields}
            from .calendar_events import CalendarEvent
            CalendarEvent.model_validate(editor)
            row=self.google.event_row(item)
            self.policy(reference.calendar,revision)
            return {'reference':event_reference(row,reference.calendar,fields['start'][:10]),'editor_event':editor,
                    'repeat_summary':'; '.join(item['recurrence']), 'provider':'google'}

    def run(self,entity,revision,request_id,intent,prepare,create=False):
        if not re.fullmatch('[a-f0-9]{32}',request_id):raise ValueError('Invalid request identifier')
        key=hashlib.sha256(request_id.encode()).hexdigest()
        digest=hashlib.sha256(json.dumps({'provider':'google',**intent},sort_keys=True).encode()).hexdigest()
        with self.access_lock,self.writer.lock,self.writer.experiences.store.lock,self.google.lock:
            account,calendar=self.policy(entity,revision,create)
            prior=self.writer.receipts.get(key)
            if prior:
                if prior['digest']!=digest:raise ExperienceConflict('This request identifier belongs to another calendar change')
                return self.result(prior['status'])
            if len(self.writer.receipts)>=4096:raise ExperienceUnavailable('Calendar receipt capacity reached')
            self.provider(account,calendar)
            method,path,payload,etag=prepare(account,calendar)
            token,_=self.google.token(account['id'])
            self.policy(entity,revision,create)
            receipt={'digest':digest,'status':'pending'}
            self.writer.commit({**self.writer.receipts,key:receipt})
            try:
                options={'headers':{'Authorization':'Bearer '+token,**({'If-Match':etag} if etag else {})},
                         'params':{'sendUpdates':'none'}}
                if payload is not None:options['json']=payload
                result=self.google.transport.json(method,'https://www.googleapis.com/calendar/v3/'+path,**options)
                if method!='DELETE':
                    expected=payload['id'] if method=='POST' else path.rsplit('/',1)[1]
                    if not editable_event(result) or result['id']!=expected:
                        raise HomeUnavailable('Google returned an unexpected event. Check the calendar before retrying.')
                status='accepted'
            except GoogleRejected:status='rejected'
            except HomeUnavailable:status='unconfirmed'
            self.writer.commit({**self.writer.receipts,key:{**receipt,'status':status}})
            try:self.policy(entity,revision,create)
            except (HTTPException,PermissionError,ExperienceConflict,HomeUnavailable):
                # Dispatch already happened. A permission change must not invite
                # the browser to invent a new request ID and repeat the write.
                raise ExperienceUnavailable('Calendar access changed during the request. Check the calendar; any retry must use the same request identifier.') from None
            return self.result(status)

    @staticmethod
    def result(status):
        return {'status':status if status in {'accepted','rejected'} else 'unconfirmed','capability':'calendar',
                'text':('Google accepted the change. Refresh the agenda to see it.' if status=='accepted' else
                        'Google rejected the change. Refresh the agenda and review the current event and permissions.' if status=='rejected' else
                        'Completion is unconfirmed. Check Google Calendar before making another change. This request will not be sent again.')}

    def create(self,event,revision,request_id):
        from .calendar_events import CalendarEvent
        event=CalendarEvent.model_validate(event)
        payload=self.fields(event)
        # Deterministic provider ID also prevents duplicate inserts after an
        # uncertain response. Only a new, explicitly reviewed request gets a new ID.
        payload['id']='echo'+hashlib.sha256(request_id.encode()).hexdigest()
        if event.recurrence:payload['recurrence']=['RRULE:'+event.recurrence.rule()]
        return self.run(event.calendar,revision,request_id,{'operation':'create','event':event.model_dump()},
                        lambda a,c:('POST',self.path(c),payload,None),create=True)

    def change(self,operation,reference,event,revision,request_id,scope):
        from .calendar_events import CalendarEvent,EventReference
        if scope=='following':
            from .google_calendar_series import change_following
            return change_following(self,operation,reference,event,revision,request_id)
        reference=EventReference.model_validate(reference)
        if operation not in {'edit','delete'} or scope not in {'single','occurrence','series'}:
            raise ValueError('Choose a supported calendar change scope')
        if reference.following_version is not None:raise ValueError('A following-series review does not apply to this change scope')
        replacement=CalendarEvent.model_validate(event) if operation=='edit' else None
        if replacement and (replacement.calendar!=reference.calendar or replacement.recurrence):
            raise ValueError('Keep the calendar and existing recurrence pattern')
        if operation=='delete' and event is not None:raise ValueError('Deletion does not accept replacement fields')
        def prepare(account,calendar):
            item=self.current(account,calendar,reference)
            if scope not in change_scopes(self.google.event_row(item))[operation]:raise ExperienceConflict('This scope is no longer available')
            if scope=='series' and item.get('recurringEventId'):
                if operation=='edit':raise ValueError('Load and review the original series before editing all occurrences')
                item=self.google.get(account['id'],self.path(calendar,item['recurringEventId']))
                if (not editable_event(item) or not item.get('recurrence') or item.get('recurringEventId')
                    or item['id']!=reference.recurrence_id):raise ExperienceConflict('The series changed. Review it in Google Calendar.')
            if replacement:
                if any(len(str(item.get(k) or ''))>limit for k,limit in (('summary',200),('description',2000),('location',300))):
                    raise ValueError('Edit this event in Google Calendar to retain its longer fields')
                if scope=='series':
                    if len(item['recurrence'])!=1 or not item['recurrence'][0].startswith('RRULE:'):
                        raise ValueError('This series has additional recurrence dates. Edit it in Google Calendar.')
                    if replacement.all_day!=('date' in item['start']):raise ValueError('Keep the series all-day setting')
                payload=self.fields(replacement)
                # PATCH intentionally omits recurrence, attendees, reminders,
                # attachments and provider metadata. COUNT remains unchanged.
                return 'PATCH',self.path(calendar,item['id']),payload,item['etag']
            return 'DELETE',self.path(calendar,item['id']),None,item['etag']
        # Preserve receipts written before following-review references existed,
        # including the original recurrence_id:null field in single-event digests.
        return self.run(reference.calendar,revision,request_id,{'operation':operation,'reference':reference.model_dump(exclude={'following_version'}),
                        'event':replacement.model_dump() if replacement else None,'scope':scope},prepare)
