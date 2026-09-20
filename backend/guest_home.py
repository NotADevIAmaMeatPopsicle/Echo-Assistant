"""Local guest commands over explicitly shared devices; no model or household tools."""
from dataclasses import dataclass
import re

from .home import HomeUnavailable
from .home_access import HomeAccessUnavailable
from .home_actions import HomeActions,ActionRequest
from .home_policy import apply_policy,policy_hash
from .display_profiles import home_view


def normalized(text):
    return re.sub(r'\s+',' ',re.sub(r'[^\w\s]',' ',text.casefold())).strip()


@dataclass
class Intent:
    action:str
    target:str=''
    value:object=None
    unit:str|None=None
    domain:str|None=None


def parse(text):
    """One anchored instruction, with no implied follow-up, scene or arbitrary service."""
    text=re.sub(r'\s+',' ',text.strip().casefold()).rstrip('.?!')
    text=re.sub(r'^(?:(?:please|can you|could you|would you) )+','',text)
    text=re.sub(r',? please$','',text)
    if text in {'list devices','list shared devices','what devices are shared','what devices can i control','what can you control'}:
        return Intent('list')
    match=re.fullmatch(r'(?:turn|switch) (on|off) (.+)',text)
    if match:return Intent('turn_'+match[1],match[2])
    match=re.fullmatch(r'(?:turn|switch) (.+) (on|off)',text)
    if match:return Intent('turn_'+match[2],match[1])
    match=re.fullmatch(r'(?:set|dim) (.+?)(?: brightness)? to (\d{1,3})(?:\s*%| percent)',text)
    if match:
        target=match[1]
        if target.endswith(' volume'):return Intent('volume',target[:-7],int(match[2]),domain='media_player')
        return Intent('brightness',target,int(match[2]),domain='light')
    match=re.fullmatch(r'set (.+?) to (-?\d{1,3}(?:\.\d+)?)(?: degrees?)?\s*(celsius|fahrenheit|°c|°f|c|f)',text)
    if match:return Intent('temperature',match[1],float(match[2]),'°C' if match[3] in {'celsius','°c','c'} else '°F',domain='climate')
    match=re.fullmatch(r'(play|pause|stop|mute|unmute) (.+)',text)
    if match:
        action=match[1]
        return Intent('mute' if action in {'mute','unmute'} else action,match[2],action=='mute' if action in {'mute','unmute'} else None,domain='media_player')
    match=re.fullmatch(r'(?:what is|what’s|what\x27s) (?:the )?(?:state|status) of (.+)',text)
    if not match:match=re.fullmatch(r'(?:is|are) (.+) (?:on|off|playing|paused)',text)
    if match:return Intent('state',match[1])
    return None


def select(items,intent):
    target=normalized(intent.target)
    target=re.sub(r'^the ','',target)
    candidates=[i for i in items if intent.domain is None or i['domain']==intent.domain]
    exact=[i for i in candidates if target in {normalized(i['name']),normalized(i['entity_id'])}]
    if exact:return exact,len(exact)==1
    # Room groups include only explicitly shared lights. A room label grants nothing.
    for item in candidates:
        if item['domain']!='light':continue
        room=normalized(item.get('area') or '')
        if room and target in {room+' lights','lights in '+room,'lights in the '+room}:
            return [i for i in candidates if i['domain']=='light' and normalized(i.get('area') or '')==room],True
    if target in {'lights','all lights','all the lights'}:
        return [i for i in candidates if i['domain']=='light'],True
    domain={'thermostat':'climate','speaker':'media_player','lamp':'light'}.get(target)
    matches=[i for i in candidates if i['domain']==domain] if domain else []
    return matches,len(matches)==1


class ScopedAccess:
    def __init__(self,access,displays,session,expected,require_voice=True):
        self.access,self.displays,self.session,self.expected=access,displays,session,expected
        self.require_voice=require_voice

    def snapshot(self):
        current=self.displays.profile_for(self.session)
        if current!=self.expected:raise HomeAccessUnavailable('Display access changed; ask again after it refreshes.')
        profile=current['profile']
        if profile['mode']!='guest' or self.require_voice and (not profile.get('home_voice',False) or not profile['conversation']):
            raise HomeAccessUnavailable('Guest home voice commands are not enabled.')
        saved=self.access.snapshot();policy={'default_access':'hidden','devices':{}}
        for entity,grant in profile['home_devices'].items():
            rule=saved['policy']['devices'].get(entity,{'access':saved['policy']['default_access'],'room':''})
            if rule['access'] not in {'read','control'}:continue
            policy['devices'][entity]={**rule,'access':'control' if grant==rule['access']=='control' else 'read'}
        # Global changes invalidate a pending command even if this subset is identical.
        return {'policy':policy,'revision':saved['revision']+':'+policy_hash(policy)}


