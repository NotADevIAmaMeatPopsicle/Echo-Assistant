"""Read-only Home Assistant inventory with actual entity/device/area bindings."""
import json
from .home import HomeBridge, HomeUnavailable

DOMAINS = {'light', 'switch', 'climate', 'media_player', 'cover', 'fan', 'scene', 'weather'}
FIELDS = {'brightness', 'color_temp_kelvin', 'color_mode', 'supported_color_modes','rgb_color','target_temp_low','target_temp_high',
          'min_color_temp_kelvin', 'max_color_temp_kelvin', 'min_temp', 'max_temp', 'target_temp_step',
          'current_temperature', 'temperature', 'current_humidity', 'hvac_action',
          'hvac_modes', 'volume_level', 'is_volume_muted', 'media_title',
          'supported_features', 'unit_of_measurement', 'temperature_unit'}


class HomeCatalog:
    def __init__(self, bridge: HomeBridge, registry=None):
        self.bridge = bridge
        self.registry = registry

    def _registries(self):
        if self.registry is not None:
            return self.registry()
        # The sync WebSocket client rejects redirect responses. The validated HA
        # origin is an explicit private IP, and credentials never enter a URL.
        from websockets.sync.client import connect
        url = self.bridge.config.base_url.replace('http://', 'ws://').replace('https://', 'wss://')
        with connect(url + '/api/websocket', open_timeout=3, close_timeout=1, max_size=2_000_000) as ws:
            if json.loads(ws.recv(timeout=3)).get('type') != 'auth_required':
                raise HomeUnavailable('Home registry authentication unavailable')
            ws.send(json.dumps({'type':'auth','access_token':self.bridge.config.token}))
            if json.loads(ws.recv(timeout=3)).get('type') != 'auth_ok':
                raise HomeUnavailable('Home registry authentication rejected')
            result = []
            for identifier, kind in enumerate(('area','device','entity'), 1):
                ws.send(json.dumps({'id':identifier,'type':f'config/{kind}_registry/list'}))
                reply = json.loads(ws.recv(timeout=3))
                if reply.get('id') != identifier or not reply.get('success'):
                    raise HomeUnavailable('Home registry unavailable')
                result.append(reply['result'])
            return result

    def snapshot(self, domain='', area=''):
        if domain and domain not in DOMAINS:
            raise ValueError('Unsupported home device domain')
        states = self.bridge._request('GET', '/api/states')
        if not isinstance(states, list): raise HomeUnavailable('Home inventory unavailable')
        registry_available = True
        try:
            areas, devices, entities = self._registries()
            area_names = {x['area_id']: x['name'] for x in areas if isinstance(x['name'], str)}
            device_areas = {x['id']: x.get('area_id') for x in devices}
            entity_areas = {x['entity_id']: x.get('area_id') or device_areas.get(x.get('device_id')) for x in entities}
        except Exception:
            # State reads remain useful, but never invent a room from a name.
            area_names, device_areas, entity_areas = {}, {}, {}
            registry_available = False
        items = []
        temperature_unit=None
        if any(isinstance(x,dict) and str(x.get('entity_id','')).startswith('climate.') for x in states):
            try:
                unit=self.bridge._request('GET','/api/config').get('unit_system',{}).get('temperature')
                if unit in ('°C','°F'):temperature_unit=unit
            except (HomeUnavailable,TypeError,AttributeError):pass
        for state in states:
            if not isinstance(state, dict): continue
            identifier = state.get('entity_id', '')
            if not isinstance(identifier, str): continue
            kind = identifier.split('.')[0]
            if kind not in DOMAINS or (domain and kind != domain): continue
            attrs = state.get('attributes', {})
            if not isinstance(attrs, dict): attrs = {}
            if kind=='climate' and temperature_unit:attrs={**attrs,'temperature_unit':temperature_unit}
            room = area_names.get(entity_areas.get(identifier))
            if area and (room or '').casefold() != area.casefold(): continue
            name = attrs.get('friendly_name')
            items.append({'entity_id': identifier, 'domain': kind,
                'name': name if isinstance(name,str) else identifier, 'area': room,
                'state': state.get('state'), 'available': state.get('state') not in ('unknown','unavailable'),
                'attributes': {k:v for k,v in attrs.items() if k in FIELDS}})
        return {'status':'available', 'registry_available':registry_available,
                'areas':sorted(area_names.values()), 'devices':items,
                'counts': {'total':len(items), 'available':sum(x['available'] for x in items),
                           'unavailable':sum(not x['available'] for x in items),
                           'without_area':sum(x['area'] is None for x in items)}}

    def state(self, entity_id):
        matches = [x for x in self.snapshot()['devices'] if x['entity_id'] == entity_id]
        if not matches: raise ValueError('Device is not present in the home inventory')
        return matches[0]
