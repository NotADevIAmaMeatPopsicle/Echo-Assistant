"""Live Mini policy refresh and immutable request identities for queued work."""
import re
import time
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


class RoundAccess:
    def __init__(self,root,store=None,clock=time.monotonic):
        self.store=store or RoundProfile(root,default_protector());self.clock=clock
        self.firmware=False;self.next_poll=0;self.applied=None;self.state=self.read()
    def read(self):
        try:return {**self.store.snapshot(),'available':True}
        except RoundProfileUnavailable:
            return {'profile':DisplayProfile(mode='guest',conversation=False,name='Access unavailable').model_dump(),'profile_revision':-1,'available':False}
    def observe(self,line):
        if line.startswith('STATUS '):self.firmware=bool(re.search(r'\baccess_profile=1\b',line))
    def refresh(self):
        if self.clock()<self.next_poll:return False
        self.next_poll=self.clock()+.5;state=self.read();key=(state,self.firmware)
        changed=self.applied!=key;self.state=state;self.applied=key;return changed
    @property
    def guest(self):return self.state['profile']['mode']=='guest'
    @property
    def conversation(self):return self.state['available'] and (not self.guest or self.firmware and self.state['profile']['conversation'])
    def client(self,base):return RoundClient(base,self.state['profile_revision'])
    def health(self):return {'firmware':self.firmware,'mode':self.state['profile']['mode'],'revision':self.state['profile_revision'],'available':self.state['available']}
    def configure(self,write):
        if self.firmware:
            name=re.sub(r'[^ -~]','',self.state['profile']['name'])[:24] or ('Guest' if self.guest else 'Household')
            write(f"PROFILE_SET {max(0,self.state['profile_revision'])} {int(self.guest)} {int(self.conversation)} :{name}\n".encode('ascii'))
