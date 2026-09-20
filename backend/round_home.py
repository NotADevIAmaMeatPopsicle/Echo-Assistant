"""Mini guest cards project only shared entities; buttons use scoped HomeActions."""
import hashlib
import json
from threading import RLock

from fastapi import HTTPException
from .display_profiles import home_view
from .guest_home import ScopedAccess
from .home_actions import ActionRequest,HomeActions
from .home_lights import ROOMS
from .home_policy import apply_policy


def binding(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


class RoundHome:
    def __init__(self,home,catalog,actions,displays,profile):
        self.home,self.catalog,self.actions,self.displays,self.profile=home,catalog,actions,displays,profile
        self.selected='';self.lock=RLock()

    def inventory(self):
        expected=self.profile.snapshot()
        scoped=ScopedAccess(self.actions.access,self.displays,'round',expected,require_voice=False)
        saved=scoped.snapshot();items=home_view(apply_policy(self.catalog.snapshot(),saved['policy']),expected['profile'])['devices']
        if scoped.snapshot()['revision']!=saved['revision']:raise HTTPException(409,'Mini access changed. Refresh the controls.')
        return expected,scoped,saved,items

    def snapshot(self):
        with self.lock:
            expected,_,saved,items=self.inventory()
            revision=binding([expected['profile_revision'],saved['revision']])
            def choose(domain,configured):
                available=[i for i in items if i['domain']==domain]
                return next((i for i in available if i['entity_id']==configured),available[0] if len(available)==1 else None)
            def device(item):
                return {'status':'available' if item and item['available'] else 'unavailable',
                        'state':item['state'] if item else 'unknown','attributes':item['attributes'] if item else {}}
            thermo=choose('climate',self.home.config.entities.get('thermostat'))
            weather=choose('weather',self.home.config.entities.get('weather'))
            choices=sorted((i for i in items if i['domain']=='media_player'),key=lambda i:(i['name'].casefold(),i['entity_id']))[:32]
            selected=next((i for i in choices if i['entity_id']==self.selected),None)
            if not selected:selected=next((i for i in choices if i['entity_id']==self.home.config.entities.get('soundbar')),choices[0] if choices else None)
            chosen=selected['entity_id'] if selected else ''
            speakers={'status':'available','choices':[{'entity_id':i['entity_id'],'name':i['name'],'available':i['available']} for i in choices],
                      'selected':next((n for n,i in enumerate(choices) if i['entity_id']==chosen),-1),'name':selected['name'] if selected else 'Speaker unavailable',
                      'revision':binding([revision,[i['entity_id'] for i in choices]]),'binding':binding([revision,chosen]),'device':device(selected)}
            rooms=[];control_mask=0
            for n,(key,name) in enumerate(ROOMS.items()):
                lights=[i for i in items if i['domain']=='light' and (i.get('area') or '').casefold()==name.casefold()]
                on=sum(i['state']=='on' for i in lights);ready=bool(lights) and all(i['available'] and i['state'] in {'on','off'} for i in lights)
                if lights and all(i['access']=='control' for i in lights):control_mask|=1<<n
                rooms.append({'id':key,'name':name,'entities':[i['entity_id'] for i in lights],'count':len(lights),'on':on,'available':ready,
                              'state':'unassigned' if not lights else 'unavailable' if not ready else 'on' if on==len(lights) else 'mixed' if on else 'off'})
            return {'status':'available','devices':{'thermostat':device(thermo),'soundbar':device(selected),'weather':device(weather)},
                    'lights':{'status':'available','rooms':rooms,'revision':binding([revision,[(r['id'],r['entities']) for r in rooms]])},
                    'speakers':speakers,'thermostat_entity':thermo['entity_id'] if thermo else None,
                    'permissions':{'thermostat':bool(thermo and thermo['access']=='control'),'soundbar':bool(selected and selected['access']=='control'),'lights':control_mask}}

    def commands(self,commands):
        expected,scoped,saved,items=self.inventory()
        known={i['entity_id']:i for i in items}
        if any(known.get(entity,{}).get('access')!='control' for entity,_,_,_ in commands):raise HTTPException(403,'This control is not shared with Echo Mini')
        actions=HomeActions(self.home,scoped,enabled=self.actions.enabled,clock=self.actions.clock,sleep=self.actions.sleep)
        if not actions.enabled:raise HTTPException(409,'Home actions are disabled in validation mode')
        with actions.scope(True,saved['revision']) as scope:
            requests=[ActionRequest(request_id=scope.id,entity_id=entity,action=action,value=value,unit=unit) for entity,action,value,unit in commands]
            for request in requests:actions.preflight(request)
            results=[]
            for request in requests:
                result=actions.execute(request);results.append(result)
                if result['status'] not in {'complete','accepted'}:break
        complete=len(results)==len(commands) and all(r['status']=='complete' for r in results)
        return {'status':'accepted' if len(results)==len(commands) and all(r['status'] in {'complete','accepted'} for r in results) else 'unconfirmed','verified':complete}

    def room(self,name,action,revision):
        with self.profile.lock,self.lock:
            state=self.snapshot()['lights'];room=next((r for r in state['rooms'] if r['id']==name),None)
            if revision!=state['revision'] or not room or not room['available'] or len(room['entities'])>12:raise HTTPException(409,'Room state changed or is unavailable')
            return self.commands([(entity,action,None,None) for entity in room['entities']])

    def select(self,index,revision):
        with self.profile.lock,self.lock:
            state=self.snapshot()['speakers']
            if state['revision']!=revision or not 0<=index<len(state['choices']):raise HTTPException(409,'Speaker list changed')
            self.selected=state['choices'][index]['entity_id'];return {'status':'accepted','selected':index}

    def speaker(self,action,expected_binding):
        mapping={'up':('adjust_volume',.02),'down':('adjust_volume',-.02),'mute':('mute',True),'unmute':('mute',False),
                 'play':('play',None),'pause':('pause',None),'on':('turn_on',None),'off':('turn_off',None)}
        if action not in mapping:raise ValueError('Unsupported speaker action')
        with self.profile.lock,self.lock:
            if self.snapshot()['speakers']['binding']!=expected_binding:raise HTTPException(409,'Selected speaker changed')
            command,value=mapping[action];return self.action('soundbar',command,value)

    def action(self,device,action,value=None,unit=None):
        with self.profile.lock,self.lock:
            state=self.snapshot();attrs=state['devices'].get(device,{}).get('attributes',{})
            if device=='thermostat':entity=state['thermostat_entity']
            elif device=='soundbar':
                speakers=state['speakers'];index=speakers['selected'];entity=speakers['choices'][index]['entity_id'] if index>=0 else None
            else:raise ValueError('Unsupported Mini card')
            if not entity:raise HTTPException(409,'No device is shared with this card')
            if action=='adjust_temperature':
                if type(value) not in (int,float) or abs(value)>1 or type(attrs.get('temperature')) not in (int,float):raise ValueError('Invalid temperature step')
                if unit not in {'°C','°F'} or unit!=attrs.get('temperature_unit'):raise ValueError('Thermostat units changed. Refresh its controls.')
                action,value='temperature',attrs['temperature']+value
            elif action=='set_mode':action='mode'
            elif action=='adjust_volume':
                if type(value) not in (int,float) or abs(value)>.02 or type(attrs.get('volume_level')) not in (int,float):raise ValueError('Invalid volume step')
                action,value='volume',max(0,min(100,(attrs['volume_level']+value)*100))
            return self.commands([(entity,action,value,unit)])
