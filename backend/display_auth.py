"""Owner-approved display enrollment, revocable credentials and scoped sessions."""
import base64
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
from threading import RLock
import time

from fastapi import HTTPException


class DisplayStorageUnavailable(RuntimeError): pass


def allowed(method,path):
    reads={'/v1/voice','/v1/home','/v1/display/home','/v1/state','/v1/household','/v1/schedules',
           '/v1/routines','/v1/memory','/v1/tasks','/v1/chat/activity','/v1/display/session',
           '/v1/display/sources','/v1/display/agenda','/v1/display/photos','/v1/display/media'}
    if method=='GET' and re.fullmatch(r'/v1/display/photos/[a-f0-9]{32}',path): return True
    if method=='GET' and re.fullmatch(r'/v1/display/cameras/camera\.[a-z0-9_]{1,128}/snapshot',path): return True
    if method=='GET' and (path in reads or re.fullmatch(r'/v1/tasks/[a-f0-9]{32}',path)): return True
    exact={
        'POST':{'/v1/chat','/v1/timers','/v1/household','/v1/schedules','/v1/memory','/v1/tasks','/v1/notifications',
                '/v1/display/home/control','/v1/music/control','/v1/home/speakers/select','/v1/home/speakers/control'},
        'PUT':{'/v1/schedule-preferences'},
    }
    if path in exact.get(method,set()): return True
    patterns={
        'POST':[r'/v1/timers/[a-f0-9]{32}/ack',r'/v1/schedule-events/[a-f0-9]{32}',r'/v1/routines/[a-f0-9]{32}/run',
                r'/v1/(?:chat/activity|tasks)/[a-f0-9]{32}/stop',r'/v1/home/rooms/(?:bedroom|living_room|dining_room|patio)/actions',
                r'/v1/home/(?:thermostat|soundbar)/actions'],
        'PUT':[r'/v1/(?:schedules|memory)/[a-f0-9]{32}'],
        'PATCH':[r'/v1/household/[a-f0-9]{32}'],
        'DELETE':[r'/v1/(?:timers|schedules|household|memory|tasks)/[a-f0-9]{32}'],
    }
    return any(re.fullmatch(pattern,path) for pattern in patterns.get(method,[]))


class Displays:
    def __init__(self,root,protector,clock=time.time):
        self.path=Path(root)/'local/echo-displays.json' if root else None
        self.protector,self.clock,self.lock=protector,clock,RLock()
        self.devices=[]; self.pending={}; self.sessions={}; self.seen={}; self.error=False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>100_000: raise ValueError()
                envelope=json.loads(self.path.read_text())
                if envelope['version']!=1: raise ValueError()
                devices=json.loads(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
                if not isinstance(devices,list) or len(devices)>32: raise ValueError()
                ids=set()
                for d in devices:
                    if set(d)!={'id','name','hash','created_at'} or not re.fullmatch('[a-f0-9]{32}',d['id']) or d['id'] in ids: raise ValueError()
                    if not isinstance(d['name'],str) or not 1<=len(d['name'])<=60 or not re.fullmatch('[a-f0-9]{64}',d['hash']): raise ValueError()
                    ids.add(d['id'])
                self.devices=devices
            except (OSError,ValueError,TypeError,KeyError,RuntimeError): self.error=True

    def require(self):
        if self.error: raise DisplayStorageUnavailable('Display credentials could not be read. Existing storage is preserved.')

    def commit(self,devices):
        if self.path:
            try:
                raw=self.protector.encrypt(json.dumps(devices).encode())
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(raw).decode()}))
                temporary.replace(self.path)
            except (OSError,RuntimeError): raise DisplayStorageUnavailable('Display credentials could not be saved.') from None
        self.devices=devices

    def prune(self):
        now=self.clock()
        self.pending={k:v for k,v in self.pending.items() if v['expires_at']>now}
        self.sessions={k:v for k,v in self.sessions.items() if v['expires_at']>now}

    def pairing(self,name):
        name=name.strip()
        if not 1<=len(name)<=60 or any(ord(c)<32 for c in name): raise ValueError('Choose a display name of 1–60 characters')
        with self.lock:
            self.require(); self.prune()
            if len(self.devices)>=32 or len(self.pending)>=8: raise ValueError('Revoke an unused display or wait for pending codes to expire')
            code=secrets.token_urlsafe(32); expires=self.clock()+300
            self.pending[hashlib.sha256(code.encode()).hexdigest()]={'name':name,'expires_at':expires}
            return {'code':code,'expires_at':expires,'name':name}

    def enroll(self,code):
        with self.lock:
            self.require(); self.prune(); digest=hashlib.sha256(code.encode()).hexdigest()
            pending=self.pending.get(digest)
            if not pending: raise HTTPException(401,'Pairing code expired or was already used')
            if len(self.devices)>=32: raise HTTPException(409,'Display limit reached')
            identifier=secrets.token_hex(16); secret=secrets.token_urlsafe(32)
            self.commit(self.devices+[{'id':identifier,'name':pending['name'],'hash':hashlib.sha256(secret.encode()).hexdigest(),'created_at':self.clock()}])
            self.pending.pop(digest,None)
            return {'id':identifier,'name':pending['name'],'credential':identifier+'.'+secret}

    def credential(self,header):
        with self.lock:
            self.require()
            if not header.startswith('Display '): raise HTTPException(401,'A paired display credential is required')
            pieces=header[8:].split('.')
            if len(pieces)!=2: raise HTTPException(401,'Invalid display credential')
            identifier,secret=pieces
            device=next((d for d in self.devices if d['id']==identifier),None)
            if device is None or not hmac.compare_digest(device['hash'],hashlib.sha256(secret.encode()).hexdigest()):
                raise HTTPException(401,'Display was revoked or its credential is invalid')
            self.seen[identifier]=self.clock(); return identifier

    def new_session(self,header):
        with self.lock:
            identifier=self.credential(header); self.prune()
            if len(self.sessions)>=64: self.sessions.pop(next(iter(self.sessions)))
            token=secrets.token_urlsafe(32)
            self.sessions[token]={'id':identifier,'expires_at':self.clock()+8*3600}
            return token

    def authorize(self,request):
        header=request.headers.get('authorization','')
        if header.startswith('Display '): identifier=self.credential(header)
        else:
            with self.lock:
                self.require(); self.prune()
                entry=self.sessions.get(request.cookies.get('echo_display_session',''))
                if not entry or not any(d['id']==entry['id'] for d in self.devices): raise HTTPException(401,'Display session expired or was revoked')
                identifier=entry['id']; self.seen[identifier]=self.clock()
            if request.method not in {'GET','HEAD'}:
                from .web_auth import BrowserAuth
                BrowserAuth.same_origin(request)
        if not allowed(request.method,request.url.path): raise HTTPException(403,'Open the owner workspace to administer Echo')
        return 'display:'+identifier

    def snapshot(self):
        with self.lock:
            self.require()
            return [{'id':d['id'],'name':d['name'],'created_at':d['created_at'],'last_seen':self.seen.get(d['id'])} for d in self.devices]

    def revoke(self,identifier):
        with self.lock:
            self.require()
            if not any(d['id']==identifier for d in self.devices): return False
            self.commit([d for d in self.devices if d['id']!=identifier])
            self.sessions={k:v for k,v in self.sessions.items() if v['id']!=identifier}
            self.seen.pop(identifier,None); return True
