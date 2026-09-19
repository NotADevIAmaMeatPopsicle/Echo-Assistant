"""Opt-in doorbell observation and encrypted ring history. No actuation or audio."""
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from threading import RLock
import time
from pydantic import BaseModel, ConfigDict, Field
from .experiences import ExperienceUnavailable
from .home import HomeUnavailable


class Ring(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    trigger:str=Field(pattern=r'^(event|binary_sensor)\.[a-z0-9_]{1,128}$')
    at:float=Field(gt=0,allow_inf_nan=False)


class Doorbells:
    def __init__(self,experiences,root=None,protector=None,clock=time.time):
        self.experiences,self.protector,self.clock=experiences,protector,clock
        self.path=Path(root)/'local/echo-doorbells.json' if root else None
        self.lock=RLock();self.events=[];self.baseline={};self.revision=None;self.status='warming';self.error=False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>100_000:raise ValueError()
                doc=json.loads(self.path.read_text())
                if doc['version']!=1:raise ValueError()
                raw=json.loads(protector.decrypt(base64.b64decode(doc['protected'],validate=True)))
                if not isinstance(raw,list) or len(raw)>100:raise ValueError()
                self.events=[Ring.model_validate(e).model_dump() for e in raw]
                if len({e['id'] for e in self.events})!=len(self.events):raise ValueError()
            except (OSError,ValueError,TypeError,KeyError,RuntimeError):self.error=True

    def save(self,events):
        if self.error:raise ExperienceUnavailable('Doorbell history could not be read. The existing file is preserved.')
        if self.path:
            try:
                raw=self.protector.encrypt(json.dumps(events).encode())
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(raw).decode()}))
                temporary.replace(self.path)
            except (OSError,RuntimeError):raise ExperienceUnavailable('Doorbell history could not be saved.') from None
        self.events=events

    def tick(self):
        try:
            snapshot=self.experiences.store.snapshot();selected=snapshot['sources']['doorbells']
            if not selected or not self.experiences.home.config.enabled:
                with self.lock:
                    self.baseline={};self.status='not_selected' if not selected else 'not_configured'
                    if not selected and self.events:self.save([])
                return
            states=self.experiences.home._request('GET','/api/states')
            if not isinstance(states,list):raise HomeUnavailable('Doorbell state unavailable')
            states={s.get('entity_id'):s for s in states if isinstance(s,dict) and isinstance(s.get('entity_id'),str)}
            if self.experiences.store.snapshot()['revision']!=snapshot['revision']:return
            with self.lock:
                if self.revision!=snapshot['revision']:self.baseline={};self.revision=snapshot['revision']
                current={};events=list(self.events);unavailable=False
                for binding in selected:
                    identifier=binding['trigger'];state=states.get(identifier,{})
                    value=state.get('state')
                    event=identifier.startswith('event.')
                    if event and value=='unknown':current[identifier]='unknown';continue
                    if not isinstance(value,str) or value in {'unknown','unavailable'}:unavailable=True;continue
                    raw_time=value if event else state.get('last_changed','')
                    try:
                        instant=datetime.fromisoformat(raw_time.replace('Z','+00:00'))
                        if instant.tzinfo is None:raise ValueError()
                        at=instant.timestamp()
                    except (ValueError,TypeError,AttributeError):unavailable=True;continue
                    if not event and value not in {'on','off'}:unavailable=True;continue
                    current[identifier]=value
                    previous=self.baseline.get(identifier)
                    changed=previous is not None and previous!=value and (event or previous=='off' and value=='on')
                    if changed and 0<=self.clock()-at<=30:
                        key=hashlib.sha256((identifier+'\0'+raw_time).encode()).hexdigest()[:32]
                        if not any(e['id']==key for e in events):events.append({'id':key,'trigger':identifier,'at':float(at)})
                allowed={d['trigger'] for d in selected}
                events=[e for e in events if e['trigger'] in allowed][-100:]
                if events!=self.events:self.save(events)
                self.baseline=current;self.status='partial' if unavailable else 'available'
        except (HomeUnavailable,ExperienceUnavailable):
            with self.lock:self.baseline={};self.status='unavailable'

    def snapshot(self):
        snapshot=self.experiences.store.snapshot();sources=snapshot['sources'];selected={d['trigger']:d for d in sources['doorbells']}
        with self.lock:
            if self.error:raise ExperienceUnavailable('Doorbell history could not be read. The existing file is preserved.')
            events=[]
            for event in reversed(self.events):
                if event['trigger'] not in selected:continue
                binding=selected[event['trigger']]
                events.append({**event,'label':binding['label'],'camera':binding['camera'] if binding['camera'] in sources['cameras'] else None})
            return {'status':self.status if selected else 'not_selected','events':deepcopy(events),'revision':snapshot['revision']}

    def dismiss(self,identifier):
        selected={d['trigger'] for d in self.experiences.store.snapshot()['sources']['doorbells']}
        with self.lock:self.save([e for e in self.events if e['id']!=identifier or e['trigger'] not in selected])
        return self.snapshot()