class GuestHome:
    def __init__(self,catalog,actions,displays):self.catalog,self.actions,self.displays=catalog,actions,displays

    def respond(self,text,session,expected,*,allow_home=False,cancel=None):
        intent=parse(text)
        if intent is None:return None
        def reply(text,**fields):return {'status':'complete','capability':'home','text':text,**fields}
        if not expected['profile'].get('home_voice',False):
            return reply('Guest home voice commands are off. Use the shared controls on Rooms, or ask the owner to enable voice commands for this display.')
        scoped=ScopedAccess(self.actions.access,self.displays,session,expected)
        try:
            if cancel is not None and cancel.is_set():return reply('Request stopped.')
            saved=scoped.snapshot()
            inventory=home_view(apply_policy(self.catalog.snapshot(),saved['policy']),expected['profile'])
            if scoped.snapshot()['revision']!=saved['revision']:raise HomeAccessUnavailable('Device access changed. Please ask again.')
            items=inventory['devices']
            if intent.action=='list':
                return reply('Shared here: '+', '.join(i['name']+(' (view only)' if i['access']=='read' else '') for i in items[:12])+('. More are on Rooms.' if len(items)>12 else '.') if items else 'No home devices are shared with this display.')
            targets,clear=select(items,intent)
            if not targets:return reply('I could not match that to a shared device. Use its name from Rooms, or ask “What devices are shared?”')
            if not clear:return reply('That name matches more than one shared device. Choose an individual device on Rooms or use its room name.')
            if any(not i['available'] for i in targets):return reply('A selected shared device is unavailable. No command was sent.')
            if len(targets)>12:return reply('That selects more than twelve devices. Choose a smaller room or an individual device.')
            if intent.action=='state':
                def describe(item):
                    attrs=item['attributes'];detail=''
                    if item['domain']=='climate' and attrs.get('temperature') is not None:detail=', target '+str(attrs['temperature'])+' '+str(attrs.get('temperature_unit') or '')
                    elif item['domain']=='media_player' and type(attrs.get('volume_level')) in (int,float):detail=', volume '+str(round(attrs['volume_level']*100))+' percent'
                    return item['name']+' is '+str(item['state'])+detail
                return reply('; '.join(describe(i) for i in targets)+'.')
            if not allow_home:return reply('Enable “Allow home actions” for this message, or use the shared device controls on Rooms.')
            if any(i['access']!='control' for i in targets):return reply('A selected device is shared for viewing only. No devices were changed.')
            if not self.actions.enabled:return reply('Home actions are disabled on this validation host.')
            actions=HomeActions(self.actions.bridge,scoped,clock=self.actions.clock,sleep=self.actions.sleep)
            with actions.scope(True,saved['revision'],cancel) as scope:
                commands=[ActionRequest(request_id=scope.id,entity_id=i['entity_id'],action=intent.action,value=intent.value,unit=intent.unit) for i in targets]
                for command in commands:actions.preflight(command)
                results=[]
                for command in commands:
                    result=actions.execute(command);results.append(result)
                    if result['status'] not in {'complete','accepted'}:break
                complete=sum(r['status']=='complete' for r in results)
                if complete==len(commands):message='The shared device reports the requested state.' if complete==1 else f'All {complete} shared devices report the requested state.'
                elif all(r['status']=='accepted' for r in results):message='Command accepted. The device does not provide confirmation of that action.'
                else:message=f'{complete} of {len(commands)} shared devices confirmed the requested state. Check Rooms before trying again; a command may already have been sent.'
                return reply(message,home_actions=results)
        except (HomeUnavailable,HomeAccessUnavailable,ValueError):
            return reply('I could not safely apply that request to the shared devices. Check their connection, permissions and supported values on Rooms. No new command was sent.')
