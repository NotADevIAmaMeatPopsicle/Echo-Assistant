"""Mini API profiles and queued request identities; synthetic home and no audio."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json
from unittest import TestCase
from unittest.mock import patch

import httpx

from backend.round_access import RoundAccess,RoundClient
from backend.round_profile import RoundProfile,RoundProfileUnavailable
import tests.test_display_profiles as fixtures


class RoundProfileTests(TestCase):
    with_runtime=True
    setUp=fixtures.DisplayProfileTests.setUp
    enroll=fixtures.DisplayProfileTests.enroll
    profile=fixtures.DisplayProfileTests.profile

    def save(self,profile=None,revision=0,ready=True):
        status={'status':'armed','access_profile':{'firmware':ready}}
        with patch('backend.app.voice_status',return_value=status):
            return self.client.put('/v1/round/profile',headers=self.owner,json={'profile':profile or self.profile(),'revision':revision})

    def headers(self,revision=1):return {**self.owner,'X-Echo-Endpoint':'round','X-Echo-Access-Revision':str(revision)}

    def test_slow_mini_home_read_does_not_block_display_state(self):
        entered,release=Event(),Event()
        def slow_home():
            entered.set();release.wait(5)
            return {'status':'available','devices':{}}
        with patch.object(self.home,'snapshot',side_effect=slow_home),ThreadPoolExecutor(2) as pool:
            home=pool.submit(self.client.get,'/v1/home',headers=self.headers(0))
            try:
                self.assertTrue(entered.wait(2))
                state=pool.submit(self.client.get,'/v1/state',headers=self.guest)
                self.assertEqual(state.result(timeout=2).status_code,200)
            finally:release.set()
            self.assertEqual(home.result(timeout=2).status_code,200)

    def test_inflight_mini_home_read_discards_result_after_profile_change(self):
        entered,release=Event(),Event()
        def slow_home():
            entered.set();release.wait(5)
            return {'status':'available','devices':{'private':'must not escape'}}
        with patch.object(self.home,'snapshot',side_effect=slow_home),ThreadPoolExecutor(2) as pool:
            home=pool.submit(self.client.get,'/v1/home',headers=self.headers(0))
            try:
                self.assertTrue(entered.wait(2))
                changed=pool.submit(self.save)
                self.assertEqual(changed.result(timeout=2).status_code,200)
            finally:release.set()
            result=home.result(timeout=2)
            self.assertEqual(result.status_code,409)
            self.assertNotIn('must not escape',result.text)

    def enable(self,grant='control',conversation=True):
        self.assertEqual(self.save(self.profile(home_devices={'light.guest':grant},home_voice=True,conversation=conversation)).status_code,200)
        self.device={'entity_id':'light.guest','state':'off','attributes':{'supported_color_modes':['brightness'],'brightness':0}}
        self.writes=[];original=self.home._request
        def request(method,path,data=None):
            if path=='/api/states/light.guest':return deepcopy(self.device)
            if method=='POST':
                self.writes.append((path,deepcopy(data)));self.device['state']='on' if path.endswith('/turn_on') else 'off';return []
            return original(method,path,data)
        self.home._request=request

    def test_owner_enable_requires_current_firmware_and_global_grants(self):
        self.assertEqual(self.save(ready=False).status_code,409)
        self.assertEqual(self.save(self.profile(home_devices={'light.hidden':'control'})).status_code,422)
        self.assertEqual(self.save().status_code,200)
        # Existing restrictions remain editable when the Mini is disconnected.
        self.assertEqual(self.save(self.profile(conversation=False),1,False).status_code,200)
        self.assertEqual(self.save(revision=0).status_code,409)
        self.assertEqual(self.client.put('/v1/round/profile',headers=self.headers(2),json={'revision':2,'profile':self.profile()}).status_code,403)
        self.assertEqual(self.client.get('/v1/round/profile',headers=self.guest).status_code,403)

    def test_guest_denies_private_tools_and_scopes_voice_home_and_timers(self):
        self.enable()
        for method,path in [('GET','/v1/settings'),('GET','/v1/memory'),('GET','/v1/household'),('GET','/v1/tasks'),
                ('GET','/v1/music/groups'),('POST','/v1/intercom/calls'),('POST','/v1/display/calendar/events'),('GET','/v1/display/photos')]:
            with self.subTest(path=path):self.assertEqual(self.client.request(method,path,headers=self.headers()).status_code,403)
        with patch('backend.agent.HermesRuntime.complete',side_effect=AssertionError('Guest reached Hermes')):
            result=self.client.post('/v1/text',headers=self.headers(),json={'text':'Turn on Guest lamp'})
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['home_actions'][0]['status'],'complete')
            answer=self.client.post('/v1/text',headers=self.headers(),json={'text':'Explain rainbows'})
            self.assertEqual(answer.status_code,200)
        self.assertEqual(self.writes,[('/api/services/light/turn_on',{'entity_id':'light.guest'})])
        owner_timer=self.client.post('/v1/timers',headers=self.guest,json={'seconds':120,'label':'Private display timer'}).json()['id']
        mine=self.client.post('/v1/timers',headers=self.headers(),json={'seconds':120,'label':'Mini timer'}).json()['id']
        state=self.client.get('/v1/state',headers=self.headers()).json()
        self.assertEqual([t['id'] for t in state['timers']],[mine]);self.assertNotIn('audio_inbox',state)
        self.assertEqual(self.client.delete('/v1/timers/'+owner_timer,headers=self.headers()).status_code,404)

    def test_cards_filter_rooms_and_read_only_buttons_never_actuate(self):
        self.enable('read');self.catalog.snapshot.return_value['devices'][0]['area']='Living Room'
        snapshot=self.client.get('/v1/home',headers=self.headers()).json()
        self.assertNotIn('Private',json.dumps(snapshot));self.assertEqual(snapshot['permissions']['lights'],0)
        room=next(r for r in snapshot['lights']['rooms'] if r['id']=='living_room')
        self.assertEqual(room['entities'],['light.guest'])
        result=self.client.post('/v1/home/rooms/living_room/actions',headers=self.headers(),json={'action':'turn_on','revision':snapshot['lights']['revision']})
        self.assertEqual(result.status_code,403,result.text);self.assertEqual(self.writes,[])
        self.assertEqual(self.save(self.profile(home_devices={'light.guest':'control'}),1).status_code,200)
        self.assertEqual(self.client.get('/v1/home',headers=self.headers()).status_code,409)
        state=self.client.get('/v1/home',headers=self.headers(2)).json()
        result=self.client.post('/v1/home/rooms/living_room/actions',headers=self.headers(2),json={'action':'turn_on','revision':state['lights']['revision']})
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(len(self.writes),1)

    def test_conversation_revocation_and_endpoint_header_cannot_promote_access(self):
        self.enable(conversation=False)
        self.assertEqual(self.client.post('/v1/text',headers=self.headers(),json={'text':'Hello'}).status_code,403)
        self.assertEqual(self.client.get('/v1/settings',headers=self.headers()).status_code,403)
        self.assertEqual(self.client.get('/v1/home',headers={**self.guest,'X-Echo-Endpoint':'round','X-Echo-Access-Revision':'1'}).status_code,401)
        self.assertEqual(self.client.get('/v1/settings',headers=self.owner).status_code,200)

    def test_speaker_selection_and_thermostat_use_only_shared_entities(self):
        states={
            'climate.shared':{'state':'heat','attributes':{'temperature':21,'temperature_unit':'°C','min_temp':15,'max_temp':28,'hvac_modes':['heat','off'],'supported_features':1}},
            'media_player.a':{'state':'playing','attributes':{'volume_level':.2,'supported_features':16397}},
            'media_player.b':{'state':'paused','attributes':{'volume_level':.4,'supported_features':16397}}}
        for entity,item in states.items():item['entity_id']=entity
        self.catalog.snapshot.return_value['devices']=[{**deepcopy(s),'name':e,'domain':e.split('.')[0],'area':'Shared room','available':True} for e,s in states.items()]
        policy={'default_access':'hidden','devices':{e:{'access':'control','room':''} for e in states}}
        self.access.update(policy,self.access.snapshot()['revision'])
        self.home.config.entities.update(thermostat='climate.shared',soundbar='media_player.a')
        self.assertEqual(self.save(self.profile(home_devices={e:'control' for e in states})).status_code,200)
        writes=[]
        def request(method,path,data=None):
            if path=='/api/config':return {'unit_system':{'temperature':'°C'}}
            if method=='GET':return deepcopy(states[path.rsplit('/',1)[1]])
            writes.append((path,deepcopy(data)));entity=states[data['entity_id']]
            if path.endswith('volume_set'):entity['attributes']['volume_level']=data['volume_level']
            if path.endswith('set_temperature'):entity['attributes']['temperature']=data['temperature']
            return []
        self.home._request=request
        before=self.client.get('/v1/home',headers=self.headers()).json()['speakers']
        r=self.client.post('/v1/home/speakers/select',headers=self.headers(),json={'index':1,'revision':before['revision']});self.assertEqual(r.status_code,200,r.text)
        selected=self.client.get('/v1/home',headers=self.headers()).json()['speakers']
        self.assertEqual(selected['selected'],1);self.assertEqual(self.home.config.entities['soundbar'],'media_player.a')
        stale=self.client.post('/v1/home/speakers/control',headers=self.headers(),json={'action':'up','binding':before['binding']})
        self.assertEqual(stale.status_code,409);self.assertEqual(writes,[])
        r=self.client.post('/v1/home/speakers/control',headers=self.headers(),json={'action':'up','binding':selected['binding']});self.assertEqual(r.status_code,200,r.text)
        r=self.client.post('/v1/home/thermostat/actions',headers=self.headers(),json={'action':'adjust_temperature','value':1,'unit':'°C'});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual([d['entity_id'] for _,d in writes],['media_player.b','climate.shared'])
        # Revoking the global grant invalidates the same on-screen binding.
        policy['devices']['media_player.b']['access']='hidden';self.access.update(policy,self.access.snapshot()['revision'])
        r=self.client.post('/v1/home/speakers/control',headers=self.headers(),json={'action':'down','binding':selected['binding']})
        self.assertEqual(r.status_code,409);self.assertEqual(len(writes),2)
        # Unsupported/malformed device data becomes a bounded API error.
        self.catalog.snapshot.return_value['devices'][0]['attributes']['temperature']=None
        r=self.client.post('/v1/home/thermostat/actions',headers=self.headers(),json={'action':'adjust_temperature','value':1})
        self.assertEqual(r.status_code,409);self.assertEqual(len(writes),2)

    def test_encrypted_profile_restart_corruption_and_runtime_failure(self):
        self.save(self.profile(room='Synthetic room'))
        path=self.root/'local/echo-round-profile.json';self.assertNotIn(b'Synthetic room',path.read_bytes())
        store=RoundProfile(self.root,self.protector);self.assertEqual(store.snapshot()['profile']['room'],'Synthetic room')
        runtime=RoundAccess(self.root,store=store,clock=lambda:0)
        runtime.observe('STATUS access_profile=1');self.assertTrue(runtime.refresh());self.assertTrue(runtime.guest)
        path.write_text('broken')
        with self.assertRaises(RoundProfileUnavailable):store.snapshot()
        self.assertFalse(runtime.read()['available'])

    def test_queued_clients_keep_old_revision_and_cannot_override_endpoint(self):
        captured=[]
        with httpx.Client(base_url='http://test',transport=httpx.MockTransport(lambda r:(captured.append(r) or httpx.Response(200)))) as base:
            old=RoundClient(base,1);new=RoundClient(base,2)
            new.get('/v1/home');old.post('/v1/timers',headers={'X-Echo-Endpoint':'owner'},json={'seconds':60})
        self.assertEqual([r.headers['x-echo-access-revision'] for r in captured],['2','1'])
        self.assertTrue(all(r.headers['x-echo-endpoint']=='round' for r in captured))

    def test_household_keeps_owner_research_queue_guest_cannot_start_jobs(self):
        with patch('backend.research_tasks.ResearchTasks.start',return_value={'id':'synthetic'}) as start:
            result=self.client.post('/v1/text',headers=self.headers(0),json={'text':'Research battery recycling'})
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['task_id'],'synthetic')
            start.assert_called_once_with('device','Research battery recycling')
            self.save();start.reset_mock()
            result=self.client.post('/v1/text',headers=self.headers(),json={'text':'Research battery recycling'})
            self.assertEqual(result.status_code,200,result.text);start.assert_not_called()

    def test_profile_change_stops_active_reply_before_saving(self):
        self.save();entered=Event();release=Event()
        def reply(*args,**kwargs):entered.set();release.wait(3);return 'A bounded guest reply.'
        self.provider.complete.side_effect=reply
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self.client.post,'/v1/text',headers=self.headers(),json={'text':'Explain rainbows'})
            try:
                self.assertTrue(entered.wait(3))
                change=self.save(self.profile(conversation=False),revision=1)
                self.assertEqual(change.status_code,409,change.text)
                self.assertEqual(self.client.get('/v1/round/profile',headers=self.owner).json()['profile_revision'],1)
            finally:release.set()
            pending.result(timeout=5)
        self.assertEqual(self.save(self.profile(conversation=False),revision=1).status_code,200)
