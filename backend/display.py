"""Live device home state and bounded touch actions, separate from speech work."""
import math
import re
import time

HVAC_MODES = ('off', 'heat', 'cool', 'auto', 'heat_cool', 'dry', 'fan_only')
WEATHER_LABELS = {'clear-night':'Clear_night', 'cloudy':'Cloudy', 'exceptional':'Exceptional',
    'fog':'Fog', 'hail':'Hail', 'lightning':'Thunderstorms', 'lightning-rainy':'Thunderstorms',
    'partlycloudy':'Partly_cloudy', 'pouring':'Heavy_rain', 'rainy':'Rain', 'snowy':'Snow',
    'snowy-rainy':'Rain_and_snow', 'sunny':'Sunny', 'windy':'Windy', 'windy-variant':'Windy'}

def number(value, default=0):
    return value if type(value) in {int, float} and math.isfinite(value) else default


def home_lines(snapshot):
    devices = snapshot.get("devices", {})
    thermo = devices.get("thermostat", {})
    attrs = thermo.get("attributes", {})
    unit = attrs.get("temperature_unit", "")
    if not isinstance(unit, str): unit = ''
    ready = (thermo.get("status") == "available" and unit in {"°F", "°C"}
             and all(type(attrs.get(k)) in {int, float} and math.isfinite(attrs[k])
                     for k in ("current_temperature", "temperature", "min_temp", "max_temp")))
    mode = thermo.get("state", "unknown")
    if mode not in {"off", "heat", "cool", "auto", "heat_cool", "dry", "fan_only"}: mode = "unknown"
    lines = [f"HOME_TEMP {int(ready)} {number(attrs.get('current_temperature')):g} "
             f"{number(attrs.get('temperature')):g} {unit[-1:] or '-'} {mode} "
             f"{number(attrs.get('min_temp')):g} {number(attrs.get('max_temp')):g}\n"]
    modes = attrs.get('hvac_modes', [])
    mask = sum(1 << i for i, value in enumerate(HVAC_MODES)
               if isinstance(modes, list) and value in modes)
    lines.append(f"HOME_MODES {int(thermo.get('status') == 'available')} {mask}\n")
    sound = devices.get("soundbar", {})
    attrs = sound.get("attributes", {})
    state = sound.get("state", "unknown")
    if state not in {"off", "on", "idle", "playing", "paused", "standby", "buffering"}: state = "unknown"
    features = attrs.get("supported_features", 0)
    features = features if type(features) is int and 0 <= features <= 0x7fffffff else 0
    volume = attrs.get('volume_level')
    volume = round(volume * 100) if type(volume) in {int, float} and math.isfinite(volume) and 0 <= volume <= 1 else -1
    muted = attrs.get('is_volume_muted')
    lines.append(f"HOME_SOUND {int(sound.get('status') == 'available')} {state} "
                 f"{volume} {features} {int(muted) if type(muted) is bool else -1}\n")
    weather = devices.get('weather', {}); attrs = weather.get('attributes', {})
    temperature, unit, humidity = attrs.get('temperature'), attrs.get('temperature_unit'), attrs.get('humidity')
    if not isinstance(unit, str): unit = '-'
    ready = (weather.get('status') == 'available' and unit in {'°C', '°F'}
             and type(temperature) in {int, float} and math.isfinite(temperature))
    humidity = round(humidity) if type(humidity) in {int, float} and math.isfinite(humidity) and 0 <= humidity <= 100 else -1
    state = weather.get('state')
    condition = WEATHER_LABELS.get(state, 'Unknown_conditions') if isinstance(state, str) else 'Unknown_conditions'
    lines.append(f"HOME_WEATHER {int(ready)} {number(temperature):g} {unit[-1] if unit in {'°C', '°F'} else '-'} {humidity} {condition}\n")
    lights = snapshot.get('lights', {})
    revision = lights.get('revision','')
    masks = [0,0,0,0]
    if lights.get('status')=='available' and re.fullmatch('[a-f0-9]{64}',revision):
        for i, key in enumerate(('bedroom','living_room','dining_room','patio')):
            room = next((r for r in lights.get('rooms',[]) if r.get('id')==key),{})
            for j, flag in enumerate((room.get('available'),room.get('on',0)>0,room.get('state')=='mixed',room.get('count',0)>0)):
                if flag:masks[j] |= 1<<i
    else: revision='0'*64
    lines.append('HOME_LIGHTS '+' '.join(map(str,masks))+' '+revision+'\n')
    speakers=snapshot.get('speakers',{})
    clean=lambda s:re.sub(r'[^a-zA-Z0-9 .\-]','',str(s))[:44].strip().replace(' ','_') or 'Speaker'
    if speakers.get('status')=='available' and re.fullmatch('[a-f0-9]{64}',speakers.get('revision','')):
        choices=speakers['choices'][:32];revision=speakers['revision']
        lines.append(f"HOME_SELECTED {speakers['binding']} {clean(speakers['name'])}\n")
        lines.append(f"HOME_SPEAKERS {revision} {len(choices)} {speakers['selected']}\n")
        for i,speaker in enumerate(choices):
            lines.append(f"HOME_SPEAKER {revision} {i} {int(bool(speaker['available']))} {clean(speaker['name'])}\n")
    else:
        lines.append('HOME_SELECTED '+'0'*64+' Speaker_unavailable\n')
        lines.append('HOME_SPEAKERS '+'0'*64+' 0 -1\n')
    permissions=snapshot.get('permissions',{'thermostat':bool(thermo),'soundbar':bool(sound),'lights':15 if lights.get('status')=='available' else 0})
    lines.append(f"HOME_PERMS {int(bool(permissions.get('thermostat')))} {int(bool(permissions.get('soundbar')))} {int(permissions.get('lights',0))&15}\n")
    return lines


