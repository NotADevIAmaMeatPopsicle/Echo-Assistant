"""Explicit calendar creation with separate grants and durable at-most-once dispatch."""
import base64
from copy import deepcopy
from datetime import date,datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from typing import Literal
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from .experiences import ExperienceConflict,ExperienceUnavailable
from .home import HomeUnavailable


class CalendarEvent(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    calendar:str=Field(pattern=r'^calendar\.[a-z0-9_]{1,128}$')
    title:str=Field(min_length=1,max_length=200)
    description:str=Field(default='',max_length=2000)
    location:str=Field(default='',max_length=300)
    start:str=Field(max_length=30)
    end:str=Field(max_length=30)
    all_day:bool=False
    timezone:str=Field(min_length=1,max_length=80)
    start_fold:Literal[0,1]=0
    end_fold:Literal[0,1]=0

    @field_validator('title','description','location')
    @classmethod
    def readable(cls,value,info):
        value=value.strip()
        if any(ord(c)<32 and c not in '\n\t' for c in value) or info.field_name=='title' and not value:
            raise ValueError('Use readable text and a nonempty title')
        return value

    @model_validator(mode='after')
    def times(self):
        self.bounds();return self

    def bounds(self):
        try:zone=ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError,ValueError):raise ValueError('Choose an IANA time zone') from None
        if self.all_day:
            if not all(re.fullmatch(r'\d{4}-\d{2}-\d{2}',v) for v in (self.start,self.end)):raise ValueError('All-day events need dates')
            start,end=date.fromisoformat(self.start),date.fromisoformat(self.end)
            seconds=(end-start).total_seconds()
            values={'start_date':start.isoformat(),'end_date':end.isoformat()}
        else:
            def instant(value,fold):
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}',value):raise ValueError('Use local date and time, to the minute')
                naive=datetime.fromisoformat(value);aware=naive.replace(tzinfo=zone,fold=fold)
                if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=naive:
                    raise ValueError('This time does not exist because the clocks change. Choose another time.')
                return aware
            start,end=instant(self.start,self.start_fold),instant(self.end,self.end_fold)
            seconds=end.timestamp()-start.timestamp()
            values={'start_date_time':start.isoformat(),'end_date_time':end.isoformat()}
        if not 0<seconds<=366*86400:raise ValueError('End must follow start, within one year')
        return values

    def payload(self):
        return {'entity_id':self.calendar,'summary':self.title,'description':self.description,'location':self.location,**self.bounds()}


class CalendarWriter:
    def __init__(self,experiences,root,protector,enabled=True):
        self.experiences,self.protector,self.enabled=experiences,protector,enabled
        self.path=Path(root)/'local/echo-calendar-receipts.json' if root else None
        self.receipts={};self.error=False;self.lock=RLock()
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>4_000_000:raise ValueError()
                envelope=json.loads(self.path.read_text(encoding='utf-8'))
                if envelope['version']!=1:raise ValueError()
                saved=json.loads(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
                if not isinstance(saved,dict) or len(saved)>4096:raise ValueError()
                for key,value in saved.items():
                    if not re.fullmatch('[a-f0-9]{64}',key) or not re.fullmatch('[a-f0-9]{64}',value['digest']) or value['status'] not in {'pending','accepted','unconfirmed'}:raise ValueError()
                self.receipts=saved
            except (OSError,ValueError,TypeError,KeyError,RuntimeError):self.error=True

    def commit(self,receipts):
        if self.path:
            try:
                raw=self.protector.encrypt(json.dumps(receipts).encode());self.path.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(raw).decode()}),encoding='utf-8');temporary.replace(self.path)
            except (OSError,RuntimeError):raise ExperienceUnavailable('Calendar receipt could not be saved. Check the agenda before retrying.') from None
        self.receipts=receipts

    def create(self,event,revision,request_id,principal):
        if not self.enabled:raise PermissionError('Calendar creation is disabled on the validation host')
        if not re.fullmatch('[a-f0-9]{32}',request_id):raise ValueError('Invalid request identifier')
        event=CalendarEvent.model_validate(event);payload=event.payload()
        # The unguessable request ID survives browser reauthentication and API
        # restart. Session-scoped keys would dispatch a retry twice after login.
        key=hashlib.sha256(request_id.encode()).hexdigest()
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        with self.lock,self.experiences.store.lock:
            if self.error:raise ExperienceUnavailable('Calendar receipts are unreadable. Existing data is preserved; creation is paused.')
            policy=self.experiences.store.snapshot()
            if event.calendar not in policy['sources']['writable_calendars']:raise PermissionError('This calendar is not approved for event creation')
            prior=self.receipts.get(key)
            if prior:
                if prior['digest']!=digest:raise ExperienceConflict('This request identifier belongs to a different event')
                return self.result(prior['status'])
            if policy['revision']!=revision:raise ExperienceConflict('Calendar permissions changed. Reload before creating an event.')
            if len(self.receipts)>=4096:raise ExperienceUnavailable('Calendar receipt capacity reached. Archive receipts before creating more events.')
            home=self.experiences.home
            current=home._request('GET','/api/states/'+event.calendar)
            features=current.get('attributes',{}).get('supported_features',0)
            if current.get('state') in {None,'unknown','unavailable'} or type(features) is not int or not features&1:
                raise HomeUnavailable('This calendar is unavailable or does not support event creation')
            # Persist before dispatch. A crash or uncertain response never triggers
            # a retry of the same request, even after a process restart.
            receipt={'digest':digest,'status':'pending'}
            self.commit({**self.receipts,key:receipt})
            try:home._request('POST','/api/services/calendar/create_event',payload);status='accepted'
            except HomeUnavailable:status='unconfirmed'
            self.commit({**self.receipts,key:{**receipt,'status':status}})
            return self.result(status)

    @staticmethod
    def result(status):
        accepted=status=='accepted'
        return {'status':'accepted' if accepted else 'unconfirmed', 'capability':'calendar',
            'text':'Home Assistant accepted the event. Refresh the agenda to see it once the calendar syncs.' if accepted else
                   'The calendar request may have been sent, but completion is unconfirmed. Check your calendar before creating another event. This request will not be sent again.'}
