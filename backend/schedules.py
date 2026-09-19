"""Encrypted wall-clock schedules and durable notification delivery receipts."""
import base64
from copy import deepcopy
from datetime import date, datetime, time as daytime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from threading import RLock
import time
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UTC = timezone.utc


class ScheduleUnavailable(RuntimeError): pass
class ScheduleConflict(ValueError): pass


class ScheduleSpec(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    title: str = Field(min_length=1,max_length=80)
    kind: Literal['alarm','reminder'] = 'alarm'
    message: str = Field(default='',max_length=400)
    time: str = Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    timezone: str = Field(min_length=1,max_length=80)
    weekdays: list[int] = Field(default_factory=list,max_length=7)
    local_date: str | None = None
    enabled: bool = True

    @field_validator('title','message')
    @classmethod
    def text(cls,value):
        if any(ord(c)<32 for c in value): raise ValueError('Use plain text')
        return value.strip()

    @field_validator('timezone')
    @classmethod
    def zone(cls,value):
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError): raise ValueError('Choose an IANA time zone') from None
        return value

    @field_validator('weekdays')
    @classmethod
    def days(cls,value):
        if any(type(day) is not int or not 0<=day<=6 for day in value) or len(set(value))!=len(value):
            raise ValueError('Choose distinct weekdays, Monday=0 through Sunday=6')
        return sorted(value)

    @model_validator(mode='after')
    def occurrence(self):
        if not self.title: raise ValueError('Enter a title')
        if bool(self.weekdays) == bool(self.local_date): raise ValueError('Choose either repeat weekdays or a one-off date')
        if self.local_date:
            if date.fromisoformat(self.local_date).isoformat()!=self.local_date: raise ValueError('Use YYYY-MM-DD')
        return self


