"""Persist the owner's display speaker selection, without changing agent grants."""
import base64
import hashlib
import json
from pathlib import Path
from threading import RLock
import re
from .home import HomeBridge, HomeConfig, HomeUnavailable


class HomeSpeakers:
    def __init__(self, bridge, catalog, root, protector):
        self.bridge,self.catalog,self.protector=bridge,catalog,protector
        self.path=Path(root)/'local/speaker-selection.json' if root else None
        self.lock=RLock();self.saved='';self.error=False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>10000:raise ValueError()
                envelope=json.loads(self.path.read_text())
                if envelope['version']!=1:raise ValueError()
                self.saved=json.loads(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))['entity_id']
                if not re.fullmatch(r'media_player\.[a-z0-9_]{1,200}',self.saved):raise ValueError()
            except (ValueError,KeyError,TypeError,OSError,RuntimeError):self.error=True

    def snapshot(self):
        with self.lock:
            if self.error:raise HomeUnavailable('Saved speaker selection is unreadable; the file was preserved')
            selected=self.saved or self.bridge.config.entities.get('soundbar','')
            devices=self.catalog.snapshot(domain='media_player')['devices']
            choices=sorted((d for d in devices if d['domain']=='media_player'),key=lambda d:(d['name'].casefold(),d['entity_id']))
            # Bound the physical chooser; retain the saved selection if the inventory grows.
            chosen=next((d for d in choices if d['entity_id']==selected),None)
            choices=choices[:32]
            if chosen and chosen not in choices:choices[-1]=chosen
            revision=hashlib.sha256(json.dumps([d['entity_id'] for d in choices]).encode()).hexdigest()
            binding=hashlib.sha256(selected.encode()).hexdigest()
            index=next((i for i,d in enumerate(choices) if d['entity_id']==selected),-1)
            return {'status':'available','revision':revision,'binding':binding,'selected':index,
                    'name':chosen['name'] if chosen else 'Speaker unavailable',
                    'choices':[{'entity_id':d['entity_id'],'name':d['name'],'available':d['available']} for d in choices],
                    'device':{'status':'available' if chosen and chosen['available'] else 'unavailable',
                              'state':chosen['state'] if chosen else 'unknown','attributes':chosen['attributes'] if chosen else {}}}

    def select(self,index,revision):
        with self.lock:
            data=self.snapshot()
            if revision!=data['revision'] or type(index) is not int or not 0<=index<len(data['choices']):
                raise ValueError('Speaker list changed. Refresh before selecting.')
            entity=data['choices'][index]['entity_id']
            if not re.fullmatch(r'media_player\.[a-z0-9_]{1,200}',entity):raise ValueError('Invalid speaker')
            if self.path:
                temporary=self.path.with_suffix('.tmp')
                try:
                    self.path.parent.mkdir(parents=True,exist_ok=True)
                    blob=self.protector.encrypt(json.dumps({'entity_id':entity}).encode())
                    temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(blob).decode()}))
                    temporary.replace(self.path)
                except (OSError,RuntimeError):raise HomeUnavailable('Could not save speaker selection') from None
            self.saved=entity
            return {'status':'accepted','selected':index}

    def action(self,action,binding):
        actions={'up':('adjust_volume',.02),'down':('adjust_volume',-.02),'mute':('mute',True),
                 'unmute':('mute',False),'play':('play',None),'pause':('pause',None),
                 'on':('turn_on',None),'off':('turn_off',None)}
        if action not in actions:raise ValueError('Unsupported speaker action')
        with self.lock:
            state=self.snapshot()
            if binding!=state['binding']:raise ValueError('Selected speaker changed. Refresh its controls.')
            if state['selected']<0 or state['device']['status']!='available':raise HomeUnavailable('Selected speaker unavailable')
            entity=state['choices'][state['selected']]['entity_id']
            original=self.bridge.config
            isolated=HomeBridge(HomeConfig(original.enabled,original.base_url,original.token,{'soundbar':entity}),self.bridge.transport)
            # Same current-capability, range and small-step checks as the original Bose controls.
            command,value=actions[action]
            return isolated.act('soundbar',command,value)