class HomeDisplay:
    def __init__(self, client, worker, write, clock=time.monotonic):
        self.client, self.worker, self.write, self.clock = client, worker, write, clock
        self.poll = self.action = None
        self.action_request = None
        self.next_poll = 0.
        self.unit = None

    def _get(self):
        response = self.client.get('/v1/home'); response.raise_for_status()
        return response.json()

    def _act(self, device, action, value=None, unit=None):
        response = self.client.post(f'/v1/home/{device}/actions', json={'action': action, 'value': value, 'unit': unit})
        response.raise_for_status()
        return response.json()

    def _ack(self, request, status):
        if request is not None:
            self.write(f'HOME_ACK {request} {status}\n'.encode('ascii'))
        else:
            # Earlier firmware still uses the untagged protocol and text result.
            message = {'pending':'Sending request...', 'accepted':'Request accepted',
                       'failed':'Request failed', 'unavailable':'Device unavailable',
                       'busy':'Busy - please wait'}[status]
            self.write(f'HOME_RESULT {message}\n'.encode('ascii'))

    def _light(self, room, action, revision):
        response=self.client.post(f'/v1/home/rooms/{room}/actions',json={'action':'turn_'+action,'revision':revision})
        response.raise_for_status()
        return response.json()

    def _speaker(self,selection,value,binding):
        body={'index':int(value),'revision':binding} if selection else {'action':value,'binding':binding}
        response=self.client.post('/v1/home/speakers/'+('select' if selection else 'control'),json=body)
        response.raise_for_status();return response.json()

    def receive(self, line):
        speaker=re.fullmatch(r'EVENT speaker_(select|action)=(\d{1,2}|up|down|mute|unmute|play|pause|on|off) request=([0-9]{1,10}) binding=([a-f0-9]{64})',line)
        if speaker:
            selection=speaker[1]=='select';value=speaker[2];request=int(speaker[3])
            if not 1<=request<=0xffffffff or (selection and (not value.isdigit() or int(value)>31)) or (not selection and value.isdigit()):return
            if self.action:
                self._ack(request,'pending' if request==self.action_request else 'busy');return
            self.action_request=request;self.action=self.worker.submit(self._speaker,selection,value,speaker[4])
            self._ack(request,'pending');return
        light=re.fullmatch(r'EVENT light_action=(bedroom|living_room|dining_room|patio):(on|off) request=([0-9]{1,10}) binding=([a-f0-9]{64})',line)
        if light:
            request=int(light[3])
            if not 1<=request<=0xffffffff:return
            if self.action:
                self._ack(request,'pending' if request==self.action_request else 'busy');return
            self.action_request=request
            self.action=self.worker.submit(self._light,light[1],light[2],light[4])
            self._ack(request,'pending');return
        match = re.fullmatch(r'EVENT home_action=(temp_up|temp_down|mode_(?:off|heat|cool|auto|heat_cool|dry|fan_only)|sound_(?:play|pause|on|off|up|down|mute|unmute))(?: request=([0-9]{1,10}))?', line)
        if not match: return
        request = int(match[2]) if match[2] is not None else None
        if request is not None and not 1 <= request <= 0xffffffff: return
        if self.action:
            self._ack(request, 'pending' if request is not None and request == self.action_request else 'busy'); return
        action = match[1]
        if action.startswith('temp_'):
            if self.unit not in {'°F', '°C'}:
                if request is None: self.write(b'HOME_RESULT Temperature unavailable\n')
                else: self._ack(request, 'unavailable')
                return
            step = 1 if self.unit == '°F' else .5
            self.action = self.worker.submit(self._act, 'thermostat', 'adjust_temperature',
                step if action == 'temp_up' else -step, self.unit)
        elif action.startswith('mode_'):
            self.action = self.worker.submit(self._act, 'thermostat', 'set_mode', action[5:])
        elif action in {'sound_up', 'sound_down'}:
            self.action = self.worker.submit(self._act, 'soundbar', 'adjust_volume', .02 if action == 'sound_up' else -.02)
        elif action in {'sound_mute', 'sound_unmute'}:
            self.action = self.worker.submit(self._act, 'soundbar', 'mute', action == 'sound_mute')
        else:
            command = {'sound_play': 'play', 'sound_pause': 'pause', 'sound_on': 'turn_on', 'sound_off': 'turn_off'}[action]
            self.action = self.worker.submit(self._act, 'soundbar', command)
        self.action_request = request
        self._ack(request, 'pending')

    def pump(self):
        now = self.clock()
        if self.action and self.action.done():
            try:
                result = self.action.result()
                status = 'accepted' if result.get('status') == 'accepted' else 'failed'
            except Exception: status = 'unavailable'
            # A state request started before the action can return old values
            # after acknowledgement. Refresh after the mutation instead.
            if self.poll: self.poll.cancel(); self.poll = None
            self._ack(self.action_request, status)
            self.action = None; self.action_request = None; self.next_poll = 0
        if self.poll and self.poll.done():
            try: snapshot = self.poll.result()
            except Exception: snapshot = {}
            self.unit = snapshot.get('devices', {}).get('thermostat', {}).get('attributes', {}).get('temperature_unit')
            for line in home_lines(snapshot): self.write(line.encode('ascii', errors='replace'))
            self.poll = None
        if not self.poll and now >= self.next_poll:
            self.poll = self.worker.submit(self._get); self.next_poll = now+5
