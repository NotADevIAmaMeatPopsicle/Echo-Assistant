"""Explicit touch controls for the owner's four room cards, independent of agent grants."""
import hashlib
import json
import re
from threading import Lock
from .home import HomeUnavailable
from .home_policy import apply_policy

ROOMS = {'bedroom':'Bedroom', 'living_room':'Living Room', 'dining_room':'Dining Room', 'patio':'Patio'}


class RoomLights:
    def __init__(self, bridge, catalog, access):
        self.bridge, self.catalog, self.access = bridge, catalog, access
        self.lock = Lock()

    def light_action(self, entity, action, revision):
        """An owner's explicit single-bulb action for locating and assigning lights."""
        if not re.fullmatch(r'light\.[a-z0-9_]{1,200}', entity) or action not in ('turn_on','turn_off'):
            raise ValueError('Choose a light and an explicit on or off action')
        if not self.lock.acquire(blocking=False):
            raise HomeUnavailable('A light request is already running')
        try:
            saved = self.access.snapshot()
            if saved['revision'] != revision:
                raise ValueError('Device settings changed. Refresh before controlling this light.')
            inventory = apply_policy(self.catalog.snapshot(domain='light'), saved['policy'])
            selected = next((d for d in inventory['devices'] if d['entity_id']==entity and d['domain']=='light'), None)
            if selected is None:
                raise ValueError('This light is hidden or no longer in Home Assistant')
            state = self.bridge._request('GET','/api/states/'+entity)
            if not selected['available'] or state.get('state') not in ('on','off'):
                raise HomeUnavailable('This light is unavailable. Refresh before trying again.')
            target = action[5:]
            result = {'entity_id':entity,'action':action,'status':'already_set','verified':True,'state':target}
            # A click permits only this bulb and never enables the AI's Control grant.
            with self.access.lock:
                if self.access.snapshot()['revision'] != revision:
                    raise ValueError('Device settings changed. Refresh before controlling this light.')
                if state['state']==target:
                    return result
                try:
                    self.bridge._request('POST','/api/services/light/'+action,{'entity_id':entity})
                except HomeUnavailable:
                    raise HomeUnavailable('The light request was not confirmed. Refresh its state before trying again.') from None
            result.update(status='accepted',verified=False,state=None)
            try:
                observed = self.bridge._request('GET','/api/states/'+entity).get('state')
                if observed in ('on','off'):
                    result.update(state=observed,verified=observed==target)
            except HomeUnavailable:
                pass
            return result
        finally:
            self.lock.release()

    def snapshot(self):
        policy = self.access.snapshot()
        inventory = apply_policy(self.catalog.snapshot(domain='light'), policy['policy'])
        rooms = []
        for key, name in ROOMS.items():
            devices = sorted((d for d in inventory['devices'] if d['domain']=='light'
                              and (d.get('area') or '').casefold()==name.casefold()), key=lambda d:d['entity_id'])
            known = sum(d.get('available') and d.get('state') in ('on','off') for d in devices)
            on = sum(d.get('state')=='on' for d in devices)
            state = ('unassigned' if not devices else 'unavailable' if known!=len(devices)
                     else 'on' if on==len(devices) else 'mixed' if on else 'off')
            rooms.append({'id':key, 'name':name, 'state':state, 'count':len(devices), 'on':on,
                          'available':bool(devices) and known==len(devices) and len(devices)<=32,
                          'entities':[d['entity_id'] for d in devices]})
        binding = {'policy':policy['revision'], 'rooms':{r['id']:r['entities'] for r in rooms}}
        revision = hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()
        return {'status':'available', 'revision':revision, 'policy_revision':policy['revision'], 'rooms':rooms}

    def action(self, room, action, revision):
        if room not in ROOMS or action not in ('turn_on','turn_off'):
            raise ValueError('Unsupported room light action')
        if not self.lock.acquire(blocking=False):
            raise HomeUnavailable('A room light request is already running')
        try:
            current = self.snapshot()
            if current['revision']!=revision:
                raise ValueError('Room assignments changed. Refresh before using this button.')
            selected = next(r for r in current['rooms'] if r['id']==room)
            if not selected['available']:
                raise HomeUnavailable('Assign this room and wait for all its lights to be available')
            # Send an explicit state once; retrying a toggle can reverse the user's intent.
            with self.access.lock:
                if self.access.snapshot()['revision']!=current['policy_revision']:
                    raise ValueError('Room assignments changed. Refresh before using this button.')
                self.bridge._request('POST','/api/services/light/'+action,{'entity_id':selected['entities']})
            verified = False
            try:
                states = [self.bridge._request('GET','/api/states/'+entity) for entity in selected['entities']]
                verified = all(s.get('state')==action[5:] for s in states)
            except HomeUnavailable: pass
            return {'status':'accepted','room':room,'action':action,'verified':verified}
        finally:
            self.lock.release()
