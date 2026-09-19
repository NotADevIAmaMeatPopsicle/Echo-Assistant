"""Interactive, loopback-only display demo. No credentials, integrations, or audio.

Run with Echo's Python environment: python tools/preview_smart_display.py
All changes affect synthetic in-memory data and disappear when this process exits.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from threading import RLock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.preview_web import Preview, DATA, ThreadingHTTPServer, WEB
from backend.core import Assistant
from backend.household import HouseholdStore, HouseholdConflict
from backend.schedules import ScheduleStore,ScheduleConflict
from backend.household_commands import parse as household_request,respond as household_respond
from datetime import date,timedelta
from backend.photos import Photos
from backend.media_presets import MediaPresets
from backend.experiences import Sources


def fixtures():
    data = deepcopy(DATA)
    revision = hashlib.sha256(b'synthetic display').hexdigest()
    data['/health']['display_demo'] = True
    data['/v1/display/session']={'role':'owner'}
    data['/v1/displays']={'items':[]}
    data['/v1/display/sources']={'status':'available','items':[
        {'entity_id':'calendar.household_demo','kind':'calendar','name':'Household · sample','available':True},
        {'entity_id':'camera.porch_demo','kind':'camera','name':'Porch · sample','available':False}]}
    data['/v1/display/source-settings']={'revision':0,'status':'available',
        'sources':{'calendars':['calendar.household_demo'],'cameras':['camera.porch_demo']},
        'items':deepcopy(data['/v1/display/sources']['items'])}
    data['/v1/display/agenda']={'status':'available','unavailable':[], 'events':[
        {'id':'a'*32,'calendar':'calendar.household_demo','calendar_name':'Household · sample','title':'A slow Saturday',
         'start':date.today().isoformat(),'end':(date.today()+timedelta(days=1)).isoformat(),'all_day':True,'location':''},
        {'id':'b'*32,'calendar':'calendar.household_demo','calendar_name':'Household · sample','title':'Dinner with friends',
         'start':date.today().isoformat()+'T18:30:00-04:00','end':date.today().isoformat()+'T20:00:00-04:00','all_day':False,'location':'The neighbourhood café'}]}
    data['/v1/voice'] = {'status':'armed', 'phrases':['hey echo','okay echo'],
        'music':{'status':'paused','title':'A little room to breathe','artist':'Sample track · demo only'}}
    home = data['/v1/home']; home['status'] = 'configured'
    home['lights']['revision'] = revision
    for room, identifier in zip(home['lights']['rooms'], ['bedroom','living_room','dining_room','patio']): room['id'] = identifier
    home['devices'] = {
        'weather':{'status':'available','state':'partly cloudy','attributes':{'temperature':22,'temperature_unit':'°C','humidity':48}},
        'thermostat':{'status':'available','state':'heat','attributes':{'current_temperature':21.5,'temperature':22,'temperature_unit':'°C','min_temp':16,'max_temp':28}},
    }
    home['speakers'] = {'status':'available','revision':revision,'binding':revision,'selected':0,
        'choices':[{'name':'Living room speaker','available':True},{'name':'Kitchen speaker','available':True}],
        'device':{'status':'available','state':'paused','attributes':{'volume_level':.12,'is_volume_muted':False}}}
    home['devices']['soundbar'] = home['speakers']['device']
    data['/v1/display/home']={'revision':revision,'devices':deepcopy(data['/v1/home/devices']['devices'])}
    return data


class DisplayPreview(Preview):
    state = fixtures()
    timers = Assistant()
    household = HouseholdStore(None, None)
    schedules = ScheduleStore(None,None)
    photos = Photos(None,None)
    media = MediaPresets(None,None)
    lock = RLock()

    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        for key, value in {'Content-Type':content_type,'Content-Length':str(len(body)),
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items(): self.send_header(key,value)
        self.end_headers(); self.wfile.write(body)

    def json_reply(self, body, status=200): self.reply(status, json.dumps(body).encode())

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in {'/', '/display'}:
            return self.reply(200, (WEB/'display/index.html').read_bytes(), 'text/html; charset=utf-8')
        assets = {'/assets/display/display.js':('display/display.js','text/javascript'),
                  '/assets/display/planner.js':('display/planner.js','text/javascript'),
                  '/assets/display/devices.js':('display/devices.js','text/javascript'),
                  '/assets/display/pairing.js':('display/pairing.js','text/javascript'),
                  '/assets/display/lists.js':('display/lists.js','text/javascript'),
                  '/assets/display/experiences.js':('display/experiences.js','text/javascript'),
                  '/assets/display/photos.js':('display/photos.js','text/javascript'),
                  '/assets/display/media.js':('display/media.js','text/javascript'),
                  '/assets/display/display.css':('display/display.css','text/css'),
                  '/assets/icon.svg':('icon.svg','image/svg+xml')}
        if path in assets:
            name, mime = assets[path]; return self.reply(200,(WEB/name).read_bytes(),mime)
        with self.lock:
            if path == '/v1/display/photos': return self.json_reply(self.photos.snapshot())
            if path == '/v1/display/media': return self.json_reply(self.media.snapshot())
            if path.startswith('/v1/display/photos/'):
                try:return self.reply(200,self.photos.read(path.rsplit('/',1)[-1]),'image/jpeg')
                except KeyError:return self.json_reply({'detail':'Photo not found'},404)
            if path == '/v1/state': return self.json_reply({'timers':self.timers.timer_states()+self.schedules.timer_states()})
            if path == '/v1/schedules': return self.json_reply(self.schedules.snapshot())
            if path == '/v1/household': return self.json_reply(self.household.snapshot())
            if path in self.state: return self.json_reply(self.state[path])
        if path in {'/settings','/devices','/routines','/tasks','/memory'}:
            return self.reply(200,b'<!doctype html><title>Echo demo</title><h1>Display demo</h1><p>Full workspace links open your existing Echo workspace in a live deployment. This preview loads no account or device configuration.</p><a href="/display">Back to display</a>','text/html')
        return self.json_reply({'detail':'No demo route'},404)

    def do_POST(self):
        # A malicious website cannot make state changes in the loopback demo.
        origin = self.headers.get('Origin')
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or (origin and origin != f'http://127.0.0.1:{self.server.server_port}'):
            return self.json_reply({'detail':'Same-origin demo requests only'},403)
        try:
            size = int(self.headers.get('Content-Length','0'))
            if urlsplit(self.path).path=='/v1/display/photos' and self.command=='POST':
                if not 0<size<=12_000_000:raise ValueError('Choose a photo under 12 MB')
                return self.json_reply(self.photos.add(self.rfile.read(size)))
            if not 0 <= size <= 8192: raise ValueError('Request too large')
            body = json.loads(self.rfile.read(size) or b'{}')
            if not isinstance(body,dict): raise ValueError('Expected an object')
            path = urlsplit(self.path).path
            if path=='/v1/notifications':return self.json_reply(self.schedules.notify(body['title'],body['message'],body.get('announce',False)))
            if path.startswith('/v1/display/photos/') and self.command=='DELETE':
                self.photos.delete(path.rsplit('/',1)[-1]);return self.json_reply({'deleted':True})
            with self.lock:
                result = self.mutate(path,body)
            return self.json_reply(result)
        except (HouseholdConflict,ScheduleConflict) as error: return self.json_reply({'detail':str(error)},409)
        except (ValueError,TypeError,KeyError): return self.json_reply({'detail':'Invalid demo request'},422)

    do_PATCH = do_DELETE = do_PUT = do_POST

    def mutate(self, path, body):
        if path == '/v1/display/source-settings':
            state=self.state[path]
            if body['revision']!=state['revision']:raise ScheduleConflict('Sources changed')
            sources=Sources.model_validate(body['sources']).model_dump()
            identifiers=set(sources['calendars']+sources['cameras'])
            if not identifiers<={i['entity_id'] for i in state['items']}:raise ValueError()
            state.update(sources=sources,revision=state['revision']+1)
            self.state['/v1/display/sources']={'status':'available' if identifiers else 'not_selected','items':[i for i in state['items'] if i['entity_id'] in identifiers]}
            return {'sources':sources,'revision':state['revision']}
        if path == '/v1/display/media': return self.media.save(body)
        if path == '/v1/schedules': return self.schedules.save(body['schedule'],body['revision'])
        if path.startswith('/v1/schedules/'):
            identifier=path.rsplit('/',1)[1]
            if self.command=='DELETE': self.schedules.delete(identifier,body['revision']); return {'deleted':True}
            return self.schedules.save(body['schedule'],body['revision'],identifier)
        if path == '/v1/schedule-preferences': self.schedules.set_quiet(body['quiet'],body['revision']); return self.schedules.snapshot()
        if path.startswith('/v1/schedule-events/'):
            self.schedules.event_action(path.rsplit('/',1)[1],body['action'],body.get('minutes',5)); return self.schedules.snapshot()
        if path == '/v1/household' and self.command == 'POST': return self.household.change(**body)
        if path.startswith('/v1/household/') and self.command in {'PATCH','DELETE'}:
            return self.household.change(identifier=path.rsplit('/',1)[1],delete=self.command=='DELETE',**body)
        if path == '/v1/timers' and self.command == 'POST': return {'id':self.timers.start_timer(body['seconds'],body['label'])}
        if path.startswith('/v1/timers/') and self.command == 'DELETE': return {'dismissed':self.timers.dismiss_timer(path.rsplit('/',1)[1])}
        if path == '/v1/chat':
            command=household_request(body['text'])
            if command: return household_respond(self.household,command)
            return {'text':'This is the interactive display demo. Your live Echo agent will answer here; this preview sends nothing to a model, makes no sound, and controls no home devices.','sources':[]}
        home = self.state['/v1/home']
        if path == '/v1/display/home/control':
            device=next(d for d in self.state['/v1/display/home']['devices'] if d['entity_id']==body['entity_id'])
            if device['access']!='control': raise ValueError('Read-only device')
            action,value=body['action'],body.get('value'); attrs=device['attributes']
            if action in {'turn_on','turn_off'}: device['state']=action[5:]
            elif action=='brightness': attrs['brightness']=round(float(value)*255/100)
            elif action=='color_temperature': attrs['color_temp_kelvin']=value
            elif action=='temperature': attrs['temperature']=value
            elif action=='mode': device['state']=value
            elif action=='volume': attrs['volume_level']=float(value)/100
            elif action=='mute': attrs['is_volume_muted']=value
            elif action in {'play','pause'}: device['state']='playing' if action=='play' else 'paused'
        elif path.startswith('/v1/home/rooms/'):
            room = next(r for r in home['lights']['rooms'] if r['id'] == path.split('/')[4])
            if body['revision'] != home['lights']['revision']: raise ValueError('Stale revision')
            room['state'] = {'turn_on':'on','turn_off':'off'}[body['action']]
            home['lights']['revision'] = hashlib.sha256(json.dumps(home['lights']['rooms']).encode()).hexdigest()
        elif path == '/v1/home/thermostat/actions':
            attrs = home['devices']['thermostat']['attributes']; value = body['value']
            if body['action'] != 'adjust_temperature' or value not in {-1,1}: raise ValueError()
            attrs['temperature'] = max(16,min(28,attrs['temperature']+value))
        elif path == '/v1/home/speakers/select': home['speakers']['selected'] = int(body['index'])
        elif path == '/v1/home/speakers/control':
            attrs = home['speakers']['device']['attributes']; command = body['action']
            if command in {'up','down'}: attrs['volume_level'] = max(0,min(1,attrs['volume_level'] + (.02 if command=='up' else -.02)))
            elif command in {'mute','unmute'}: attrs['is_volume_muted'] = command=='mute'
        elif path == '/v1/music/control':
            music = self.state['/v1/voice']['music']
            if body['action'] == 'toggle': music['status'] = 'paused' if music['status']=='playing' else 'playing'
        elif path.startswith('/v1/routines/') and path.endswith('/run'): pass
        else: raise ValueError('No demo action')
        return {'text':'Demo updated. No real device was changed.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--port',type=int,default=8788)
    args = parser.parse_args()
    DisplayPreview.timers.start_timer(300,'A cup of tea')
    DisplayPreview.household.change(0,kind='shopping',text='Coffee beans')
    DisplayPreview.household.change(1,kind='shopping',text='Something fresh for dinner')
    DisplayPreview.household.change(2,kind='notes',text='A small space for the things that matter.')
    server = ThreadingHTTPServer(('127.0.0.1',args.port),DisplayPreview)
    print(f'Echo display demo: http://127.0.0.1:{args.port}/display (no audio or real devices)',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
