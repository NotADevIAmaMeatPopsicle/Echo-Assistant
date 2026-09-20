"""Local personal accounts. The host is trusted; a shared endpoint is not a person.

Passcodes unlock one existing endpoint for a bounded session. No browser token,
provider credential, transcript or passcode is persisted by this service.
"""
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
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .display_profiles import DisplayProfile,guest_allowed
from .memory import MemoryStore,MemoryUnavailable


class MembersUnavailable(RuntimeError):pass


class PersonalPrincipal(str):
    def __new__(cls,endpoint,member,nonce):
        value=super().__new__(cls,endpoint);value.member=member;value.nonce=nonce;return value


class MemberPreferences(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    personality:str=Field(default='',max_length=4000)
    memory_enabled:bool=True


def hashed(code,salt):
    return hashlib.scrypt(code.encode('ascii'),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=32).hex()


class Members:
    def __init__(self,root,protector,*,clock=time.monotonic,wall=time.time):
        self.path=Path(root)/'local/echo-members.json' if root else None
        self.protector,self.clock,self.wall=protector,clock,wall
        self.lock=RLock();self.records={};self.sessions={};self.memories={};self.error=False
        self.base_profile=None;self.on_lock=lambda principal:None
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>6000000:raise ValueError()
                envelope=json.loads(self.path.read_text())
                if envelope['version']!=1:raise ValueError()
                records=json.loads(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
                if not isinstance(records,dict) or len(records)>16:raise ValueError()
                for identifier,item in records.items():self.validate(identifier,item)
                self.records=records
            except (OSError,ValueError,TypeError,KeyError,RuntimeError):self.error=True

    @staticmethod
    def validate(identifier,item):
        if not re.fullmatch('[a-f0-9]{32}',identifier) or set(item)!={'name','revision','salt','hash','profile','preferences','memory','failures','locked_until'}:raise ValueError()
        if not isinstance(item['name'],str) or not 1<=len(item['name'])<=60 or any(ord(c)<32 for c in item['name']):raise ValueError()
        if type(item['revision']) is not int or item['revision']<0:raise ValueError()
        if not re.fullmatch('[a-f0-9]{32}',item['salt']) or not re.fullmatch('[a-f0-9]{64}',item['hash']):raise ValueError()
        profile=DisplayProfile.model_validate(item['profile'])
        if profile.mode!='guest' or profile.members:raise ValueError()
        MemberPreferences.model_validate(item['preferences'])
        if not isinstance(item['memory'],list) or len(item['memory'])>200:raise ValueError()
        seen=set()
        for fact in item['memory']:
            if set(fact)!={'id','text','created_at','updated_at'} or not re.fullmatch('[a-f0-9]{32}',fact['id']) or fact['id'] in seen:raise ValueError()
            seen.add(fact['id']);MemoryStore.validate_text(fact['text'])
            if any(type(fact[k]) not in (int,float) or not 0<=fact[k]<1e12 for k in ('created_at','updated_at')):raise ValueError()
        if type(item['failures']) is not int or not 0<=item['failures']<=5 or type(item['locked_until']) not in (int,float) or not 0<=item['locked_until']<1e12:raise ValueError()

    def require(self):
        if self.error:raise MembersUnavailable('Personal accounts could not be read. The saved file has been preserved.')

    def commit(self,records):
        self.require()
        if len(records)>16:raise ValueError('Echo supports up to 16 personal accounts')
        if self.path:
            try:
                plain=json.dumps(records,ensure_ascii=False).encode()
                if len(plain)>4400000:raise ValueError('Personal storage is full. Remove saved facts before adding more.')
                encoded={'version':1,'protected':base64.b64encode(self.protector.encrypt(plain)).decode()}
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(encoded));temporary.replace(self.path)
            except (OSError,RuntimeError):raise MembersUnavailable('Personal accounts could not be saved. Previous data is unchanged.') from None
        self.records=records

    def item(self,identifier):
        self.require()
        if identifier not in self.records:raise HTTPException(404,'Personal account not found')
        return self.records[identifier]

    def roster(self):
        with self.lock:
            self.require()
            return [{'id':key,'name':v['name'],'revision':v['revision'],'profile':deepcopy(v['profile'])} for key,v in self.records.items()]

    def new_code(self,item):
        code=f'{secrets.randbelow(100000000):08d}';salt=secrets.token_hex(16)
        item.update(salt=salt,hash=hashed(code,salt),failures=0,locked_until=0)
        return code

    def create(self,name):
        name=name.strip()
        if not 1<=len(name)<=60 or any(ord(c)<32 for c in name):raise ValueError('Use a name between 1 and 60 characters')
        with self.lock:
            self.require()
            if any(v['name'].casefold()==name.casefold() for v in self.records.values()):raise ValueError('Choose a distinct account name')
            identifier=uuid4().hex
            item={'name':name,'revision':0,'profile':DisplayProfile(mode='guest',name=name).model_dump(),
                  'preferences':MemberPreferences().model_dump(),'memory':[]}
            code=self.new_code(item);records=deepcopy(self.records);records[identifier]=item;self.commit(records)
            return {'id':identifier,'name':name,'passcode':code,'revision':0}

    def permitted(self,endpoint):
        self.require()
        if endpoint=='round':return []  # Mini personal sign-in needs its own explicit phone/firmware flow.
        base=self.base_profile(str(endpoint))['profile']
        if endpoint.startswith('display:'):
            return [identifier for identifier in base.get('members',[]) if identifier in self.records] if base['mode']=='household' or base['conversation'] else []
        return list(self.records)  # The owner workspace can deliberately enter a personal session.

    def available(self,endpoint):
        with self.lock:
            return [{'id':key,'name':self.records[key]['name']} for key in self.permitted(endpoint)]

    def login(self,endpoint,identifier,code):
        endpoint=str(endpoint)
        with self.lock:
            if identifier not in self.permitted(endpoint):raise HTTPException(403,'This account is not shared with this display')
            item=self.item(identifier)
            if item['locked_until']>self.wall():raise HTTPException(429,'Too many attempts. Wait five minutes before trying again.')
            valid=bool(re.fullmatch(r'[0-9]{8}',code)) and hmac.compare_digest(hashed(code,item['salt']),item['hash'])
            records=deepcopy(self.records);record=records[identifier]
            if not valid:
                record['failures']=(0 if record['locked_until'] else record['failures'])+1
                record['locked_until']=self.wall()+300 if record['failures']>=5 else 0
                self.commit(records);raise HTTPException(401,'Passcode was not accepted')
            record.update(failures=0,locked_until=0);self.commit(records)
            self.lock_session(endpoint)
            if len(self.sessions)>=64:self.lock_session(next(iter(self.sessions)))
            entry={'member':identifier,'nonce':uuid4().hex,'expires':self.clock()+900,'expires_at':self.wall()+900}
            self.sessions[endpoint]=entry
            return self.resolve(endpoint)

    def lock_session(self,endpoint):
        endpoint=str(endpoint);entry=self.sessions.pop(endpoint,None)
        if entry:self.on_lock(PersonalPrincipal(endpoint,entry['member'],entry['nonce']))

    def resolve(self,endpoint):
        with self.lock:
            entry=self.sessions.get(str(endpoint))
            if not entry:return str(endpoint)
            if entry['expires']<=self.clock() or entry['member'] not in self.permitted(endpoint):
                self.lock_session(endpoint);return str(endpoint)
            return PersonalPrincipal(str(endpoint),entry['member'],entry['nonce'])

    def current(self,principal):
        with self.lock:
            self.require();entry=self.sessions.get(str(principal))
            if (not isinstance(principal,PersonalPrincipal) or not entry or entry['nonce']!=principal.nonce or
                    entry['member']!=principal.member or not isinstance(self.resolve(str(principal)),PersonalPrincipal)):
                raise HTTPException(401,'Personal session locked. Sign in again.')
            return self.item(principal.member)

    def profile_for(self,principal):
        with self.lock:
            item=self.current(principal);base=self.base_profile(str(principal));profile=deepcopy(item['profile'])
            if base['profile']['mode']=='guest':
                other=base['profile'];profile['conversation'] &= other['conversation'];profile['home_voice'] &= other['home_voice']
                profile['home_devices']={k:'control' if v=='control' and other['home_devices'][k]=='control' else 'read'
                    for k,v in profile['home_devices'].items() if k in other['home_devices']}
                for key in ('calendars','cameras','presence_sensors'):profile[key]=[v for v in profile[key] if v in other[key]]
            profile['personal']=True;profile['name']=item['name'];profile['members']=[]
            revision=int(hashlib.sha256(json.dumps([base['profile_revision'],item['revision'],principal.nonce]).encode()).hexdigest()[:13],16)
            return {'profile':profile,'profile_revision':revision,'member':{'id':principal.member,'name':item['name'],
                    'expires_at':self.sessions[str(principal)]['expires_at']}}

    def authorize(self,request,principal):
        profile=self.profile_for(principal)['profile']
        if not guest_allowed(request.method,request.url.path,profile):raise HTTPException(403,'This feature is not available in a personal session')
        return principal

    def change(self,identifier,revision,*,profile=None,reset=False,delete=False):
        with self.lock:
            item=self.item(identifier)
            if item['revision']!=revision:raise HTTPException(409,'This account changed. Reload before saving.')
            records=deepcopy(self.records);record=records[identifier];record['revision']+=1;code=None
            if profile is not None:
                checked=DisplayProfile.model_validate(profile)
                if checked.mode!='guest' or checked.members:raise ValueError('Personal accounts use selected grants, without other account assignments')
                checked.name=record['name'];record['profile']=checked.model_dump()
            if reset:code=self.new_code(record)
            if delete:del records[identifier]
            self.commit(records)
            for endpoint,session in list(self.sessions.items()):
                if session['member']==identifier:self.lock_session(endpoint)
            if delete:self.memories.pop(identifier,None)
            return {'id':identifier,'revision':record['revision'],**({'passcode':code} if code else {})}

    def memory(self,principal):
        with self.lock:
            self.current(principal)
            if principal.member not in self.memories:self.memories[principal.member]=MemberMemory(self,principal.member)
            return BoundMemory(self,self.memories[principal.member],principal)

    def preferences(self,principal,values=None):
        with self.lock:
            item=self.current(principal)
            if values is not None:
                records=deepcopy(self.records);records[principal.member]['preferences']=MemberPreferences.model_validate(values).model_dump()
                records[principal.member]['revision']+=1;self.commit(records)
            return deepcopy(self.item(principal.member)['preferences'])


class BoundMemory:
    """Validate the captured login while holding the same lock as each operation."""
    def __init__(self,members,memory,principal):
        self.members,self.memory,self.principal=members,memory,principal
        self.lock=members.lock
    @property
    def revision(self):return self.memory.revision
    @property
    def error(self):return self.memory.error
    def __getattr__(self,name):
        if name not in {'snapshot','relevant','save','edit','delete','clear','update'}:raise AttributeError(name)
        def call(*args,**kwargs):
            with self.lock:
                self.members.current(self.principal)
                return getattr(self.memory,name)(*args,**kwargs)
        return call


class MemberMemory(MemoryStore):
    def __init__(self,members,identifier):
        super().__init__(None,members.protector);self.members,self.identifier=members,identifier
        self.lock=members.lock;self.records=deepcopy(members.item(identifier)['memory'])
    def _require(self):
        try:self.members.item(self.identifier)
        except HTTPException:raise MemoryUnavailable('This personal account was removed') from None
    def _commit(self,records):
        self._require()
        if len(records)>200:raise ValueError('Memory is full. Remove a saved item before adding another.')
        values=deepcopy(self.members.records);values[self.identifier]['memory']=deepcopy(records)
        self.members.commit(values);self.records=records;self.revision+=1
