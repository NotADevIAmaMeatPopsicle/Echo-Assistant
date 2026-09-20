"""Guest home commands against fake devices, with no sound or network actions."""
from copy import deepcopy
from threading import Event
from unittest import TestCase
from unittest.mock import Mock,patch

from backend.guest_home import parse,ScopedAccess,GuestHome
from backend.home_actions import HomeActions
import tests.test_display_profiles as profiles


class GuestHomeTests(TestCase):
    setUp=profiles.DisplayProfileTests.setUp
    enroll=profiles.DisplayProfileTests.enroll
    profile=profiles.DisplayProfileTests.profile
    save=profiles.DisplayProfileTests.save

    def enable(self,grant='control'):
        self.assertEqual(self.save(self.profile(home_voice=True,home_devices={'light.guest':grant})).status_code,200)
        self.device={'entity_id':'light.guest','state':'off','attributes':{'supported_color_modes':['brightness'],'brightness':0}}
        self.writes=[]
        original=self.home._request
        def request(method,path,data=None):
            if path=='/api/states/light.guest':return deepcopy(self.device)
            if method=='POST':
                self.writes.append((path,deepcopy(data)));self.device['state']='on' if path.endswith('/turn_on') else 'off'
                if 'brightness_pct' in data:self.device['attributes']['brightness']=round(data['brightness_pct']*255/100)
                return []
            return original(method,path,data)
        self.home._request=request

    def chat(self,text,allow=True):
        return self.client.post('/v1/chat',headers=self.guest,json={'text':text,'allow_home_actions':allow})

    def test_local_control_and_read_never_use_model_or_private_devices(self):
        self.enable()
        with patch('backend.agent.HermesRuntime.complete',side_effect=AssertionError('Hermes was called')):
            result=self.chat('Please turn on the Guest lamp')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['home_actions'][0]['status'],'complete')
        self.assertEqual([body['entity_id'] for _,body in self.writes],['light.guest'])
        self.provider.complete.assert_not_called()
        self.assertNotIn('Private',self.chat('List shared devices').text)
        self.assertNotIn('Private',self.chat('Is Private lamp on?').text)
        self.assertEqual(len(self.writes),1)
        self.assertIn('Guest lamp',self.chat('What is the status of the Guest lamp?').json()['text'])

    def test_owner_voice_opt_in_and_current_message_consent_are_independent(self):
        self.save(self.profile(home_devices={'light.guest':'control'}))
        self.assertIn('voice commands are off',self.chat('Turn on Guest lamp').json()['text'])
        self.assertEqual(self.save(self.profile(home_voice=True,home_devices={'light.guest':'control'}),1).status_code,200)
        self.assertIn('Allow home actions',self.chat('Turn on Guest lamp',False).json()['text'])
        self.provider.complete.assert_not_called()

    def test_read_only_unknown_ambiguous_and_out_of_range_commands_never_write(self):
        self.enable('read')
        self.assertIn('viewing only',self.chat('Turn on Guest lamp').json()['text'])
        self.assertEqual(self.save(self.profile(home_voice=True,home_devices={'light.guest':'control'}),1).status_code,200)
        self.chat('Set Guest lamp brightness to 140 percent')
        self.chat('Turn on Private lamp')
        self.chat('Turn on Guest lamp and delete all files')
        duplicate=deepcopy(self.catalog.snapshot.return_value['devices'][0]);duplicate['entity_id']='light.duplicate'
        self.catalog.snapshot.return_value['devices'].append(duplicate)
        policy=self.access.snapshot();policy['policy']['devices']['light.duplicate']={'access':'control','room':''};self.access.update(policy['policy'],policy['revision'])
        self.save(self.profile(home_voice=True,home_devices={'light.guest':'control','light.duplicate':'control'}),2)
        self.assertIn('more than one',self.chat('Turn on Guest lamp').json()['text'])
        self.assertEqual(self.writes,[])

    def test_room_group_is_limited_to_shared_entities_and_validates_before_dispatch(self):
        self.enable();self.chat('Set Guest room lights to 20 percent')
        self.assertEqual(self.writes,[('/api/services/light/turn_on',{'entity_id':'light.guest','brightness_pct':20})])
        self.provider.complete.assert_not_called()

    def test_revocation_between_inventory_and_execution_prevents_action(self):
        self.enable();snapshot=deepcopy(self.catalog.snapshot.return_value)
        def changed():
            policy=self.access.snapshot();policy['policy']['devices']['light.guest']['access']='hidden'
            self.access.update(policy['policy'],policy['revision']);return snapshot
        self.catalog.snapshot.side_effect=changed
        self.chat('Turn on Guest lamp')
        self.assertEqual(self.writes,[])

    def test_profile_scope_is_rechecked_immediately_before_write(self):
        self.enable();displays=Mock()
        before={'profile':self.profile(home_voice=True,home_devices={'light.guest':'control'}),'profile_revision':1}
        displays.profile_for.return_value=before
        scoped=ScopedAccess(self.access,displays,'display:example',deepcopy(before))
        actions=HomeActions(self.home,scoped,sleep=lambda _:None)
        original=self.home._request
        def revoke(method,path,data=None):
            value=original(method,path,data)
            if method=='GET':displays.profile_for.return_value={**before,'profile_revision':2}
            return value
        self.home._request=revoke
        from backend.home_actions import ActionRequest
        with actions.scope(True,scoped.snapshot()['revision']) as scope:
            result=actions.execute(ActionRequest(request_id=scope.id,entity_id='light.guest',action='turn_on'))
        self.assertEqual(result['status'],'denied');self.assertEqual(self.writes,[])

    def test_spoken_commands_share_the_same_restrictions_without_synthesizing(self):
        self.enable();pipeline=self.app.state.display_voice;pipeline.injected=True;pipeline.worker=Mock()
        pipeline.worker.transcribe.return_value='Turn on Guest lamp'
        from backend.display_voice import wave_bytes
        result=self.client.post('/v1/display/voice?reply_audio=false&allow_home=true',headers={**self.guest,'Content-Type':'audio/wav'},content=wave_bytes(bytes(3200),16000))
        self.assertEqual(result.status_code,200,result.text);self.assertNotIn('audio',result.json())
        self.assertEqual(result.json()['home_actions'][0]['entity_id'],'light.guest')
        self.assertEqual(len(self.writes),1);self.provider.complete.assert_not_called()

    def test_cancel_and_validation_mode_never_send(self):
        self.enable();displays=Mock();before={'profile':self.profile(home_voice=True,home_devices={'light.guest':'control'}),'profile_revision':1};displays.profile_for.return_value=before
        actions=HomeActions(self.home,self.access,enabled=False);gateway=GuestHome(self.catalog,actions,displays)
        result=gateway.respond('Turn on Guest lamp','display:example',before,allow_home=True)
        self.assertIn('validation host',result['text'])
        cancel=Event();cancel.set();self.assertEqual(gateway.respond('Turn on Guest lamp','display:example',before,allow_home=True,cancel=cancel)['text'],'Request stopped.')
        self.assertEqual(self.writes,[])

    def test_supported_phrases_have_explicit_values_and_general_questions_fall_through(self):
        for text,action,value,unit in [('set Guest speaker volume to 25%','volume',25,None),('set thermostat to 21 celsius','temperature',21.0,'°C'),('unmute Guest speaker','mute',False,None),('pause the speaker','pause',None,None)]:
            with self.subTest(text=text):
                intent=parse(text);self.assertEqual((intent.action,intent.value,intent.unit),(action,value,unit))
        for text in ['Why does the Moon have phases?','Do not turn on the lamp','If it is dark turn on the lamp','Run scene all lights','Set thermostat to 21']:
            self.assertIsNone(parse(text))
