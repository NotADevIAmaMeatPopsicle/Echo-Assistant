import copy
import re
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from pydantic import ValidationError
from backend.agent import EchoAgent
from backend.agent_runtime import RuntimeUnavailable
from backend.app import create_app
from backend.home import HomeUnavailable
from backend.home_actions import HomeActions, ActionRequest
from backend.home_access import HomeAccessStore
from backend.home_policy import apply_policy, validate_policy
from backend.settings import EchoSettings, SettingsStore, SettingsUpdate


class FakeHome:
    def __init__(self):
        self.config=SimpleNamespace(enabled=True)
        self.states={
            'light.desk':{'entity_id':'light.desk','state':'on','attributes':{'brightness':255,
                'supported_color_modes':['color_temp'],'color_temp_kelvin':4000,
                'min_color_temp_kelvin':2200,'max_color_temp_kelvin':6500}},
            'climate.study':{'entity_id':'climate.study','state':'heat','attributes':{
                'hvac_modes':['off','heat','cool'],'temperature':70,'min_temp':60,'max_temp':85,'target_temp_step':1}},
            'media_player.test':{'entity_id':'media_player.test','state':'paused','attributes':{
                'supported_features':1+4+8+16+32+128+256+16384+4096,'volume_level':.2,'is_volume_muted':False}},
            'scene.evening':{'entity_id':'scene.evening','state':'2026-09-17','attributes':{}}}
        self.calls=[];self.fail_post=False;self.apply_post=True;self.before_read=None

    def _request(self,method,path,body=None):
        self.calls.append((method,path,copy.deepcopy(body)))
        if path=='/api/config':return {'unit_system':{'temperature':'°F'}}
        if method=='GET':
            if self.before_read:self.before_read()
            return copy.deepcopy(self.states[path.removeprefix('/api/states/')])
        entity=body['entity_id'];state=self.states[entity];attrs=state['attributes']
        if self.apply_post:
            if path.endswith('/turn_off'):state['state']='off'
            elif path.endswith('/turn_on') and not entity.startswith('scene.'):
                state['state']='on'
                if 'brightness_pct' in body:
                    attrs['brightness']=round(body['brightness_pct']*255/100)
                    if not body['brightness_pct']:state['state']='off'
                if 'color_temp_kelvin' in body:attrs['color_temp_kelvin']=body['color_temp_kelvin']
            elif path.endswith('/set_temperature'):attrs['temperature']=body['temperature']
            elif path.endswith('/set_hvac_mode'):state['state']=body['hvac_mode']
            elif path.endswith('/volume_set'):attrs['volume_level']=body['volume_level']
            elif path.endswith('/volume_mute'):attrs['is_volume_muted']=body['is_volume_muted']
            elif path.endswith('/media_play'):state['state']='playing'
        if self.fail_post:raise HomeUnavailable('Ambiguous synthetic response')
        return []

    @property
    def writes(self):return [c for c in self.calls if c[0]=='POST']


