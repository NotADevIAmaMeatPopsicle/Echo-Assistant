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
import time
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
from backend.calendar_events import CalendarEvent
from backend.calendar_drafts import draft_request
from backend.announcements import Announcements
from backend.announcement_api import Send,Configure
from types import SimpleNamespace
from fastapi import HTTPException
from tools.preview_members import PreviewMembers


def fixtures():
    data = deepcopy(DATA)
    revision = hashlib.sha256(b'synthetic display').hexdigest()
    data['/health']['display_demo'] = True
    data['/v1/display/session']={'role':'owner'}
    data['/v1/calendar/google']={'revision':0,'client_id':'','redirect_uri':'','secret_saved':False,'enabled':False,'accounts':[]}
    data['/v1/calling']={'enabled':False,'allowed':True,'provider':'LiveKit','max_minutes':15,'invite_seconds':120}
    data['/v1/calling/settings']={'revision':0,'enabled':False,'url':'','credentials_saved':False,'allowed_displays':[],'displays':[]}
    data['/v1/display/local-voice']={'supported':False,'phase':'unavailable'}
    data['/v1/display/camera']={'supported':False,'capturing':False,'ready':False}
    data['/v1/display/vision']={'available':False,'provider':'disabled','model':''}
    data['/v1/display/alert-settings']={'supported':False,'status':'Silent preview'}
    data['/v1/displays']={'items':[]}
    data['/v1/members']={'items':[],'limit':16}
    data['/v1/members/available']={'items':[],'session_minutes':15,'supported':True}
    data['/v1/round/profile']={'profile':{'mode':'household','name':'Household','room':'','conversation':True,'home_voice':False,
        'home_devices':{},'calendars':[],'cameras':[],'presence_sensors':[]},'profile_revision':0,'firmware_ready':True}
    data['/v1/display/voice']={'available':False,'mode':'push_to_talk','message':'Silent preview.'}
    data['/v1/display/sources']={'status':'available','items':[
        {'entity_id':'calendar.household_demo','kind':'calendar','name':'Household · sample','available':True,'can_create':True,'writable':True,'can_edit':True,'can_delete':True,'editable':True,'deletable':True},
        {'entity_id':'camera.porch_demo','kind':'camera','name':'Porch · sample','available':True}]}
    data['/v1/display/source-settings']={'revision':0,'status':'available',
        'sources':{'calendars':['calendar.household_demo'],'cameras':['camera.porch_demo'],'writable_calendars':['calendar.household_demo'],'managed_calendars':['calendar.household_demo']},
        'items':deepcopy(data['/v1/display/sources']['items'])}
    data['/v1/display/source-settings']['items'].append({'entity_id':'event.porch_demo','kind':'event','name':'Front door press · sample','available':True})
    data['/v1/display/source-settings']['sources']['doorbells']=[]
    data['/v1/display/source-settings']['sources']['presence_sensors']=[]
    data['/v1/display/source-settings']['items'].append({'entity_id':'binary_sensor.study_demo','kind':'binary_sensor','name':'Study occupancy · sample','available':True,'can_detect_presence':True})
    data['/v1/display/presence']={'status':'not_selected','items':[],'revision':0}
    data['/v1/display/doorbells']={'status':'not_selected','events':[],'revision':0}
    data['/v1/display/sources']['revision']=0
    data['/v1/display/agenda']={'status':'available','unavailable':[], 'events':[
        {'id':'a'*32,'calendar':'calendar.household_demo','calendar_name':'Household · sample','title':'A slow Saturday',
         'start':date.today().isoformat(),'end':(date.today()+timedelta(days=1)).isoformat(),'all_day':True,'location':''},
        {'id':'b'*32,'calendar':'calendar.household_demo','calendar_name':'Household · sample','title':'Dinner with friends',
         'start':date.today().isoformat()+'T18:30:00-04:00','end':date.today().isoformat()+'T20:00:00-04:00','all_day':False,'location':'The neighbourhood café'}]}
    data['/v1/voice'] = {'status':'armed', 'phrases':['hey echo','okay echo'],
        'music':{'status':'paused','title':'A little room to breathe','artist':'Sample track · demo only'}}
    data['/v1/voice']['device']={'volume':2}
    data['/v1/music/now-playing']={'available':True,'status':'paused','title':'Room to breathe',
        'artist':'North Coast','album':'Echo Sessions · sample album','duration_ms':246000,'position_ms':83000,
        'volume':75,'shuffle':False,'repeat':'off','explicit':False,'capabilities':['seek','shuffle','repeat','volume'],
        'artwork':'/v1/music/artwork/'+'a'*64,'open_url':''}
    data['/v1/display/music/now-playing']={**data['/v1/music/now-playing'],'supported':True,'receiver_name':'Echo Display','output_volume':2,'output_configured':True,'artwork':'/v1/display/music/artwork/'+'a'*64}
    data['/v1/display/music/settings']={'supported':False}
    data['/v1/music/groups']={'status':'available','revision':1,'binding':'a'*64,'max_volume':30,'items':[
        {'id':key,'name':name,'provider':'sendspin','available':True,'state':'paused','volume':2,'muted':False,
         'features':['pause','volume_set','volume_mute','set_members'],'members':[],'leader':None,'in_group':False,
         'blocked':False,'compatible':['demo-deck' if key=='demo-mini' else 'demo-mini'],
         'title':'A little room to breathe','artist':'Sample track'} for key,name in [('demo-deck','Echo Deck · sample'),('demo-mini','Echo Mini · sample')]]}
    data['/v1/music/groups/settings']={'revision':1,'config':{'enabled':True,'receivers':[],'url':'http://echo-music:8095','players':['demo-deck','demo-mini'],'max_volume':30},'token_saved':True}
    data['/v1/music/groups/discovery']=deepcopy(data['/v1/music/groups'])
    data['/v1/display/group-music']={'supported':False}
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
    members=PreviewMembers()
    state = fixtures()
    timers = Assistant()
    household = HouseholdStore(None, None)
    schedules = ScheduleStore(None,None)
    photos = Photos(None,None)
    media = MediaPresets(None,None)
    lock = RLock()
    calendar_requests=set()
    for event in state['/v1/display/agenda']['events']:
        event['description']='Sample calendar notes.'
        event['reference']={'calendar':event['calendar'],'uid':event['id'],'on_date':event['start'][:10],'version':'f'*64}
    announcements=Announcements(None,None,SimpleNamespace(snapshot=lambda:[{'id':'a'*32,'name':'Kitchen display · sample'}]),schedules,lambda:{'status':'disconnected'})
    announcements.configure([{'id':'round','room':'Living room','enabled':True},{'id':'a'*32,'room':'Kitchen','enabled':True}],0)

    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        for key, value in {'Content-Type':content_type,'Content-Length':str(len(body)),
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob: https:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items(): self.send_header(key,value)
        self.end_headers(); self.wfile.write(body)

    def json_reply(self, body, status=200): self.reply(status, json.dumps(body).encode())

    def camera_sample(self, stream=False):
        import io,time
        from PIL import Image,ImageDraw
        def frame(tick):
            image=Image.new('RGB',(640,360),'#122b3c');draw=ImageDraw.Draw(image)
            draw.rectangle((240,85,400,350),fill='#286070');draw.rectangle((30,220,160,330),fill='#315440')
            draw.ellipse((450,35,490,75),fill='#d8d9af')
            x=40+(tick*9)%500;draw.ellipse((x,260,x+35,295),fill='#9de9cc')
            draw.text((20,20),'SAMPLE PORCH / LIVE DEMO',fill='#d4eae7')
            draw.text((20,42),'Frame '+str(tick)+' - generated locally',fill='#d4eae7')
            out=io.BytesIO();image.save(out,format='JPEG',quality=80);return out.getvalue()
        if not stream:return self.reply(200,frame(0),'image/jpeg')
        from backend.camera_stream import multipart
        self.send_response(200);self.send_header('Content-Type','multipart/x-mixed-replace; boundary=echo-frame')
        self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.end_headers()
        self.close_connection=True
        try:
            for tick in range(800):
                self.wfile.write(multipart(frame(tick)));self.wfile.flush();time.sleep(.125)
        except (BrokenPipeError,ConnectionResetError):pass

    def do_GET(self):
        path = urlsplit(self.path).path
        personal=self.members.read(path)
        if personal is not None:return self.json_reply(personal)
        if path in {'/', '/display'}:
            return self.reply(200, (WEB/'display/index.html').read_bytes(), 'text/html; charset=utf-8')
        if path=='/display/video-player':
            return self.reply(200,(WEB/'display/video-player.html').read_bytes(),'text/html; charset=utf-8')
        if path in {'/v1/display/cameras/camera.porch_demo/stream','/v1/display/cameras/camera.porch_demo/snapshot'}:
            return self.camera_sample(path.endswith('/stream'))
        assets = {'/assets/display/polish.css':('display/polish.css','text/css'),
                  '/assets/display/video-provider.js':('display/video-provider.js','text/javascript'),
                  '/assets/display/video-provider.css':('display/video-provider.css','text/css'),
                  '/assets/display/video-player.js':('display/video-player.js','text/javascript'),
                  '/assets/display/video-player.css':('display/video-player.css','text/css'),
                  '/assets/display/google-calendar.js':('display/google-calendar.js','text/javascript'),
                  '/assets/display/google-calendar.css':('display/google-calendar.css','text/css'),
                  '/assets/display/calling.js':('display/calling.js','text/javascript'),
                  '/assets/display/calling.css':('display/calling.css','text/css'),
                  '/assets/vendor/livekit-client-2.22.3.umd.js':('vendor/livekit-client-2.22.3.umd.js','text/javascript'),
                  '/assets/display/profiles.css':('display/profiles.css','text/css'),
                  '/assets/display/group-music.js':('display/group-music.js','text/javascript'),
                  '/assets/display/group-music.css':('display/group-music.css','text/css'),
                  '/assets/display/profiles.js':('display/profiles.js','text/javascript'),
                  '/assets/display/members.js':('display/members.js','text/javascript'),
                  '/assets/display/members.css':('display/members.css','text/css'),
                  '/assets/display/screen.css':('display/screen.css','text/css'),
                  '/assets/display/screen.js':('display/screen.js','text/javascript'),
                  '/assets/display/home.css':('display/home.css','text/css'),
                  '/assets/display/home.js':('display/home.js','text/javascript'),
                  '/assets/display/navigation.js':('display/navigation.js','text/javascript'),
                  '/assets/display/keyboard.css':('display/keyboard.css','text/css'),
                  '/assets/display/keyboard.js':('display/keyboard.js','text/javascript'),
                  '/assets/display/swipe.js':('display/swipe.js','text/javascript'),
                  '/assets/display/keyboard-words.json':('display/keyboard-words.json','application/json'),
                  '/assets/fonts/Manrope-Variable.ttf':('fonts/Manrope-Variable.ttf','font/ttf'),
                  '/assets/display/pi-voice.js':('display/pi-voice.js','text/javascript'),
                  '/assets/display/alerts.js':('display/alerts.js','text/javascript'),
                  '/assets/display/alerts.css':('display/alerts.css','text/css'),
                  '/assets/display/display.js':('display/display.js','text/javascript'),
                  '/assets/display/announcements.js':('display/announcements.js','text/javascript'),
                  '/assets/display/announcements.css':('display/announcements.css','text/css'),
                  '/assets/display/intercom.js':('display/intercom.js','text/javascript'),
                  '/assets/display/intercom.css':('display/intercom.css','text/css'),
                  '/assets/display/intercom-worklet.js':('display/intercom-worklet.js','text/javascript'),
                  '/assets/display/planner.js':('display/planner.js','text/javascript'),
                  '/assets/display/devices.js':('display/devices.js','text/javascript'),
                  '/assets/display/pairing.js':('display/pairing.js','text/javascript'),
                  '/assets/display/lists.js':('display/lists.js','text/javascript'),
                  '/assets/display/experiences.js':('display/experiences.js','text/javascript'),
                  '/assets/display/doorbells.js':('display/doorbells.js','text/javascript'),
                  '/assets/display/doorbells.css':('display/doorbells.css','text/css'),
                  '/assets/display/briefing.js':('display/briefing.js','text/javascript'),
                  '/assets/display/calendar.js':('display/calendar.js','text/javascript'),
                  '/assets/display/calendar.css':('display/calendar.css','text/css'),
                  '/assets/display/calendar-invitations.js':('display/calendar-invitations.js','text/javascript'),
                  '/assets/display/calendar-invitations.css':('display/calendar-invitations.css','text/css'),
                  '/assets/display/member-google.js':('display/member-google.js','text/javascript'),
                  '/assets/display/member-google.css':('display/member-google.css','text/css'),
                  '/assets/display/briefing.css':('display/briefing.css','text/css'),
                  '/assets/display/photos.js':('display/photos.js','text/javascript'),
                  '/assets/display/media.js':('display/media.js','text/javascript'),
                  '/assets/display/radio.js':('display/radio.js','text/javascript'),
                  '/assets/display/device-library.js':('display/device-library.js','text/javascript'),
                  '/assets/display/spotify-library.js':('display/spotify-library.js','text/javascript'),
                  '/assets/display/camera.js':('display/camera.js','text/javascript'),
                  '/assets/display/camera.css':('display/camera.css','text/css'),
                  '/assets/display/settings.css':('display/settings.css','text/css'),
                  '/assets/display/settings.js':('display/settings.js','text/javascript'),
                  '/assets/display/music.js':('display/music.js','text/javascript'),
                  '/assets/display/pi-audio.js':('display/pi-audio.js','text/javascript'),
                  '/assets/display/music.css':('display/music.css','text/css'),
                  '/assets/display/spotify-phone.png':('display/spotify-phone.png','image/png'),
                  '/assets/display/voice.js':('display/voice.js','text/javascript'),
                  '/assets/display/capture-worklet.js':('display/capture-worklet.js','text/javascript'),
                  '/assets/display/display.css':('display/display.css','text/css'),
                  '/assets/icon.svg':('icon.svg','image/svg+xml')}
        if path in assets:
            name, mime = assets[path]; return self.reply(200,(WEB/name).read_bytes(),mime)
        if path in {'/v1/music/artwork/'+'a'*64,'/v1/display/music/artwork/'+'a'*64}:
            return self.reply(200,(ROOT/'docs/images/music-sample-cover.svg').read_bytes(),'image/svg+xml')
        with self.lock:
            if path=='/v1/display/briefing':
                import time
                from datetime import datetime
                today=date.today().isoformat()
                events=[e for e in self.state['/v1/display/agenda']['events'] if
                    (e['start']<=today<e['end'] if e['all_day'] else e['start'][:10]==today and datetime.fromisoformat(e['end']).timestamp()>time.time())]
                items=self.household.snapshot()['items'];tasks=sum(i['kind']=='tasks' and not i['done'] for i in items);shopping=sum(i['kind']=='shopping' and not i['done'] for i in items)
                return self.json_reply({'status':'complete','partial':False,'date':date.today().isoformat(),'timezone':'Local demo','generated_at':time.time(),
                    'text':f'A little room to breathe today. It’s partly cloudy, 22°C. {len(events)} calendar events remain today. There are {shopping} things on the shopping list.',
                    'sources':{'calendar':'available','weather':'available','reminders':'available','lists':'available'},
                    'event_count':len(events),'reminders':[],'task_count':tasks,'shopping_count':shopping})
            if path == '/v1/display/photos': return self.json_reply(self.photos.snapshot())
            if path == '/v1/display/media': return self.json_reply(self.media.snapshot())
            if path.startswith('/v1/display/photos/'):
                try:return self.reply(200,self.photos.read(path.rsplit('/',1)[-1]),'image/jpeg')
                except KeyError:return self.json_reply({'detail':'Photo not found'},404)
            if path == '/v1/state': return self.json_reply({'timers':self.timers.timer_states()+self.schedules.timer_states()})
            if path == '/v1/audio/rooms':return self.json_reply(self.announcements.catalog())
            if path == '/v1/audio/messages':return self.json_reply(self.announcements.reports('demo'))
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
        except HTTPException as error:return self.json_reply({'detail':error.detail},error.status_code)
        except (HouseholdConflict,ScheduleConflict) as error: return self.json_reply({'detail':str(error)},409)
        except (ValueError,TypeError,KeyError): return self.json_reply({'detail':'Invalid demo request'},422)

    do_PATCH = do_DELETE = do_PUT = do_POST

    def mutate(self, path, body):
        personal=self.members.mutate(self.command,path,body)
        if personal is not None:return personal
        if path=='/v1/round/profile':
            from backend.display_profiles import DisplayProfile
            current=self.state[path]
            if body['revision']!=current['profile_revision']:raise ValueError()
            current.update(profile=DisplayProfile.model_validate(body['profile']).model_dump(),profile_revision=current['profile_revision']+1)
            return current
        if path=='/v1/music/groups/library':
            view=body['view'];folder=view=='browse' and not body.get('selection')
            return {'view':view,'offset':0,'total':1,'more':False,'truncated':False,'items':[
                {'selection':('c' if folder else 'd')*32,'kind':'folder' if folder else 'queue' if view=='queue' else 'track',
                 'name':'Echo Sessions · sample' if folder else 'Room to breathe',
                 'artist':'' if folder else 'North Coast · sample','available':True,'current':view=='queue'}]}
        if path=='/v1/music/groups/library/play':
            player=next(p for p in self.state['/v1/music/groups']['items'] if p['id']==body['player'])
            player.update(state='playing',title='Room to breathe',artist='North Coast · sample')
            return {'status':'accepted','text':'Demo playback selected. No real audio played.'}
        if path=='/v1/music/groups/settings':
            current=self.state[path]
            if body['revision']!=current['revision']:raise ValueError()
            current.update(config=body['config'],revision=current['revision']+1,token_saved=True)
            self.state['/v1/music/groups']['revision']=current['revision']
            return current
        if path=='/v1/music/groups/members':
            music=self.state['/v1/music/groups'];leader=next(p for p in music['items'] if p['id']==body['leader'])
            leader['members']=body['members']
            for p in music['items']:
                if p['id']==leader['id']:continue
                p['leader']=leader['id'] if p['id'] in body['members'] else None;p['in_group']=bool(p['leader'])
            music['binding']=hashlib.sha256(json.dumps(music['items']).encode()).hexdigest()
            return {'status':'accepted','text':'Demo group updated. No audio played.'}
        if path=='/v1/music/groups/control':
            p=next(p for p in self.state['/v1/music/groups']['items'] if p['id']==body['player'])
            if body['action']=='volume':p['volume']=body['value']
            elif body['action']=='mute':p['muted']=body['value']
            else:p['state']={'play':'playing','pause':'paused','stop':'idle'}.get(body['action'],p['state'])
            return {'status':'accepted','text':'Demo control accepted. No audio played.'}
        if path=='/v1/audio/rooms' and self.command=='PUT':
            parsed=Configure.model_validate(body)
            return self.announcements.configure([e.model_dump() for e in parsed.endpoints],parsed.revision)
        if path=='/v1/audio/messages' and self.command=='POST':
            parsed=Send.model_validate(body)
            return self.announcements.send(parsed.id,'demo',parsed.title,parsed.message,parsed.targets,parsed.revision,parsed.issued_at)
        if path.startswith('/v1/audio/messages/') and self.command=='DELETE':return self.announcements.cancel(path.rsplit('/',1)[-1],'demo')
        if path == '/v1/display/source-settings':
            state=self.state[path]
            if body['revision']!=state['revision']:raise ScheduleConflict('Sources changed')
            sources=Sources.model_validate(body['sources']).model_dump()
            identifiers=set(sources['calendars']+sources['cameras'])
            if not identifiers<={i['entity_id'] for i in state['items']}:raise ValueError()
            state.update(sources=sources,revision=state['revision']+1)
            self.state['/v1/display/presence']={'status':'available' if sources['presence_sensors'] else 'not_selected','revision':state['revision'],'items':[{'entity_id':i['entity_id'],'name':i['name'],'available':True,'occupied':False} for i in state['items'] if i['entity_id'] in sources['presence_sensors']]}
            self.state['/v1/display/doorbells']={'status':'available' if sources['doorbells'] else 'not_selected','events':[],'revision':state['revision']}
            self.state['/v1/display/sources']={'status':'available' if identifiers else 'not_selected','revision':state['revision'],'items':[{**i,'writable':i['entity_id'] in sources['writable_calendars'],'editable':i['entity_id'] in sources.get('managed_calendars',[]),'deletable':i['entity_id'] in sources.get('managed_calendars',[])} for i in state['items'] if i['entity_id'] in identifiers]}
            return {'sources':sources,'revision':state['revision']}
        if path=='/v1/demo/doorbell':
            import secrets
            bindings=self.state['/v1/display/source-settings']['sources']['doorbells']
            if not bindings:raise ValueError('Select a sample doorbell first')
            binding=bindings[0]
            self.state['/v1/display/doorbells']['events'].insert(0,{'id':secrets.token_hex(16),'trigger':binding['trigger'],'label':binding['label'],'camera':binding['camera'],'at':time.time()})
            return {'status':'demo ring'}
        if path.startswith('/v1/display/doorbells/events/') and self.command=='DELETE':
            state=self.state['/v1/display/doorbells'];state['events']=[e for e in state['events'] if e['id']!=path.rsplit('/',1)[1]]
            return state
        if path=='/v1/display/calendar/draft' or path=='/v1/chat' and draft_request(body.get('text','')):
            tomorrow=(date.today()+timedelta(days=1)).isoformat()
            return {'status':'complete','capability':'calendar_draft','text':'Sample calendar draft. Nothing was saved and no model was called.',
                'calendar_draft':{'event':{'calendar':'calendar.household_demo','title':'Lunch with Sam · sample',
                    'start':tomorrow+'T12:00','end':tomorrow+'T13:00','all_day':False,
                    'timezone':body.get('timezone','UTC'),'location':'','description':'','start_fold':0,'end_fold':0},
                    'questions':['Review this synthetic example before creating it.'],'expires_at':time.time()+900}}
        if path=='/v1/display/calendar/change':
            policy=self.state['/v1/display/source-settings']
            reference=body['reference']
            if body['revision']!=policy['revision'] or reference['calendar'] not in policy['sources'].get('managed_calendars',[]):raise ValueError()
            if body['request_id'] not in self.calendar_requests:
                events=self.state['/v1/display/agenda']['events']
                old=next(e for e in events if e.get('reference')==reference)
                if body['operation']=='delete':events.remove(old)
                else:
                    event=CalendarEvent.model_validate(body['event']);bounds=event.bounds()
                    old.update(title=event.title,description=event.description,location=event.location,all_day=event.all_day,
                        start=bounds.get('start_date',bounds.get('start_date_time')),end=bounds.get('end_date',bounds.get('end_date_time')))
                self.calendar_requests.add(body['request_id'])
            return {'status':'accepted','text':'Demo change accepted. No real calendar was changed.'}
        if path=='/v1/display/calendar/events':
            event=CalendarEvent.model_validate(body['event']);policy=self.state['/v1/display/source-settings']
            if body['revision']!=policy['revision'] or event.calendar not in policy['sources']['writable_calendars']:raise ValueError()
            if body['request_id'] not in self.calendar_requests:
                times=event.bounds();self.calendar_requests.add(body['request_id'])
                self.state['/v1/display/agenda']['events'].append({'id':body['request_id'],'calendar':event.calendar,'calendar_name':'Household · sample','title':event.title,
                    'start':times.get('start_date',times.get('start_date_time')),'end':times.get('end_date',times.get('end_date_time')),'all_day':event.all_day,'location':event.location})
            return {'status':'accepted','text':'Demo event created. No real calendar was changed.'}
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
            music = self.state['/v1/music/now-playing']
            if body['action'] == 'toggle': music['status'] = 'paused' if music['status']=='playing' else 'playing'
            elif body['action'] in {'volume','shuffle','repeat'}:music[body['action']]=body['value']
            elif body['action']=='seek':music['position_ms']=body['value']
            elif body['action'] in {'next','previous'}:music['position_ms']=0
            self.state['/v1/voice']['music']['status']=music['status']
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
