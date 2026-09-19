"""Bounded home actions with per-request authority and fresh state readback.

Scopes exist only in memory. Ending or cancelling a conversation revokes new
actions, including from a Hermes run whose admission/stop acknowledgement was
lost. An already admitted HA request cannot be undone by cancellation. Each
distinct command is sent at most once per scope, even after an ambiguous error.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass,field
import hashlib
import json
import math
from threading import Lock,RLock
import time
from uuid import uuid4
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .home import HomeUnavailable
from .home_catalog import FIELDS
from .home_access import HomeAccessUnavailable


class ActionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,str_max_length=220,allow_inf_nan=False)
    request_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    entity_id:str=Field(pattern=r'^(light|switch|climate|media_player|scene)\.[a-z0-9_]{1,200}$')
    action:Literal['turn_on','turn_off','brightness','color_temperature','color','temperature','temperature_range','mode',
                   'play','pause','stop','volume','mute','next','previous','activate']
    value:float|int|bool|str|dict[str,float]|None=None
    unit:Literal['°C','°F']|None=None


def number(value,minimum,maximum):
    if type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=maximum:
        raise ValueError('Value is outside the supported range')
    return value


def plan(command,state,bridge):
    """Return fixed service/data and an observed-state predicate; never arbitrary HA calls."""
    domain=command.entity_id.split('.')[0];action=command.action;value=command.value
    attrs=state['attributes'];data={'entity_id':command.entity_id}
    modes=attrs.get('supported_color_modes',[])
    if not isinstance(modes,list) or any(not isinstance(x,str) for x in modes):modes=[]
    if domain!='climate' and command.unit is not None:raise ValueError('Units apply only to climate temperature')
    def equals(key,target,tolerance=0):
        def test(current):
            actual=current.get('attributes',{}).get(key)
            if tolerance:return type(actual) in (int,float) and abs(actual-target)<=tolerance
            return type(actual) is type(target) and actual==target
        return test
    if domain in {'light','switch'} and action in {'turn_on','turn_off'}:
        if value is not None:raise ValueError('Power actions take no value')
        return domain,action,data,lambda current:current['state']==('on' if action=='turn_on' else 'off')
    if domain=='light' and action=='brightness':
        percent=number(value,0,100)
        if not set(modes) & {'brightness','color_temp','hs','xy','rgb','rgbw','rgbww','white'}:
            raise ValueError('This light does not report brightness support')
        data['brightness_pct']=percent
        expected=round(percent*255/100)
        return domain,'turn_on',data,lambda current:(current['state']=='off' if percent==0 else
            current['state']=='on' and equals('brightness',expected,3)(current))
    if domain=='light' and action=='color_temperature':
        if 'color_temp' not in modes:raise ValueError('This light does not report color-temperature support')
        low,high=attrs.get('min_color_temp_kelvin'),attrs.get('max_color_temp_kelvin')
        number(low,1000,20000);number(high,low,20000)
        data['color_temp_kelvin']=number(value,low,high)
        return domain,'turn_on',data,lambda current:current['state']=='on' and equals('color_temp_kelvin',value,100)(current)
    if domain=='light' and action=='color':
        import re
        if not set(modes)&{'hs','xy','rgb','rgbw','rgbww'} or not isinstance(value,str) or not re.fullmatch('#[0-9a-fA-F]{6}',value):
            raise ValueError('Choose a hex color on a light that reports color support')
        rgb=[int(value[i:i+2],16) for i in (1,3,5)]; data['rgb_color']=rgb
        def observed_color(current):
            actual=current.get('attributes',{}).get('rgb_color')
            return current['state']=='on' and isinstance(actual,(list,tuple)) and len(actual)==3 and all(type(a) in (int,float) and abs(a-b)<=8 for a,b in zip(actual,rgb))
        return domain,'turn_on',data,observed_color
    if domain=='climate' and action=='mode':
        modes=attrs.get('hvac_modes')
        if command.unit is not None or not isinstance(modes,list) or not isinstance(value,str) or value not in modes:
            raise ValueError('Choose a reported thermostat mode')
        data['hvac_mode']=value
        return domain,'set_hvac_mode',data,lambda current:current['state']==value
    if domain=='climate' and action=='temperature':
        unit=bridge._request('GET','/api/config').get('unit_system',{}).get('temperature')
        if unit not in {'°C','°F'} or command.unit!=unit:raise ValueError('Specify the thermostat temperature unit explicitly')
        low,high=attrs.get('min_temp'),attrs.get('max_temp')
        number(low,-100,300);number(high,low,300);number(value,low,high)
        if attrs.get('temperature') is None:raise ValueError('This thermostat does not report a single target temperature')
        step=attrs.get('target_temp_step',.5);number(step,.1,10)
        data['temperature']=value
        return domain,'set_temperature',data,equals('temperature',value,max(.1,step/2))
    if domain=='climate' and action=='temperature_range':
        unit=bridge._request('GET','/api/config').get('unit_system',{}).get('temperature')
        if state['state']!='heat_cool' or unit not in {'°C','°F'} or command.unit!=unit:
            raise ValueError('Range targets require heat/cool mode and the current temperature unit')
        if not isinstance(value,dict) or set(value)!={'low','high'}: raise ValueError('Specify both low and high targets')
        low,high=attrs.get('min_temp'),attrs.get('max_temp'); number(low,-100,300); number(high,low,300)
        target_low=number(value['low'],low,high); target_high=number(value['high'],target_low,high)
        if target_low>=target_high: raise ValueError('The low target must be below the high target')
        data.update(target_temp_low=target_low,target_temp_high=target_high)
        return domain,'set_temperature',data,lambda current:equals('target_temp_low',target_low,.1)(current) and equals('target_temp_high',target_high,.1)(current)
    if domain=='media_player':
        supported=attrs.get('supported_features',0)
        masks={'pause':1,'volume':4,'mute':8,'previous':16,'next':32,'turn_on':128,'turn_off':256,'play':16384,'stop':4096}
        if type(supported) is not int or action not in masks or not supported&masks[action]:raise ValueError('This player does not report that action')
        service={'volume':'volume_set','mute':'volume_mute','play':'media_play','pause':'media_pause',
                 'stop':'media_stop','next':'media_next_track','previous':'media_previous_track'}.get(action,action)
        if action=='volume':
            data['volume_level']=number(value,0,100)/100
            return domain,service,data,equals('volume_level',data['volume_level'],.015)
        if action=='mute':
            if type(value) is not bool:raise ValueError('Mute requires true or false')
            data['is_volume_muted']=value
            return domain,service,data,equals('is_volume_muted',value)
        if value is not None:raise ValueError('This action takes no value')
        states={'play':{'playing'},'pause':{'paused'},'stop':{'idle','off'},'turn_off':{'off'},'turn_on':{'on','idle','paused','playing'}}
        # Next/previous can repeat the same track; no generic state proves success.
        return domain,service,data,(lambda current:current['state'] in states[action]) if action in states else None
    if domain=='scene' and action=='activate' and value is None:
        return domain,'turn_on',data,None
    raise ValueError('That action is not supported for this device')


@dataclass
class ActionScope:
    id:str
    revision:str
    cancel:object
    deadline:float
    lock:object=field(default_factory=Lock)
    results:dict=field(default_factory=dict)
    overflow:dict|None=None


class HomeActions:
    def __init__(self,bridge,access,*,enabled=True,clock=time.monotonic,sleep=time.sleep):
        self.bridge,self.access,self.enabled=bridge,access,enabled
        self.clock,self.sleep=clock,sleep
        self.lock=RLock();self.scopes={}

    @contextmanager
    def scope(self,allowed,revision,cancel=None):
        scope=ActionScope(uuid4().hex,revision,cancel,self.clock()+60) if allowed and self.enabled else None
        if scope:
            with self.lock:
                if len(self.scopes)>=16:raise HomeAccessUnavailable('Too many home-control requests are active')
                self.scopes[scope.id]=scope
        try:yield scope
        finally:
            if scope:
                with self.lock:self.scopes.pop(scope.id,None)

    def _permitted(self,scope,entity):
        if (scope.id not in self.scopes or self.clock()>=scope.deadline or
                scope.cancel is not None and scope.cancel.is_set()):raise ValueError('The home-control request has ended')
        access=self.access.snapshot()
        if access['revision']!=scope.revision:raise ValueError('Home access changed; start a new request')
        if access['policy']['devices'].get(entity,{}).get('access')!='control':
            raise ValueError('Enable Control for this device on the Devices page first')

    def _state(self,entity):
        value=self.bridge._request('GET','/api/states/'+entity)
        if (not isinstance(value,dict) or value.get('entity_id')!=entity or
                not isinstance(value.get('state'),str) or value['state'] in {'unknown','unavailable'} or not isinstance(value.get('attributes'),dict)):
            raise HomeUnavailable('Device state is unavailable')
        return value

    def execute(self,command):
        with self.lock:scope=self.scopes.get(command.request_id)
        if not scope:return {'status':'denied','error':'No active home-control request'}
        if not scope.lock.acquire(blocking=False):return {'status':'busy','error':'Another home action is in progress'}
        payload=command.model_dump(exclude={'request_id'})
        if type(payload['value']) in (int,float):payload['value']=float(payload['value'])
        key=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        result={'entity_id':command.entity_id,'action':command.action,'value':command.value,
                'unit':command.unit,'status':'unconfirmed','attempted':False}
        def update(**fields):
            with self.lock:result.update(fields)
            return deepcopy(result)
        try:
            with self.lock:
                self._permitted(scope,command.entity_id)
                if key in scope.results:return {**deepcopy(scope.results[key]),'replayed':True}
                if len(scope.results)>=12:raise ValueError('This request reached its 12-action limit')
                scope.results[key]=result
            current=self._state(command.entity_id)
            domain,service,data,confirmed=plan(command,current,self.bridge)
            if confirmed and confirmed(current):
                return update(status='complete',observed=self.public_state(current))
            with self.lock:
                self._permitted(scope,command.entity_id)
                # Admission precedes dispatch. Cancellation cannot undo an admitted action.
                result['attempted']=True
            try:self.bridge._request('POST','/api/services/'+domain+'/'+service,data)
            except HomeUnavailable:pass  # The write may have succeeded; reconcile, never retry it.
            else:
                if confirmed is None:
                    return update(status='accepted')
            if confirmed is None:return update()
            for attempt in range(3):
                try:
                    observed=self._state(command.entity_id)
                    update(observed=self.public_state(observed))
                    if confirmed(observed):return update(status='complete')
                except HomeUnavailable:pass
                if attempt<2:self.sleep(.25)
            return update()
        except (ValueError,HomeAccessUnavailable) as error:
            update(status='denied',error=str(error))
            with self.lock:
                if key not in scope.results:
                    if len(scope.results)<12:scope.results[key]=result
                    else:scope.overflow=result
            return deepcopy(result)
        except (HomeUnavailable,TypeError,KeyError,AttributeError):
            return update(status='unavailable',error='Home device or its reported capabilities are unavailable')
        finally:scope.lock.release()

    def preflight(self,command):
        """Validate a saved routine step without dispatching or consuming its receipt."""
        with self.lock:
            scope=self.scopes.get(command.request_id)
            if not scope: raise ValueError('No active home-control request')
            self._permitted(scope,command.entity_id)
        current=self._state(command.entity_id)
        plan(command,current,self.bridge)

    def receipts(self,scope):
        with self.lock:
            return deepcopy([*scope.results.values(),*([scope.overflow] if scope.overflow else [])]) if scope else []

    @staticmethod
    def public_state(value):
        return {'state':value['state'],'attributes':{k:v for k,v in value['attributes'].items() if k in FIELDS}}