class HomeActionTests(unittest.TestCase):
    def setUp(self):
        self.home=FakeHome();self.access=HomeAccessStore(synchronizer=lambda _:None)
        self.policy={'default_access':'read','devices':{entity:{'access':'control','room':'Study'} for entity in self.home.states}}
        self.access.update(self.policy,self.access.snapshot()['revision'])
        self.now=0
        self.actions=HomeActions(self.home,self.access,clock=lambda:self.now,sleep=lambda _:None)

    def scope(self,allowed=True,cancel=None):
        return self.actions.scope(allowed,self.access.snapshot()['revision'],cancel)

    def command(self,scope,action='brightness',value=30,entity='light.desk',unit=None):
        return ActionRequest(request_id=scope.id,entity_id=entity,action=action,value=value,unit=unit)

    def test_control_is_explicit_never_the_default_or_security_devices(self):
        for policy in ({'default_access':'control','devices':{}},
            {'default_access':'read','devices':{'cover.garage':{'access':'control','room':''}}},
            {'default_access':'read','devices':{'lock.front':{'access':'control','room':''}}}):
            with self.assertRaises(ValueError):validate_policy(policy)
        with self.scope(False) as scope:self.assertIsNone(scope)
        self.assertFalse(self.home.writes)

    def test_observation_and_same_command_retry_send_at_most_once(self):
        with self.scope() as scope:
            command=self.command(scope)
            first=self.actions.execute(command)
            repeated=self.actions.execute(self.command(scope,value=30.0))
            self.assertEqual(first['status'],'complete');self.assertTrue(first['attempted'])
            self.assertTrue(repeated['replayed']);self.assertEqual(len(self.home.writes),1)
            self.assertEqual(first['observed']['attributes']['brightness'],76)
        self.assertEqual(self.actions.execute(command)['status'],'denied')
        self.assertEqual(len(self.home.writes),1)

    def test_already_desired_state_needs_no_post(self):
        with self.scope() as scope:
            result=self.actions.execute(self.command(scope,value=100))
        self.assertEqual(result['status'],'complete');self.assertFalse(result['attempted']);self.assertFalse(self.home.writes)

    def test_color_and_range_target_validation(self):
        from backend.home_actions import plan
        with self.scope() as scope:
            color=self.command(scope,action='color',value='#40a0ff')
            with self.assertRaises(ValueError): plan(color,self.home.states['light.desk'],self.home)
            light=copy.deepcopy(self.home.states['light.desk']); light['attributes']['supported_color_modes']=['rgb']
            domain,service,body,confirmed=plan(color,light,self.home)
            self.assertEqual(body['rgb_color'],[64,160,255])
            light['attributes']['rgb_color']=[64,160,255]
            self.assertTrue(confirmed(light))
            climate=copy.deepcopy(self.home.states['climate.study']); climate['state']='heat_cool'
            command=self.command(scope,action='temperature_range',value={'low':65.0,'high':75.0},entity='climate.study',unit='°F')
            domain,service,body,confirmed=plan(command,climate,self.home)
            self.assertEqual((body['target_temp_low'],body['target_temp_high']),(65,75))
            climate['attributes'].update(target_temp_low=65,target_temp_high=75)
            self.assertTrue(confirmed(climate))
            for bounds in ({'low':80.0,'high':70.0},{'low':0.0,'high':70.0}):
                with self.assertRaises(ValueError): plan(command.model_copy(update={'value':bounds}),climate,self.home)
        self.assertFalse(self.home.writes)

    def test_ambiguous_transport_never_retries_writes_and_reconciles(self):
        self.home.fail_post=True
        with self.scope() as scope:
            self.assertEqual(self.actions.execute(self.command(scope))['status'],'complete')
            self.actions.execute(self.command(scope))
        self.assertEqual(len(self.home.writes),1)
        self.home.apply_post=False
        with self.scope() as scope:
            result=self.actions.execute(self.command(scope,value=50))
            self.assertEqual(result['status'],'unconfirmed')
            self.assertTrue(self.actions.execute(self.command(scope,value=50))['replayed'])
        self.assertEqual(len(self.home.writes),2)

    def test_revocation_expiry_cancellation_and_no_cross_request_reuse(self):
        cancel=Event()
        with self.scope(cancel=cancel) as scope:
            cancel.set();self.assertEqual(self.actions.execute(self.command(scope))['status'],'denied')
        with self.scope() as scope:
            self.now=61;self.assertEqual(self.actions.execute(self.command(scope))['status'],'denied')
        with self.scope() as scope:
            self.policy['devices']['light.desk']['access']='read'
            self.access.update(self.policy,self.access.snapshot()['revision'])
            self.assertEqual(self.actions.execute(self.command(scope))['status'],'denied')
        self.assertFalse(self.home.writes)

    def test_cancellation_during_state_read_prevents_dispatch(self):
        cancel=Event();self.home.before_read=cancel.set
        with self.scope(cancel=cancel) as scope:
            self.assertEqual(self.actions.execute(self.command(scope))['status'],'denied')
        self.assertFalse(self.home.writes)

    def test_read_only_entity_and_unavailable_state_are_never_actuated(self):
        self.policy['devices']['light.desk']['access']='read'
        self.access.update(self.policy,self.access.snapshot()['revision'])
        with self.scope() as scope:
            self.assertEqual(self.actions.execute(self.command(scope))['status'],'denied')
        self.home.states['climate.study']['state']='unavailable'
        with self.scope() as scope:
            self.assertEqual(self.actions.execute(self.command(scope,'temperature',72,'climate.study','°F'))['status'],'unavailable')
        self.assertFalse(self.home.writes)

    def test_capabilities_ranges_types_and_units_checked_before_post(self):
        with self.scope() as scope:
            for action,value,entity,unit in [('brightness',101,'light.desk',None),('brightness',True,'light.desk',None),
                ('color_temperature',8000,'light.desk',None),('temperature',72,'climate.study','°C'),
                ('temperature',90,'climate.study','°F'),('mode','invented','climate.study',None),
                ('mute',1,'media_player.test',None),('turn_off',20,'light.desk',None)]:
                self.assertEqual(self.actions.execute(self.command(scope,action,value,entity,unit))['status'],'denied')
        self.assertFalse(self.home.writes)
        self.home.states['light.desk']['attributes']['supported_color_modes']=42
        with self.scope() as scope:self.assertEqual(self.actions.execute(self.command(scope))['status'],'denied')

    def test_climate_light_player_and_scene_fixed_services(self):
        with self.scope() as scope:
            for action,value,entity,unit in [('color_temperature',2700,'light.desk',None),
                ('temperature',72,'climate.study','°F'),('mode','cool','climate.study',None),
                ('volume',25,'media_player.test',None),('mute',True,'media_player.test',None),
                ('play',None,'media_player.test',None)]:
                self.assertEqual(self.actions.execute(self.command(scope,action,value,entity,unit))['status'],'complete')
            for action,entity in [('next','media_player.test'),('activate','scene.evening')]:
                self.assertEqual(self.actions.execute(self.command(scope,action,None,entity))['status'],'accepted')
        self.assertIn(('POST','/api/services/climate/set_temperature',{'entity_id':'climate.study','temperature':72}),self.home.writes)

    def test_action_count_busy_scope_and_validation_host(self):
        with self.scope() as scope:
            scope.lock.acquire()
            try:self.assertEqual(self.actions.execute(self.command(scope))['status'],'busy')
            finally:scope.lock.release()
            for value in range(12):self.actions.execute(self.command(scope,value=value))
            self.assertEqual(self.actions.execute(self.command(scope,value=50))['status'],'denied')
            self.assertEqual(len(scope.results),12)
        self.actions.enabled=False
        with self.scope() as scope:self.assertIsNone(scope)

    def test_invalid_request_schema(self):
        for fields in ({'entity_id':'light.x/../../config'},{'action':'arbitrary_service'},
                       {'value':float('nan')},{'value':float('inf')},{'extra':'no'},{'value':'x'*300}):
            with self.assertRaises(ValidationError):
                ActionRequest(**{'request_id':'a'*32,'entity_id':'light.desk','action':'brightness','value':10,**fields})

    def test_app_capability_cannot_be_created_with_static_tool_token(self):
        catalog=Mock();catalog.snapshot.return_value={'areas':[],'devices':[]}
        store=SettingsStore();store.save(SettingsUpdate(settings=EchoSettings(provider='azure',model='test',agent_runtime='hermes',azure_url='https://example.openai.azure.com/openai/v1'),api_key='synthetic-key'))
        app=create_app('a'*40,self.home,settings_store=store,home_catalog=catalog,
                       home_access_store=self.access,home_tools_token='b'*40)
        client=TestClient(app);owner={'Authorization':'Bearer '+'a'*40};tool={'Authorization':'Bearer '+'b'*40}
        payload={'request_id':'a'*32,'entity_id':'light.desk','action':'brightness','value':30}
        self.assertEqual(client.post('/internal/home/action',headers=owner,json=payload).status_code,401)
        self.assertEqual(client.post('/internal/home/action',headers=tool,json=payload).json()['status'],'denied')
        self.assertEqual(client.post('/v1/chat',headers=tool,json={'text':'turn it off','allow_home_actions':True}).status_code,401)
        scopes=[]
        def runtime(*args,**kwargs):
            match=re.search('request_id=([a-f0-9]{32})',kwargs['instructions'])
            if match:
                payload['request_id']=match[1];scopes.append(match[1])
                self.assertEqual(client.post('/internal/home/action',headers=tool,json=payload).json()['status'],'complete')
            return 'Done' if match else 'Read only'
        with patch('backend.agent.HermesRuntime.complete',side_effect=runtime):
            self.assertEqual(client.post('/v1/chat',headers=owner,json={'text':'Dim desk'}).json()['text'],'Read only')
            result=client.post('/v1/chat',headers=owner,json={'text':'Dim desk','allow_home_actions':True}).json()
        self.assertEqual(len(result['home_actions']),1);self.assertEqual(len(self.home.writes),1)
        self.assertEqual(client.post('/internal/home/action',headers=tool,json=payload).json()['status'],'denied')

    def test_followup_context_truthful_failures_and_runtime_error_revokes_scope(self):
        store=SettingsStore();store.save(SettingsUpdate(settings=EchoSettings(provider='azure',model='test',agent_runtime='hermes',azure_url='https://example.openai.azure.com/openai/v1'),api_key='synthetic-key'))
        agent=EchoAgent(store);agent.home_access=self.access;agent.home_actions=self.actions
        instructions=[];commands=[]
        def complete(*args,**kwargs):
            instructions.append(kwargs['instructions'])
            scope_id=re.search('request_id=([a-f0-9]{32})',kwargs['instructions'])[1]
            command=ActionRequest(request_id=scope_id,entity_id='light.desk',action='brightness',value=30 if len(instructions)==1 else 50)
            commands.append(command);self.actions.execute(command)
            return 'Everything worked perfectly.'
        agent.runtime.complete=complete
        self.assertEqual(agent.respond('Dim the desk',allow_home_actions=True)['home_actions'][0]['status'],'complete')
        self.home.apply_post=False
        result=agent.respond('A little brighter',allow_home_actions=True)
        self.assertIn('could not confirm',result['text']);self.assertNotIn('perfectly',result['text'])
        self.assertIn('Earlier home action receipts',instructions[-1]);self.assertIn('light.desk',instructions[-1])
        def failing(*args,**kwargs):
            complete(*args,**kwargs);raise RuntimeUnavailable('Synthetic lost reply')
        agent.runtime.complete=failing
        result=agent.respond('Try 50 percent',allow_home_actions=True)
        self.assertEqual(result['status'],'unavailable');self.assertTrue(result['home_actions'])
        self.assertFalse(self.actions.scopes);self.assertEqual(self.actions.execute(commands[-1])['status'],'denied')
        agent.clear();self.assertEqual(agent.messages('device'),[])
