"""Real API guest boundaries with synthetic providers, homes and isolated stores."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock,patch

import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.display_auth import Displays,DisplayStorageUnavailable
from backend.display_profiles import DisplayProfile,ScopedSources
from backend.experiences import Experiences,SourceStore
from backend.home import HomeBridge,HomeConfig
from backend.home_access import HomeAccessStore
from backend.linux_protection import LinuxProtector
from backend.settings import EchoSettings,SettingsStore,SettingsUpdate


class DisplayProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        key=self.root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600);self.protector=LinuxProtector(key)
        self.calls=[]
        self.entities=[{'entity_id':entity,'state':'off','attributes':{'friendly_name':entity,'supported_features':1}} for entity in
                       ('calendar.shared','calendar.private','camera.shared','camera.private')]
        def transport(request):
            self.calls.append(str(request.url))
            if request.url.path=='/api/states':return httpx.Response(200,json=self.entities)
            if request.url.path.startswith('/api/calendars/'):
                name=request.url.path.rsplit('/',1)[1]
                return httpx.Response(200,json=[{'summary':name+' event','start':{'date':'2026-09-20'},'end':{'date':'2026-09-21'}}])
            if request.url.path.startswith('/api/camera_proxy/'):
                return httpx.Response(200,content=b'\xff\xd8\xffsynthetic',headers={'content-type':'image/jpeg'})
            return httpx.Response(404)
        self.home=HomeBridge(HomeConfig(True,'http://127.0.0.1:8123','synthetic-token',{'weather':'weather.demo'}),httpx.MockTransport(transport))
        self.catalog=Mock();self.catalog.snapshot.return_value={'status':'available','devices':[
            {'entity_id':entity,'domain':'light','name':name,'area':room,'state':'off','attributes':{},'available':True}
            for entity,name,room in [('light.guest','Guest lamp','Guest room'),('light.private','Private lamp','Private room')]]}
        self.access=HomeAccessStore(None,self.protector,lambda policy:None)
        self.access.update({'default_access':'hidden','devices':{entity:{'access':'control','room':''} for entity in ('light.guest','light.private')}},self.access.snapshot()['revision'])
        self.settings=SettingsStore(protector=self.protector)
        self.settings.save(SettingsUpdate(settings=EchoSettings(provider='local',model='synthetic',agent_runtime='hermes',personality='PRIVATE HOUSEHOLD PERSONALITY')))
        self.provider=Mock();self.provider.complete.return_value='A guest answer.'
        self.app=create_app('owner-token-'*4,home=self.home,home_catalog=self.catalog,home_access_store=self.access,settings_store=self.settings,provider=self.provider,runtime_root=self.root if getattr(self,'with_runtime',False) else None)
        self.client=TestClient(self.app,base_url='http://localhost' if getattr(self,'with_runtime',False) else 'http://testserver');self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.owner={'Authorization':'Bearer '+'owner-token-'*4}
        self.paired=self.enroll('Guest room');self.guest={'Authorization':'Display '+self.paired['credential']}

    def enroll(self,name):
        code=self.client.post('/v1/displays/pairing',json={'name':name},headers=self.owner).json()['code']
        return self.client.post('/v1/displays/enroll',json={'code':code}).json()

    def profile(self,**values):return DisplayProfile(mode='guest',name='Guest',**values).model_dump()

    def save(self,profile=None,revision=0,headers=None):
        return self.client.put('/v1/displays/'+self.paired['id']+'/profile',headers=headers or self.owner,
                               json={'revision':revision,'profile':profile or self.profile()})

    def share_sources(self):
        r=self.client.put('/v1/display/source-settings',headers=self.owner,json={'revision':0,'sources':{
            'calendars':['calendar.shared','calendar.private'],'cameras':['camera.shared','camera.private'],
            'writable_calendars':['calendar.shared']}})
        self.assertEqual(r.status_code,200,r.text)

    def test_owner_assignment_persistence_and_backward_compatible_household(self):
        self.assertEqual(self.client.get('/v1/display/session',headers=self.guest).json()['profile']['mode'],'household')
        self.assertEqual(self.save(headers=self.guest).status_code,403)
        self.assertEqual(self.save().status_code,200)
        self.assertEqual(self.save().status_code,409)
        self.assertEqual(self.client.get('/v1/display/session',headers=self.guest).json()['profile_revision'],1)
        displays=Displays(self.root,self.protector);d=displays.enroll(displays.pairing('Synthetic room')['code'])
        displays.save_profile(d['id'],self.profile(room='Guest room'),0)
        raw=displays.path.read_bytes();self.assertNotIn(b'Guest room',raw)
        loaded=Displays(self.root,self.protector)
        self.assertEqual(loaded.profile_for('display:'+d['id'])['profile']['room'],'Guest room')
        self.assertEqual(loaded.credential('Display '+d['credential']),d['id'])
        with patch.object(Path,'replace',side_effect=OSError):
            with self.assertRaises(DisplayStorageUnavailable):loaded.save_profile(d['id'],self.profile(),1)
        self.assertEqual(loaded.profile_for('display:'+d['id'])['profile_revision'],1)

    def test_guest_denies_direct_and_indirect_household_endpoints(self):
        self.save()
        for method,path in [('GET','/v1/memory'),('POST','/v1/memory'),('GET','/v1/household'),('POST','/v1/household'),
                ('GET','/v1/tasks'),('POST','/v1/tasks'),('GET','/v1/routines'),('POST','/v1/routines/'+'a'*32+'/run'),
                ('GET','/v1/display/briefing?timezone=UTC'),('GET','/v1/display/photos'),('GET','/v1/display/doorbells'),
                ('GET','/v1/schedules'),('GET','/v1/voice'),('POST','/v1/text'),('POST','/v1/display/calendar/draft'),
                ('POST','/v1/display/calendar/events'),('POST','/v1/display/calendar/change'),('POST','/v1/home/speakers/select'),('POST','/v1/home/rooms/bedroom/actions'),
                ('POST','/v1/home/thermostat/actions'),('GET','/v1/settings'),('POST','/v1/audio/messages'),
                ('POST','/v1/intercom/calls'),('POST','/v1/music/control')]:
            with self.subTest(path=path):self.assertEqual(self.client.request(method,path,headers=self.guest).status_code,403)

    def test_guest_conversation_uses_no_household_memory_personality_or_runtime(self):
        self.assertEqual(self.client.post('/v1/memory',headers=self.owner,json={'text':'PRIVATE HOUSEHOLD MEMORY'}).status_code,200)
        self.client.post('/v1/chat',headers=self.guest,json={'text':'What do you remember about me?'})
        self.save()
        with patch('backend.agent.HermesRuntime.complete',side_effect=AssertionError('Guest reached Hermes')):
            response=self.client.post('/v1/chat',headers=self.guest,json={'text':'What do you know about the house?','allow_home_actions':True})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['access_revision'],1)
        args,kwargs=self.provider.complete.call_args
        self.assertEqual(args[0].agent_runtime,'direct');self.assertFalse(args[0].memory_enabled)
        self.assertNotIn('PRIVATE',str(args)+str(kwargs));self.assertNotIn('memory',kwargs)
        self.assertEqual(self.client.post('/v1/chat',headers=self.guest,json={'text':'What do you remember about me?'}).json()['capability'],'memory')
        self.assertEqual(self.save(self.profile(conversation=False),1).status_code,200)
        self.assertEqual(self.client.post('/v1/chat',headers=self.guest,json={'text':'Hello'}).status_code,403)
        self.assertEqual(self.client.get('/v1/display/voice',headers=self.guest).status_code,403)

    def test_voice_uses_the_same_guest_boundary_and_tags_transient_result(self):
        from backend.display_voice import wave_bytes
        self.save();pipeline=self.app.state.display_voice
        pipeline.injected=True;pipeline.worker=Mock();pipeline.worker.transcribe.return_value='Tell me about the Moon'
        with patch('backend.agent.HermesRuntime.complete',side_effect=AssertionError('Guest reached Hermes')):
            result=self.client.post('/v1/display/voice?reply_audio=false&allow_home=true',headers={**self.guest,'Content-Type':'audio/wav'},content=wave_bytes(bytes(3200),16000))
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['access_revision'],1);self.assertNotIn('audio',result.json())
        self.assertEqual(result.json()['transcript'],'Tell me about the Moon')

    def test_profile_change_stops_active_conversation_before_saving(self):
        self.save();started=Event();finish=Event()
        def reply(*args,**kwargs):started.set();finish.wait(5);return 'Synthetic answer'
        self.provider.complete.side_effect=reply
        with ThreadPoolExecutor(max_workers=1) as worker:
            response=worker.submit(self.client.post,'/v1/chat',headers=self.guest,json={'text':'A general question'})
            self.assertTrue(started.wait(3))
            try:
                self.assertEqual(self.save(DisplayProfile().model_dump(),1).status_code,409)
                self.assertEqual(self.client.get('/v1/display/session',headers=self.guest).json()['profile_revision'],1)
            finally:finish.set()
            self.assertNotEqual(response.result(5).json().get('status'),'complete')
        self.assertEqual(self.save(DisplayProfile().model_dump(),1).status_code,200)

    def test_source_rechecks_display_grant_after_upstream_read(self):
        store=SourceStore(None,self.protector)
        store.save({'calendars':['calendar.shared']},0)
        profile=self.profile(calendars=['calendar.shared']);view=ScopedSources(store,lambda:profile)
        home=Mock();home.config.enabled=True
        def request(method,path):
            if path=='/api/states':return self.entities
            profile['calendars']=[]
            return [{'summary':'Must not return','start':{'date':'2026-09-20'},'end':{'date':'2026-09-21'}}]
        home._request.side_effect=request
        self.assertEqual(Experiences(home,view).agenda('2026-09-20')['events'],[])

    def test_guest_timers_are_endpoint_scoped(self):
        other=self.client.post('/v1/timers',headers=self.owner,json={'seconds':30,'label':'Private timer'}).json()['id']
        self.save();own=self.client.post('/v1/timers',headers=self.guest,json={'seconds':30,'label':'Guest timer'}).json()['id']
        self.assertEqual([t['id'] for t in self.client.get('/v1/state',headers=self.guest).json()['timers']],[own])
        self.assertEqual(self.client.delete('/v1/timers/'+other,headers=self.guest).status_code,404)
        self.assertEqual(self.client.delete('/v1/timers/'+own,headers=self.guest).status_code,200)
        self.assertEqual(self.client.get('/v1/state',headers=self.owner).json()['timers'][0]['id'],other)

    def test_home_visibility_and_control_intersect_both_grants(self):
        self.save(self.profile(home_devices={'light.guest':'read'}))
        state=self.client.get('/v1/display/home',headers=self.guest).json()
        self.assertEqual([i['entity_id'] for i in state['devices']],['light.guest'])
        self.assertEqual(state['areas'],['Guest room']);self.assertEqual(state['devices'][0]['access'],'read')
        self.assertNotIn('Private',self.client.get('/v1/home',headers=self.guest).text)
        body={'entity_id':'light.private','action':'turn_on','revision':state['revision']}
        with patch('backend.home_actions.HomeActions.execute') as execute:
            self.assertEqual(self.client.post('/v1/display/home/control',headers=self.guest,json=body).status_code,403)
            body['entity_id']='light.guest';self.assertEqual(self.client.post('/v1/display/home/control',headers=self.guest,json=body).status_code,403)
            execute.assert_not_called()
        self.assertEqual(self.save(self.profile(home_devices={'light.guest':'control'}),1).status_code,200)
        with patch('backend.home_actions.HomeActions.execute',return_value={'status':'accepted'}) as execute:
            self.assertEqual(self.client.post('/v1/display/home/control',headers=self.guest,json=body).status_code,200)
            self.assertEqual(execute.call_args.args[0].entity_id,'light.guest')
        self.assertEqual(self.save(self.profile(home_devices={'light.unknown':'control'}),2).status_code,422)
        from backend.home import HomeUnavailable
        self.catalog.snapshot.side_effect=HomeUnavailable('Synthetic offline home')
        self.assertEqual(self.save(self.profile(home_devices={'light.guest':'read'}),2).status_code,200)

    def test_only_selected_sources_are_read_and_global_removal_wins(self):
        self.share_sources();self.save(self.profile(calendars=['calendar.shared'],cameras=['camera.shared']))
        source=self.client.get('/v1/display/sources',headers=self.guest).json()['items']
        self.assertEqual({i['entity_id'] for i in source},{'calendar.shared','camera.shared'})
        self.assertFalse(any(i['writable'] for i in source))
        self.calls.clear();agenda=self.client.get('/v1/display/agenda?start=2026-09-20',headers=self.guest)
        self.assertEqual([e['title'] for e in agenda.json()['events']],['calendar.shared event'])
        self.assertFalse(any('/api/calendars/calendar.private' in url for url in self.calls))
        self.assertEqual(self.client.get('/v1/display/cameras/camera.private/snapshot',headers=self.guest).status_code,403)
        self.assertEqual(self.client.get('/v1/display/cameras/camera.shared/snapshot',headers=self.guest).status_code,200)
        self.client.put('/v1/display/source-settings',headers=self.owner,json={'revision':1,'sources':{}})
        self.assertEqual(self.client.get('/v1/display/sources',headers=self.guest).json()['items'],[])
        self.assertEqual(self.client.get('/v1/display/cameras/camera.shared/snapshot',headers=self.guest).status_code,403)

    def test_invalid_profiles_and_missing_grants_are_rejected(self):
        for change in [{'home_devices':{'scene.all_lights':'control'}},{'home_devices':{'weather.demo':'control'}},
                       {'calendars':['calendar.shared','calendar.shared']},{'room':'bad\nroom'},{'mode':'owner'}]:
            profile=self.profile();profile.update(change)
            self.assertEqual(self.client.put('/v1/displays/'+self.paired['id']+'/profile',headers=self.owner,json={'revision':0,'profile':profile}).status_code,422)
        self.assertEqual(self.save(self.profile(calendars=['calendar.private'])).status_code,422)


if __name__=='__main__':unittest.main()
