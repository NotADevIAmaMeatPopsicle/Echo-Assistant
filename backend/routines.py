"""Explicitly saved home routines. Fixed targets, fresh grants, no scheduling or retries."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .home_actions import ActionRequest
from .home import HomeUnavailable
from .home_access import HomeAccessUnavailable


class RoutineUnavailable(RuntimeError):
    pass


class RoutineConflict(ValueError):
    pass


class RoutineStep(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False, str_max_length=220)
    entity_id: str = Field(pattern=r'^(light|switch|climate|media_player|scene)\.[a-z0-9_]{1,200}$')
    action: Literal['turn_on','turn_off','brightness','color_temperature','temperature','mode',
                    'play','pause','stop','volume','mute','activate']
    value: float | int | bool | str | None = None
    unit: Literal['°C','°F'] | None = None


def normalized_name(name):
    if not isinstance(name,str) or not 1 <= len(name.strip()) <= 60 or any(ord(c)<32 for c in name):
        raise ValueError('Use a routine name between 1 and 60 characters.')
    return ' '.join(name.split()).strip(' .!?')


def routine_request(text):
    text = text.strip().rstrip('.!?')
    save = re.fullmatch(r'(?:please\s+)?(?:remember|save)\s+(?:this|these actions)\s+as\s+(?:a routine (?:called|named)\s+)?(.+)', text, re.I)
    if save: return 'save', ' '.join(save[1].split()).strip(' .!?')
    run = re.fullmatch(r'(?:please\s+)?(?:run|start|activate)\s+(?:the\s+)?routine\s+(.+)', text, re.I)
    if run: return 'run', ' '.join(run[1].split()).strip(' .!?')
    if re.fullmatch(r'(?:please\s+)?(?:list|show)(?: my)? routines',text,re.I): return 'list',''
    return None


def revision(item):
    return hashlib.sha256(json.dumps(item,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class RoutineStore:
    def __init__(self, root, protector):
        self.path = Path(root)/'local/echo-routines.json' if root else None
        self.protector = protector
        self.lock = RLock(); self.items = []; self.error = False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size > 250000: raise ValueError()
                envelope = json.loads(self.path.read_text(encoding='utf-8'))
                if envelope['version'] != 1: raise ValueError()
                items = json.loads(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
                if not isinstance(items,list) or len(items)>32: raise ValueError()
                ids=set(); names=set()
                for item in items:
                    if set(item)!={'id','name','steps'} or not re.fullmatch('[0-9a-f]{32}',item['id']): raise ValueError()
                    name,steps = self.validate(item['name'],item['steps'])
                    if name != item['name'] or steps != item['steps'] or item['id'] in ids or name.casefold() in names: raise ValueError()
                    ids.add(item['id']);names.add(name.casefold())
                self.items = items
            except (OSError,ValueError,TypeError,KeyError,RuntimeError): self.error = True

    @staticmethod
    def validate(name, steps):
        name = normalized_name(name)
        if not name or not isinstance(steps,list) or not 1<=len(steps)<=12:
            raise ValueError('A routine needs a name and between 1 and 12 actions.')
        steps = [RoutineStep.model_validate(step).model_dump() for step in steps]
        for step in steps:
            if type(step['value']) in (int,float): step['value']=float(step['value'])
        if len({revision(step) for step in steps}) != len(steps):
            raise ValueError('Remove duplicate actions from the routine.')
        return name,steps

    def snapshot(self):
        with self.lock:
            if self.error: raise RoutineUnavailable('Saved routines could not be read. The existing file was preserved.')
            return [{**deepcopy(item),'revision':revision(item)} for item in self.items]

    def get(self, identifier, expected=None):
        with self.lock:
            item=next((item for item in self.snapshot() if item['id']==identifier),None)
            if item is None: raise KeyError('Routine not found')
            if expected is not None and item['revision']!=expected:
                raise RoutineConflict('This routine changed. Refresh before using it.')
            return item

    def _commit(self, items):
        if self.path:
            temporary=self.path.with_suffix('.tmp')
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                blob=self.protector.encrypt(json.dumps(items,ensure_ascii=False).encode())
                temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(blob).decode()}),encoding='utf-8')
                temporary.replace(self.path)
            except (OSError,RuntimeError): raise RoutineUnavailable('Routines could not be saved. Previous routines are unchanged.') from None
        self.items=items

    def save(self,name,steps,identifier=None,expected=None):
        name,steps=self.validate(name,steps)
        with self.lock:
            self.snapshot()
            if identifier: self.get(identifier,expected)
            if any(x['name'].casefold()==name.casefold() and x['id']!=identifier for x in self.items):
                raise RoutineConflict('That routine name already exists. Edit it on the Routines page.')
            if not identifier and len(self.items)>=32: raise ValueError('You can save up to 32 routines.')
            item={'id':identifier or uuid4().hex,'name':name,'steps':steps}
            records=deepcopy(self.items)
            if identifier: records=[item if old['id']==identifier else old for old in records]
            else: records.append(item)
            self._commit(records)
            return {**deepcopy(item),'revision':revision(item)}

    def delete(self,identifier,expected):
        with self.lock:
            self.get(identifier,expected)
            self._commit([item for item in self.items if item['id']!=identifier])


class Routines:
    def __init__(self,store,actions):
        self.store,self.actions=store,actions

    def save(self,name,steps,identifier=None,expected=None):
        name,steps=self.store.validate(name,steps)
        policy=self.actions.access.snapshot()['policy']
        from .home_actions import plan
        for step in steps:
            if policy['devices'].get(step['entity_id'],{}).get('access',policy['default_access'])=='hidden':
                raise ValueError('Unhide this device on Devices before adding it to a routine.')
            command=ActionRequest(request_id='0'*32,**step)
            try: plan(command,self.actions._state(step['entity_id']),self.actions.bridge)
            except HomeUnavailable as error: raise RoutineUnavailable(str(error)) from None
        return self.store.save(name,steps,identifier,expected)

    def from_recent(self,name,messages):
        receipts=messages[-1].get('home_actions',[]) if messages and messages[-1]['role']=='assistant' else []
        if not receipts or any(r.get('status')!='complete' for r in receipts):
            raise ValueError('There are no fully verified home actions in the last reply. Build the routine on the Routines page instead.')
        steps=[{k:r.get(k) for k in ('entity_id','action','value','unit')} for r in receipts]
        return self.save(name,steps)

    def run(self,identifier,expected,*,cancel=None,progress=None):
        receipts=[];scope=None
        try:
            item=self.store.get(identifier,expected)
            access=self.actions.access.snapshot()
            with self.actions.scope(True,access['revision'],cancel) as scope:
                if scope is None: raise ValueError('Home actions are disabled on this host.')
                commands=[ActionRequest(request_id=scope.id,**step) for step in item['steps']]
                if progress: progress('checking')
                # Check every target first, so a known invalid later action sends nothing.
                for command in commands: self.actions.preflight(command)
                for command in commands:
                    if cancel is not None and cancel.is_set(): break
                    if progress: progress('acting')
                    with self.store.lock:
                        self.store.get(identifier,expected)
                        result=self.actions.execute(command)
                    receipts.append(result)
                    if result['status'] not in {'complete','accepted'}: break
            completed=sum(r['status']=='complete' for r in receipts)
            accepted=sum(r['status']=='accepted' for r in receipts)
            stopped=cancel is not None and cancel.is_set()
            status='cancelled' if stopped else 'complete' if completed+accepted==len(commands) else 'unavailable'
            text=(f'Stopped {item["name"]}.' if stopped else f'Finished {item["name"]}.' if status=='complete' else f'Could not finish {item["name"]}.')
            if completed: text+=f' Verified {completed} action'+('s.' if completed!=1 else '.')
            if accepted: text+=f' {accepted} action'+('s were' if accepted!=1 else ' was')+' accepted, but the result is not verified.'
            if status!='complete': text+=' Check the action receipts before trying again.'
            return {'status':status,'capability':'routine','text':text,'home_actions':receipts,'routine_id':identifier}
        except (ValueError,KeyError,HomeUnavailable,HomeAccessUnavailable,RoutineUnavailable) as error:
            if scope: receipts=self.actions.receipts(scope)
            return {'status':'unavailable','capability':'routine','text':str(error),'home_actions':receipts}
