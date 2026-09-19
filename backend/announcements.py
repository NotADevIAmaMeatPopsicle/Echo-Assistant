"""Room-addressed, opt-in announcements with durable delivery claims. Audio is never saved."""
import base64
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from threading import RLock
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnnouncementUnavailable(RuntimeError): pass
class AnnouncementConflict(ValueError): pass

EndpointId = r'^(round|[a-f0-9]{32})$'


class RoomEndpoint(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=EndpointId)
    room:str=Field(min_length=1,max_length=60)
    enabled:bool=False


class RoomPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    endpoints:list[RoomEndpoint]=Field(default_factory=list,max_length=33)

    @model_validator(mode='after')
    def unique(self):
        if len({e.id for e in self.endpoints})!=len(self.endpoints):raise ValueError('Assign each receiver once')
        return self


class Delivery(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    endpoint:str=Field(pattern=EndpointId)
    status:Literal['queued','claimed','played','cancelled','failed','unknown','expired']='queued'
    claim_hash:str=''
    claim_until:float=0.0
    client:str=''


class Announcement(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')
    sender:str=Field(pattern=r'^[a-f0-9]{64}$')
    title:str=Field(min_length=1,max_length=80)
    message:str=Field(min_length=1,max_length=400)
    created:float=Field(gt=0,allow_inf_nan=False)
    expires:float=Field(gt=0,allow_inf_nan=False)
    deliveries:list[Delivery]=Field(min_length=1,max_length=33)


class SavedAnnouncements(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    version:Literal[1]=1
    revision:int=Field(default=0,ge=0)
    policy:RoomPolicy=Field(default_factory=RoomPolicy)
    messages:list[Announcement]=Field(default_factory=list,max_length=128)


class Announcements:
    def __init__(self,root,protector,displays,schedules,voice,clock=time.time):
        self.path=Path(root)/'local/echo-announcements.json' if root else None
        self.protector,self.displays,self.schedules,self.voice,self.clock=protector,displays,schedules,voice,clock
        self.lock=RLock();self.heartbeats={};self.error=False;self.state=SavedAnnouncements().model_dump()
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>2_000_000:raise ValueError()
                envelope=json.loads(self.path.read_text())
                if envelope['version']!=1:raise ValueError()
                raw=json.loads(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
                self.state=SavedAnnouncements.model_validate(raw).model_dump()
                if len({m['id'] for m in self.state['messages']})!=len(self.state['messages']):raise ValueError()
                # A process restart cannot prove that a claimed message finished playing.
                for message in self.state['messages']:
                    for delivery in message['deliveries']:
                        if delivery['status']=='claimed':delivery['status']='unknown'
            except (OSError,ValueError,KeyError,TypeError,RuntimeError):self.error=True

    def require(self):
        if self.error:raise AnnouncementUnavailable('Announcement storage could not be read. The existing file is preserved.')

    def commit(self,draft):
        self.require();SavedAnnouncements.model_validate(draft)
        if self.path:
            try:
                raw=self.protector.encrypt(json.dumps(draft).encode());self.path.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.path.with_suffix('.tmp')
                envelope=json.dumps({'version':1,'protected':base64.b64encode(raw).decode()})
                if len(envelope)>2_000_000:raise AnnouncementUnavailable('Announcement history is full. Wait for older receipts to expire.')
                temporary.write_text(envelope)
                temporary.replace(self.path)
            except (OSError,RuntimeError):raise AnnouncementUnavailable('Announcement update could not be saved.') from None
        self.state=draft

    def current_ids(self):return {'round'}|{d['id'] for d in self.displays.snapshot()}
    @staticmethod
    def sender(session):return hashlib.sha256(session.encode()).hexdigest()

    def prune(self):
        self.require();now=self.clock();draft=deepcopy(self.state);ids=self.current_ids()
        enabled={e['id'] for e in draft['policy']['endpoints'] if e['enabled']} & ids
        draft['messages']=[m for m in draft['messages'] if now-m['created']<86400]
        for message in draft['messages']:
            for delivery in message['deliveries']:
                if delivery['status'] not in {'queued','claimed'}:continue
                if delivery['endpoint'] not in enabled:delivery['status']='cancelled'
                elif delivery['status']=='claimed' and delivery['claim_until']<now:delivery['status']='unknown'
                elif delivery['status']=='queued' and message['expires']<now:delivery['status']='expired'
        if draft!=self.state:self.commit(draft)

    def ready(self,identifier,client=None):
        if self.schedules.snapshot()['quiet_active']:return False,'quiet_hours'
        if identifier=='round':
            voice=self.voice()
            if voice.get('muted'):return False,'muted'
            if voice.get('status') not in {'armed','music'}:return False,'busy_or_offline'
            if str(voice.get('device',{}).get('volume'))=='0':return False,'muted'
            return True,'ready'
        beat=self.heartbeats.get(identifier,{})
        if self.clock()-beat.get('at',0)>20:return False,'offline'
        if client and beat.get('client')!=client:return False,'another_session'
        if not beat.get('ready'):return False,'sound_off'
        if beat.get('busy'):return False,'busy'
        return True,'ready'

    def catalog(self):
        with self.lock:
            self.prune();names={'round':'Round Echo speaker',**{d['id']:d['name'] for d in self.displays.snapshot()}}
            policy={e['id']:e for e in self.state['policy']['endpoints']}
            items=[]
            for identifier,name in names.items():
                config=policy.get(identifier,{'id':identifier,'room':'','enabled':False})
                ready,status=self.ready(identifier)
                items.append({**config,'name':name,'ready':ready and config['enabled'],'status':status if config['enabled'] else 'disabled'})
            return {'revision':self.state['revision'],'items':items,'quiet_active':self.schedules.snapshot()['quiet_active']}

    def configure(self,endpoints,revision):
        policy=RoomPolicy.model_validate({'endpoints':endpoints}).model_dump()
        with self.lock:
            self.prune()
            if revision!=self.state['revision']:raise AnnouncementConflict('Room assignments changed. Reload before saving.')
            if not {e['id'] for e in policy['endpoints']}<=self.current_ids():raise ValueError('Choose currently paired receivers')
            draft=deepcopy(self.state);draft.update(policy=policy,revision=revision+1);self.commit(draft);self.prune()
        return self.catalog()

    def heartbeat(self,identifier,client,ready,busy):
        with self.lock:
            previous=self.heartbeats.get(identifier,{})
            if previous.get('client')!=client and previous.get('ready') and self.clock()-previous.get('at',0)<20:return
            self.heartbeats[identifier]={'at':self.clock(),'client':client,'ready':ready,'busy':busy}

    def send(self,identifier,session,title,message,targets,revision,issued_at):
        title=title.strip();message=message.strip()
        if not title or not message or any(ord(c)<32 and c not in '\n\t' for c in title+message):raise ValueError('Use a readable title and message')
        fingerprint=hashlib.sha256(json.dumps([title,message,sorted(targets)]).encode()).hexdigest()
        sender=self.sender(session)
        with self.lock:
            self.prune()
            existing=next((m for m in self.state['messages'] if m['id']==identifier),None)
            if existing:
                if existing['sender']!=sender or existing['fingerprint']!=fingerprint:raise AnnouncementConflict('That request ID belongs to a different message')
                return self.report(existing)
            if abs(self.clock()-issued_at)>300:raise ValueError('This draft expired. Start a new message.')
            if revision!=self.state['revision']:raise AnnouncementConflict('Room assignments changed. Reload before sending.')
            enabled={e['id'] for e in self.state['policy']['endpoints'] if e['enabled']} & self.current_ids()
            if not targets or len(set(targets))!=len(targets) or not set(targets)<=enabled:raise ValueError('Choose enabled, paired receivers')
            if len(self.state['messages'])>=128:raise AnnouncementUnavailable('Announcement history is full. Try again after older receipts expire.')
            created=float(self.clock())
            record=Announcement(id=identifier,fingerprint=fingerprint,sender=sender,title=title,message=message,created=created,expires=created+300,
                                deliveries=[Delivery(endpoint=t) for t in targets]).model_dump()
            draft=deepcopy(self.state);draft['messages'].append(record);self.commit(draft)
            return self.report(record)

    def report(self,message):
        rooms={e['id']:e['room'] for e in self.state['policy']['endpoints']}
        return {k:deepcopy(message[k]) for k in ('id','title','message','created','expires')} | {
            'deliveries':[{'endpoint':d['endpoint'],'room':rooms.get(d['endpoint'],'Unassigned'),'status':d['status']} for d in message['deliveries']]}

    def reports(self,session):
        with self.lock:
            self.prune();sender=self.sender(session)
            return {'items':[self.report(m) for m in reversed(self.state['messages']) if not session.startswith('display:') or m['sender']==sender]}

    def cancel(self,identifier,session):
        with self.lock:
            self.prune();draft=deepcopy(self.state)
            message=next((m for m in draft['messages'] if m['id']==identifier),None)
            if not message:raise KeyError()
            if session.startswith('display:') and message['sender']!=self.sender(session):raise PermissionError('Only the sender can cancel this announcement')
            for delivery in message['deliveries']:
                if delivery['status'] in {'queued','claimed'}:delivery['status']='cancelled'
            self.commit(draft);return self.report(message)

    def inbox(self,identifier,client=None):
        with self.lock:
            self.prune();ready,reason=self.ready(identifier,client)
            enabled=any(e['id']==identifier and e['enabled'] for e in self.state['policy']['endpoints'])
            items=[];active=[]
            for message in self.state['messages']:
                for delivery in message['deliveries']:
                    if delivery['endpoint']!=identifier:continue
                    if ready and enabled and delivery['status']=='queued':items.append({k:message[k] for k in ('id','title','message','expires')})
                    if delivery['client']==client and delivery['status']!='queued':active.append({'id':message['id'],'status':delivery['status']})
            return {'enabled':enabled,'ready':ready and enabled,'status':reason if enabled else 'disabled','items':items,'active':active}

    def claim(self,identifier,message_id,client):
        with self.lock:
            self.prune()
            if not self.inbox(identifier,client)['ready']:raise AnnouncementConflict('Receiver is muted, busy, offline, or in quiet hours')
            draft=deepcopy(self.state)
            message=next((m for m in draft['messages'] if m['id']==message_id),None)
            delivery=next((d for d in message['deliveries'] if d['endpoint']==identifier),None) if message else None
            if not delivery or delivery['status']!='queued':raise AnnouncementConflict('Announcement is no longer waiting for this receiver')
            claim=secrets.token_hex(32)
            delivery.update(status='claimed',claim_hash=hashlib.sha256(claim.encode()).hexdigest(),claim_until=float(self.clock()+180),client=client)
            self.commit(draft);return {'claim':claim,'title':message['title'],'message':message['message']}

    def claimed(self,identifier,message_id,claim):
        self.prune()
        message=next((m for m in self.state['messages'] if m['id']==message_id),None)
        delivery=next((d for d in message['deliveries'] if d['endpoint']==identifier),None) if message else None
        if not delivery or delivery['status']!='claimed' or not hmac.compare_digest(delivery['claim_hash'],hashlib.sha256(claim.encode()).hexdigest()):
            raise AnnouncementConflict('Delivery claim is no longer active')
        return message,delivery

    def text(self,identifier,message_id,claim):
        with self.lock:
            message,delivery=self.claimed(identifier,message_id,claim)
            # Generation may take time: callers repeat this check before returning audio.
            if not self.ready(identifier,delivery['client'])[0]:raise AnnouncementConflict('Receiver is no longer ready')
            return message['message']

    def receipt(self,identifier,message_id,claim,status):
        if status not in {'played','cancelled','failed'}:raise ValueError('Invalid playback result')
        with self.lock:
            self.claimed(identifier,message_id,claim);draft=deepcopy(self.state)
            message=next(m for m in draft['messages'] if m['id']==message_id)
            next(d for d in message['deliveries'] if d['endpoint']==identifier)['status']=status
            self.commit(draft);return {'status':status}
