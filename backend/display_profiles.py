"""Owner-assigned display access. A guest profile never inherits household tools."""
from copy import deepcopy
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DisplayProfile(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    mode:Literal['household','guest']='household'
    name:str=Field(default='Household',min_length=1,max_length=60)
    room:str=Field(default='',max_length=60)
    conversation:bool=True
    home_voice:bool=False
    home_devices:dict[str,Literal['read','control']]=Field(default_factory=dict,max_length=100)
    calendars:list[str]=Field(default_factory=list,max_length=12)
    cameras:list[str]=Field(default_factory=list,max_length=12)
    presence_sensors:list[str]=Field(default_factory=list,max_length=12)
    members:list[str]=Field(default_factory=list,max_length=16)

    @field_validator('members')
    @classmethod
    def member_ids(cls,value):
        if len(set(value))!=len(value) or any(not re.fullmatch('[a-f0-9]{32}',v) for v in value):raise ValueError('Choose unique personal accounts')
        return value

    @field_validator('name','room')
    @classmethod
    def clean_name(cls,value):
        if value!=value.strip() or any(ord(c)<32 for c in value):raise ValueError('Use a plain name without surrounding spaces')
        return value

    @field_validator('home_devices')
    @classmethod
    def devices(cls,value):
        # Scenes can affect entities outside the selected room, so cannot be delegated.
        if any(not re.fullmatch(r'(light|switch|climate|media_player|weather)\.[a-z0-9_]{1,200}',key) for key in value):
            raise ValueError('Choose supported individual home devices')
        if any(key.startswith('weather.') and access=='control' for key,access in value.items()):
            raise ValueError('Weather is read only')
        return value

    @field_validator('calendars','cameras','presence_sensors')
    @classmethod
    def sources(cls,value,info):
        domain={'calendars':'calendar','cameras':'camera','presence_sensors':'binary_sensor'}[info.field_name]
        if len(set(value))!=len(value) or any(not re.fullmatch(domain+r'\.[a-z0-9_]{1,128}',v) for v in value):
            raise ValueError('Choose unique sources')
        return value


def personal_google_allowed(method,path):
    base='/v1/member/calendar/google'
    if (method,path) in {('GET',base),('POST',base+'/flows'),('PUT',base+'/selection')}:return True
    if method in {'GET','DELETE'} and re.fullmatch(base+r'/flows/[a-f0-9]{32}',path):return True
    if method=='POST' and re.fullmatch(base+r'/flows/[a-f0-9]{32}/finish',path):return True
    if method=='POST' and re.fullmatch(base+r'/accounts/[a-f0-9]{32}/sync',path):return True
    return method=='DELETE' and bool(re.fullmatch(base+r'/accounts/[a-f0-9]{32}',path))


def guest_allowed(method,path,profile):
    """Default deny; direct endpoints and all indirect household tools stay private."""
    if method=='GET' and path=='/v1/display/video':return True  # Provider returns no selection to Guest/Personal.
    if profile['mode']!='guest':return True
    if method=='GET' and path=='/v1/members/available' or method in {'POST','DELETE'} and path=='/v1/member/session':return True
    if profile.get('personal'):
        if personal_google_allowed(method,path):return True
        if method in {'GET','PUT'} and path=='/v1/member/preferences':return True
        if method in {'GET','POST','DELETE'} and path=='/v1/memory' or method in {'PUT','DELETE'} and re.fullmatch('/v1/memory/[a-f0-9]{32}',path):return True
        if method in {'GET','DELETE'} and path=='/v1/chat':return True
    if method=='GET' and path in {'/v1/display/session','/v1/state','/v1/home','/v1/display/home',
            '/v1/display/sources','/v1/display/agenda','/v1/display/presence',
            '/v1/display/music/now-playing','/v1/display/music/settings','/v1/display/alert-settings','/v1/display/alerts'}:return True
    if method=='POST' and re.fullmatch(r'/v1/display/alerts/[a-f0-9]{32}/(?:claim|check|receipt)',path):return True
    if method=='GET' and re.fullmatch(r'/v1/display/cameras/camera\.[a-z0-9_]{1,128}/(?:snapshot|stream)',path):
        return path.split('/')[4] in profile['cameras']
    if method=='POST' and path in {'/v1/timers','/v1/display/home/control'}:return True
    if method in {'DELETE','POST'} and re.fullmatch(r'/v1/timers/[a-f0-9]{32}(?:/(?:ack|snooze))?',path):return True
    if profile['conversation']:
        if method=='GET' and path in {'/v1/display/voice','/v1/display/local-voice','/v1/chat/activity'}:return True
        if method=='POST' and (path in {'/v1/chat','/v1/display/voice'} or
                re.fullmatch(r'/v1/(?:chat/activity|display/voice)/[a-f0-9]{32}/stop',path)):return True
    return False


def home_view(snapshot,profile):
    if profile['mode']!='guest':return snapshot
    result=deepcopy(snapshot);items=[]
    for item in result['devices']:
        grant=profile['home_devices'].get(item['entity_id'])
        if grant is None:continue
        if grant=='read':item['access']='read'
        items.append(item)
    result['devices']=items;result['areas']=sorted({item['area'] for item in items if item['area']})
    result['counts']={'total':len(items),'available':sum(bool(i['available']) for i in items),
                      'unavailable':sum(not i['available'] for i in items),'without_area':sum(not i['area'] for i in items)}
    result['control_access']='selected_devices' if any(i['access']=='control' for i in items) else 'read_only'
    return result


class ScopedSources:
    """Intersect every read with the latest global and display grants, including streams."""
    def __init__(self,store,profile):self.store,self.profile=store,profile

    def snapshot(self):
        state=self.store.snapshot();profile=self.profile()
        if profile['mode']!='guest':return state
        selected=state['sources']
        for key in ('calendars','cameras','presence_sensors'):
            selected[key]=[entity for entity in selected[key] if entity in profile[key]]
        selected['writable_calendars']=[];selected['managed_calendars']=[];selected['doorbells']=[]
        return state


class GuestSettings:
    """Keep the configured provider, but never load private personality or Hermes state."""
    def __init__(self,store):self.store,self.path,self.protector=store,None,store.protector
    @property
    def revision(self):return self.store.revision
    def snapshot(self):
        from .settings import PERSONALITY
        settings,keys,revision=self.store.snapshot()
        return settings.model_copy(update={'agent_runtime':'direct','memory_enabled':False,
            'personality':PERSONALITY+' This is a guest conversation. No household memory, calendars, lists, home tools or private files are available. Use the approved on-screen controls for home actions.'}),keys,revision


class ProfileAgent:
    """Use a separate volatile conversation store and provider-only path for guests."""
    def __init__(self,household,guest,displays,home=None):
        self.household,self.guest,self.displays,self.home=household,guest,displays,home
        self.personal=None
    def respond(self,text,session='device',lookup=False,**kwargs):
        before=self.displays.profile_for(session);profile=before['profile']
        if profile.get('personal') and self.personal:
            if not profile['conversation']:raise HTTPException(403,'Conversation is not shared with this display')
            result=self.personal.respond(text,session,lookup,before=before,**kwargs)
        elif profile['mode']=='guest':
            if not profile['conversation']:raise HTTPException(403,'Conversation is not shared with this display')
            result=None
            from .lookup import lookup_request
            if self.home and not lookup and not lookup_request(text):
                result=self.home.respond(text,session,before,allow_home=kwargs.get('allow_home_actions',False),cancel=kwargs.get('cancel'))
            kwargs.update(allow_home_actions=False,calendar_review=False)
            if result is None:result=self.guest.respond(text,session,lookup,**kwargs)
        else:result=self.household.respond(text,session,lookup,**kwargs)
        if self.displays.profile_for(session)!=before:raise HTTPException(409,'Display access changed during the reply')
        return {**result,'access_revision':before['profile_revision']}