class QuietHours(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    enabled: bool = False
    timezone: str = 'UTC'
    start: str = Field(default='22:00',pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    end: str = Field(default='07:00',pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    alarms_override: bool = True

    @field_validator('timezone')
    @classmethod
    def zone(cls,value): return ScheduleSpec.zone(value)


def resolve_wall(day, clock, zone):
    """Spring gap: first valid minute. Autumn fold: first occurrence only."""
    naive=datetime.combine(day,daytime.fromisoformat(clock))
    for minute in range(181):
        wall=naive+timedelta(minutes=minute)
        candidate=wall.replace(tzinfo=zone,fold=0)
        if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None)==wall:
            return candidate.timestamp()
    raise ValueError('This local time does not exist')


def next_occurrence(spec, after):
    zone=ZoneInfo(spec['timezone'])
    if spec['local_date']:
        stamp=resolve_wall(date.fromisoformat(spec['local_date']),spec['time'],zone)
        return stamp if stamp>after else None
    today=datetime.fromtimestamp(after,zone).date()
    for offset in range(8):
        day=today+timedelta(days=offset)
        if day.weekday() in spec['weekdays']:
            stamp=resolve_wall(day,spec['time'],zone)
            if stamp>after: return stamp
    return None


class ScheduleStore:
    def __init__(self,root,protector,clock=time.time):
        self.path=Path(root)/'local/echo-schedules.json' if root else None
        self.protector,self.clock,self.lock=protector,clock,RLock()
        self.state={'version':1,'revision':0,'items':[],'events':[],'quiet':QuietHours().model_dump()}
        self.error=False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>1_500_000: raise ValueError()
                envelope=json.loads(self.path.read_text(encoding='utf-8'))
                if envelope['version']!=1: raise ValueError()
                saved=json.loads(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
                self.validate_saved(saved); self.state=saved
            except (ValueError,TypeError,KeyError,RuntimeError,OSError): self.error=True

    @staticmethod
    def validate_saved(saved):
        import math,re
        if set(saved)!={'version','revision','items','events','quiet'} or saved['version']!=1: raise ValueError()
        if type(saved['revision']) is not int or saved['revision']<0: raise ValueError()
        QuietHours.model_validate(saved['quiet'])
        if len(saved['items'])>64 or len(saved['events'])>128: raise ValueError()
        ids=set()
        for item in saved['items']:
            if not re.fullmatch('[a-f0-9]{32}',item['id']) or item['id'] in ids: raise ValueError()
            ids.add(item['id'])
            spec={k:v for k,v in item.items() if k not in {'id','next_at'}}
            ScheduleSpec.model_validate(spec)
            if item['next_at'] is not None and (type(item['next_at']) not in (int,float) or not math.isfinite(item['next_at'])): raise ValueError()
        ids=set()
        for e in saved['events']:
            if set(e)!={'id','schedule_id','title','message','kind','due_at','status','delivered'}: raise ValueError()
            if not re.fullmatch('[a-f0-9]{32}',e['id']) or e['id'] in ids: raise ValueError()
            ids.add(e['id'])
            if e['status'] not in {'due','snoozed','dismissed','missed','info'} or e['kind'] not in {'alarm','reminder'} or type(e['delivered']) is not bool: raise ValueError()
            if type(e['due_at']) not in (int,float) or not math.isfinite(e['due_at']): raise ValueError()
            if not isinstance(e['title'],str) or not 1<=len(e['title'])<=80 or not isinstance(e['message'],str) or len(e['message'])>400: raise ValueError()

    def require(self):
        if self.error: raise ScheduleUnavailable('Saved schedules are unreadable. The existing file is preserved.')

    def commit(self,draft):
        self.validate_saved(draft)
        if self.path:
            try:
                raw=self.protector.encrypt(json.dumps(draft,ensure_ascii=False).encode())
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(raw).decode()}),encoding='utf-8')
                temporary.replace(self.path)
            except (OSError,RuntimeError): raise ScheduleUnavailable('Schedule change could not be saved; previous state is unchanged.') from None
        self.state=draft

    def tick(self):
        with self.lock:
            self.require(); now=self.clock(); draft=deepcopy(self.state)
            for item in draft['items']:
                if not item['enabled'] or item['next_at'] is None or item['next_at']>now: continue
                stamp=item['next_at']; identifier=hashlib.sha256(f'{item["id"]}:{stamp}'.encode()).hexdigest()[:32]
                if not any(e['id']==identifier for e in draft['events']):
                    draft['events'].append({'id':identifier,'schedule_id':item['id'],'title':item['title'],'message':item['message'],
                        'kind':item['kind'],'due_at':stamp,'status':'due' if now-stamp<=900 else 'missed','delivered':False})
                item['next_at']=next_occurrence(item,now)
                if item['next_at'] is None: item['enabled']=False
            for event in draft['events']:
                if event['status']=='snoozed' and event['due_at']<=now: event['status']='due'
                if event['status']=='due' and not event['delivered'] and now-event['due_at']>900: event['status']='missed'
            # Keep active events preferentially, with a bounded notification history.
            if len(draft['events'])>128:
                active=[e for e in draft['events'] if e['status'] in {'due','snoozed'}]
                history=[e for e in draft['events'] if e['status'] not in {'due','snoozed'}]
                draft['events']=(history[-max(0,128-len(active)):] if len(active)<128 else [])+active[-128:]
            if draft!=self.state: self.commit(draft)

    def quiet_now(self,now=None):
        quiet=self.state['quiet']
        if not quiet['enabled']: return False
        clock=datetime.fromtimestamp(self.clock() if now is None else now,ZoneInfo(quiet['timezone'])).strftime('%H:%M')
        start,end=quiet['start'],quiet['end']
        return start<=clock<end if start<end else clock>=start or clock<end

    def snapshot(self):
        self.tick()
        with self.lock:
            return {**deepcopy(self.state),'quiet_active':self.quiet_now(),'server_time':self.clock()}

    def save(self,spec,revision,identifier=None):
        spec=ScheduleSpec.model_validate(spec).model_dump()
        with self.lock:
            self.require()
            if revision!=self.state['revision']: raise ScheduleConflict('Schedules changed. Refresh and try again.')
            draft=deepcopy(self.state); next_at=next_occurrence(spec,self.clock())
            if spec['enabled'] and next_at is None: raise ValueError('Choose a future alarm or reminder')
            item={**spec,'id':identifier or uuid4().hex,'next_at':next_at}
            if identifier:
                index=next((i for i,x in enumerate(draft['items']) if x['id']==identifier),None)
                if index is None: raise KeyError(identifier)
                draft['items'][index]=item
            else:
                if len(draft['items'])>=64: raise ValueError('Remove a schedule before adding another')
                draft['items'].append(item)
            draft['revision']+=1; self.commit(draft); return deepcopy(item)

    def delete(self,identifier,revision):
        with self.lock:
            self.require()
            if revision!=self.state['revision']: raise ScheduleConflict('Schedules changed. Refresh and try again.')
            if not any(i['id']==identifier for i in self.state['items']): raise KeyError(identifier)
            draft=deepcopy(self.state); draft['items']=[i for i in draft['items'] if i['id']!=identifier]
            for e in draft['events']:
                if e['schedule_id']==identifier and e['status'] in {'due','snoozed'}: e['status']='dismissed'
            draft['revision']+=1; self.commit(draft)

    def set_quiet(self,quiet,revision):
        quiet=QuietHours.model_validate(quiet).model_dump()
        with self.lock:
            self.require()
            if revision!=self.state['revision']: raise ScheduleConflict('Schedules changed. Refresh and try again.')
            draft=deepcopy(self.state); draft['quiet']=quiet; draft['revision']+=1; self.commit(draft)

    def event_action(self,identifier,action,minutes=5):
        with self.lock:
            self.require(); draft=deepcopy(self.state)
            event=next((e for e in draft['events'] if e['id']==identifier),None)
            if event is None: return False
            if action=='dismiss': event['status']='dismissed'
            elif action=='ack':
                if event['status']!='due': return False
                event['delivered']=True
            elif action=='snooze':
                if type(minutes) is not int or not 1<=minutes<=60 or event['status'] not in {'due','missed'}: raise ValueError('Choose 1–60 minutes for a due reminder')
                event.update(status='snoozed',due_at=self.clock()+minutes*60,delivered=False)
            else: raise ValueError('Unknown event action')
            self.commit(draft); return True

    def timer_states(self):
        self.tick()
        with self.lock:
            quiet=self.quiet_now()
            return [{'id':e['id'],'label':e['title'],'remaining_seconds':max(0,e['due_at']-self.clock()),
                'finished':e['status']=='due','notified':e['delivered'] or (quiet and not (e['kind']=='alarm' and self.state['quiet']['alarms_override'])),
                'kind':e['kind'],'spoken_text':e['message'] or f'{e["title"]}. Your {e["kind"]} is ready.'}
                for e in self.state['events'] if e['status'] in {'due','snoozed'}]

    def notify(self,title,message,announce=False):
        # Visual by default. Speaking is an explicit user action and observes quiet hours.
        title=title.strip();message=message.strip()
        if not 1<=len(title)<=80 or not 1<=len(message)<=400 or type(announce) is not bool:
            raise ValueError('Use a title and a message up to 400 characters')
        if any(ord(c)<32 and c not in '\n\t' for c in title+message):raise ValueError('Use readable text')
        with self.lock:
            self.require();draft=deepcopy(self.state)
            if len(draft['events'])>=128:
                inactive=next((i for i,e in enumerate(draft['events']) if e['status'] in {'dismissed','missed','info'}),None)
                if inactive is None:raise ValueError('Dismiss a notification before adding another')
                draft['events'].pop(inactive)
            identifier=uuid4().hex
            draft['events'].append({'id':identifier,'schedule_id':identifier,'title':title,'message':message,
                'kind':'reminder','due_at':self.clock(),'status':'due' if announce else 'info','delivered':False})
            self.commit(draft);return deepcopy(draft['events'][-1])
