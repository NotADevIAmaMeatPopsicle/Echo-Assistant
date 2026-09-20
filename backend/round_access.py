"""Live Mini policy refresh and immutable request identities for queued work."""
import re
import time
import httpx
from .round_profile import RoundProfile,RoundProfileUnavailable
from .display_profiles import DisplayProfile
from .settings import default_protector


class RoundClient:
    def __init__(self,client,revision):self.client,self.revision=client,revision
    def headers(self,kwargs):
        return {**kwargs.pop('headers',{}),'X-Echo-Endpoint':'round','X-Echo-Access-Revision':str(self.revision)}
    def request(self,method,path,**kwargs):return self.client.request(method,path,headers=self.headers(kwargs),**kwargs)
    def get(self,path,**kwargs):return self.request('GET',path,**kwargs)
    def post(self,path,**kwargs):return self.request('POST',path,**kwargs)
    def stream(self,method,path,**kwargs):return self.client.stream(method,path,headers=self.headers(kwargs),**kwargs)


class RemoteRoundProfile:
    """Fetch API-owned personal sessions without blocking the audio pump."""
    def __init__(self,client,worker,clock=time.monotonic):
        self.client,self.worker,self.clock=client,worker,clock
        self.pending=None;self.value=None;self.at=0;self.next=0
    def fetch(self):
        response=self.client.get('/v1/round/session',headers={'X-Echo-Endpoint':'round'},timeout=1)
        response.raise_for_status();value=response.json()
        if type(value.get('profile_revision')) is not int or not 0<=value['profile_revision']<2**53:raise ValueError()
        profile=dict(value['profile']);personal=profile.pop('personal',False)
        DisplayProfile.model_validate(profile)
        if personal is not False and personal is not True:raise ValueError()
        return value
    def snapshot(self):
        now=self.clock()
        if self.pending is not None and self.pending.done():
            try:self.value=self.pending.result();self.at=now
            except (httpx.HTTPError,ValueError,KeyError,TypeError):self.value=None
            self.pending=None
        if self.pending is None and now>=self.next:
            self.pending=self.worker.submit(self.fetch);self.next=now+.5
        if self.value is None or now-self.at>2:raise RoundProfileUnavailable('Mini session is unavailable')
        return self.value


class RoundAccess:
    def __init__(self,root,store=None,clock=time.monotonic):
        self.store=store or RoundProfile(root,default_protector());self.clock=clock
        self.firmware=False;self.members=False;self.next_poll=0;self.applied=None;self.state=self.read()
    def read(self):
        try:return {**self.store.snapshot(),'available':True}
        except RoundProfileUnavailable:
            return {'profile':DisplayProfile(mode='guest',conversation=False,name='Access unavailable').model_dump(),'profile_revision':-1,'available':False}
    def observe(self,line):
        if line.startswith('STATUS '):
            self.firmware=bool(re.search(r'\baccess_profile=1\b',line))
            self.members=bool(re.search(r'\bmember_accounts=1\b',line))
    def refresh(self):
        if self.clock()<self.next_poll:return False
        self.next_poll=self.clock()+.5;state=self.read();key=(state,self.firmware)
        changed=self.applied!=key;self.state=state;self.applied=key;return changed
    @property
    def guest(self):return self.state['profile']['mode']=='guest'
    @property
    def conversation(self):return self.state['available'] and (not self.guest or self.firmware and self.state['profile']['conversation'])
    def client(self,base):return RoundClient(base,self.state['profile_revision'])
    def health(self):return {'firmware':self.firmware,'members':self.members,'mode':self.state['profile']['mode'],'revision':self.state['profile_revision'],'available':self.state['available']}
    def configure(self,write):
        if self.firmware:
            name=re.sub(r'[^ -~]','',self.state['profile']['name'])[:24] or ('Guest' if self.guest else 'Household')
            kind=2 if self.members and self.state['profile'].get('personal') else int(self.guest)
            write(f"PROFILE_SET {max(0,self.state['profile_revision'])} {kind} {int(self.conversation)} :{name}\n".encode('ascii'))
