"""Shared contract for Echo's home visibility and explicit device control grants."""
import copy
import hashlib
import json
import re

CONTROL_DOMAINS = {'light','switch','climate','media_player','scene'}


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != {'default_access', 'devices'}:
        raise ValueError('Invalid home access settings')
    if value['default_access'] not in ('read', 'hidden') or not isinstance(value['devices'], dict) or len(value['devices']) > 1000:
        raise ValueError('Invalid home access settings')
    for entity, item in value['devices'].items():
        if not isinstance(entity, str) or not re.fullmatch(r'(light|switch|climate|media_player|cover|fan|scene|weather)\.[a-z0-9_]{1,200}', entity):
            raise ValueError('Invalid home device')
        if not isinstance(item, dict) or set(item) != {'access', 'room'} or item['access'] not in ('read', 'hidden', 'control'):
            raise ValueError('Invalid home device access')
        if item['access']=='control' and entity.split('.')[0] not in CONTROL_DOMAINS:
            raise ValueError('Control is not supported for that device type')
        room = item['room']
        if not isinstance(room, str) or len(room) > 60 or room != room.strip() or any(ord(c) < 32 for c in room):
            raise ValueError('Use a room name of at most 60 characters')
    return copy.deepcopy(value)


def policy_hash(value):
    return hashlib.sha256(json.dumps(validate_policy(value), sort_keys=True).encode()).hexdigest()


def apply_policy(snapshot, policy, *, management=False):
    policy = validate_policy(policy)
    result = copy.deepcopy(snapshot)
    items = []
    for item in result['devices']:
        rule = policy['devices'].get(item['entity_id'], {'access': policy['default_access'], 'room': ''})
        item['access'] = rule['access']
        item['ha_area'] = item['area']
        item['area'] = rule['room'] or item['area']
        item['area_source'] = 'echo' if rule['room'] else 'home_assistant' if item['area'] else 'unassigned'
        item['control_supported'] = item['domain'] in CONTROL_DOMAINS
        if management or rule['access'] in {'read','control'}:
            items.append(item)
    result['devices'] = items
    # The agent sees only rooms represented by permitted devices.
    result['areas'] = sorted({x['area'] for x in items if x['area']})
    result['counts'] = {'total': len(items), 'available': sum(x['available'] for x in items),
                        'unavailable': sum(not x['available'] for x in items),
                        'without_area': sum(x['area'] is None for x in items)}
    result['control_access'] = 'selected_devices' if any(x['access']=='control' for x in items) else 'read_only'
    return result
