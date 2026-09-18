import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock
from fastapi.testclient import TestClient
from backend.agent import EchoAgent
from backend.app import create_app
from backend.home_actions import HomeActions
from backend.home_access import HomeAccessStore
from backend.routines import RoutineStore, Routines, RoutineConflict, RoutineUnavailable, routine_request
from backend.settings import SettingsStore, default_protector
from test_home_actions import FakeHome


class RoutineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        self.protector=default_protector(); self.home=FakeHome()
        self.access=HomeAccessStore(synchronizer=lambda _:None)
        self.policy={'default_access':'read','devices':{key:{'access':'control','room':'Study'} for key in self.home.states}}
        self.access.update(self.policy,self.access.snapshot()['revision'])
        self.actions=HomeActions(self.home,self.access,sleep=lambda _:None)
        self.store=RoutineStore(self.root,self.protector); self.routines=Routines(self.store,self.actions)
        self.steps=[{'entity_id':'light.desk','action':'brightness','value':30,'unit':None},
                    {'entity_id':'media_player.test','action':'volume','value':15,'unit':None}]

    def save(self): return self.routines.save('Movie mode',self.steps)
    def run_item(self,item,**kwargs): return self.routines.run(item['id'],item['revision'],**kwargs)

    def test_save_is_silent_encrypted_and_survives_restart_with_exact_targets(self):
        item=self.save();self.assertEqual(self.home.writes,[])
        data=self.store.path.read_text();self.assertNotIn('Movie',data);self.assertNotIn('light.desk',data)
        restored=RoutineStore(self.root,self.protector)
        self.assertEqual(restored.get(item['id']),item)
        self.assertEqual(self.access.snapshot()['policy'],self.policy)
        result=self.run_item(item)
        self.assertEqual(result['status'],'complete');self.assertEqual(len(self.home.writes),2)
        self.assertEqual([x[2]['entity_id'] for x in self.home.writes],['light.desk','media_player.test'])
        self.assertEqual(len(result['home_actions']),2)

    def test_preflight_all_devices_blocks_every_write_when_later_permission_or_state_invalid(self):
        item=self.save();self.policy['devices']['media_player.test']['access']='read'
        self.access.update(self.policy,self.access.snapshot()['revision'])
        result=self.run_item(item);self.assertEqual(result['status'],'unavailable');self.assertFalse(self.home.writes)
        self.policy['devices']['media_player.test']['access']='control';self.access.update(self.policy,self.access.snapshot()['revision'])
        self.home.states['media_player.test']['state']='unavailable'
        self.assertEqual(self.run_item(item)['status'],'unavailable');self.assertFalse(self.home.writes)

    def test_cancellation_after_first_write_keeps_receipt_and_never_sends_second(self):
        item=self.save();cancel=Event();original=self.home._request
        def request(method,path,body=None):
            value=original(method,path,body)
            if method=='POST':cancel.set()
            return value
        self.home._request=request
        result=self.run_item(item,cancel=cancel)
        self.assertEqual(result['status'],'cancelled');self.assertEqual(len(self.home.writes),1)
        self.assertEqual(result['home_actions'][0]['status'],'complete')

    def test_ambiguous_first_write_is_not_retried_and_stops_routine(self):
        item=self.save();self.home.apply_post=False;self.home.fail_post=True
        result=self.run_item(item)
        self.assertEqual(result['status'],'unavailable');self.assertEqual(len(self.home.writes),1)
        self.assertEqual(result['home_actions'][0]['status'],'unconfirmed')

    def test_edit_revision_and_access_changes_stop_remaining_actions(self):
        for change in ('recipe','permission'):
            with self.subTest(change=change):
                self.setUp();item=self.save();original=self.home._request
                def request(method,path,body=None):
                    value=original(method,path,body)
                    if method=='POST':
                        if change=='recipe': self.store.save('Changed',self.steps,item['id'],item['revision'])
                        else:
                            self.policy['devices']['media_player.test']['access']='read'
                            self.access.update(self.policy,self.access.snapshot()['revision'])
                    return value
                self.home._request=request;result=self.run_item(item)
                self.assertEqual(result['status'],'unavailable');self.assertEqual(len(self.home.writes),1)
                self.assertEqual(result['home_actions'][0]['status'],'complete')

    def test_conflicts_duplicates_corruption_and_stale_delete_preserve_data(self):
        item=self.save()
        with self.assertRaises(RoutineConflict):self.routines.save('movie MODE',self.steps)
        with self.assertRaises(ValueError):self.routines.save('Duplicate',[self.steps[0],{**self.steps[0],'value':30.0}])
        with self.assertRaises(ValueError):self.routines.save('Bad target',[{**self.steps[0],'value':101}])
        updated=self.routines.save('New name',self.steps,item['id'],item['revision'])
        with self.assertRaises(RoutineConflict):self.store.delete(item['id'],item['revision'])
        self.assertEqual(self.store.get(item['id']),updated)
        self.store.path.write_text('corrupt');broken=RoutineStore(self.root,self.protector)
        with self.assertRaises(RoutineUnavailable):broken.save('Replacement',self.steps)
        self.assertEqual(self.store.path.read_text(),'corrupt')

    def test_source_is_last_verified_receipts_not_an_old_or_failed_conversation(self):
        receipt={**self.steps[0],'status':'complete','observed':{'state':'on'}}
        item=self.routines.from_recent('Study',[{'role':'assistant','home_actions':[receipt]}])
        self.assertEqual(item['steps'][0]['entity_id'],'light.desk');self.assertFalse(self.home.writes)
        for messages in ([{'role':'assistant','home_actions':[{**receipt,'status':'unconfirmed'}]}],
                         [{'role':'assistant','home_actions':[receipt]},{'role':'assistant','content':'Different subject'}]):
            with self.assertRaises(ValueError):self.routines.from_recent('Wrong',messages)

    def test_play_uses_play_capability_not_play_media(self):
        self.home.states['media_player.test']['attributes']['supported_features']=512
        with self.assertRaises(ValueError):self.routines.save('Play',[{'entity_id':'media_player.test','action':'play'}])
        self.home.states['media_player.test']['attributes']['supported_features']=16384
        item=self.routines.save('Play',[{'entity_id':'media_player.test','action':'play'}])
        self.assertEqual(self.run_item(item)['status'],'complete')

    def test_agent_exact_commands_do_not_call_model_or_save_routine_as_fact(self):
        agent=EchoAgent(SettingsStore(),provider=Mock());agent.routines=self.routines;agent.home_access=self.access
        token,_=agent.context('owner')
        agent._append_exchange('owner',token,'Dim it',{'role':'assistant','content':'Verified','home_actions':[{**self.steps[0],'status':'complete'}]})
        result=agent.respond('Remember this as Movie mode','owner')
        self.assertEqual(result['status'],'complete');self.assertEqual(agent.memory.snapshot(),[])
        self.assertFalse(self.home.writes)
        self.assertEqual(agent.respond('Run routine Movie mode','owner')['status'],'unavailable')
        self.assertEqual(agent.respond('Run routine Movie mode','owner',allow_home_actions=True)['status'],'complete')
        self.assertIn('Movie mode',agent.respond('List my routines','owner')['text'])
        agent.provider.complete.assert_not_called()
        self.assertEqual(routine_request('remember that I prefer tea'),None)

    def test_api_owner_auth_crud_exact_revision_run_and_validation_mode(self):
        token='test-routine-owner-'*3
        app=create_app(token,home=self.home,runtime_root=self.root,home_access_store=self.access)
        with TestClient(app,base_url='http://localhost') as api:
            body={'name':'Movie mode','steps':self.steps}
            self.assertEqual(api.post('/v1/routines',json=body).status_code,401)
            api.headers['Authorization']='Bearer '+token
            item=api.post('/v1/routines',json=body).json()['item']
            self.assertEqual(api.get('/v1/routines').json()['items'],[item]);self.assertFalse(self.home.writes)
            path='/v1/routines/'+item['id']
            self.assertEqual(api.post(path+'/run',json={'revision':'0'*64}).status_code,409)
            result=api.post(path+'/run',json={'revision':item['revision']}).json()
            self.assertEqual(result['status'],'complete');self.assertEqual(len(self.home.writes),2)
            self.assertEqual(api.get('/v1/chat/activity').json()['state'],'completed')
            self.assertEqual(api.post('/v1/text',json={'text':'Run routine Movie mode'}).json()['status'],'complete')
            self.assertEqual(len(self.home.writes),2)  # Already at the saved settings: no second write.
            self.assertEqual(api.request('DELETE',path,json={'revision':item['revision']}).status_code,200)
        # Saving never changes grants and a validation host cannot execute routines.
        item=self.save();self.actions.enabled=False;self.home.calls=[]
        self.assertEqual(self.run_item(item)['status'],'unavailable');self.assertFalse(self.home.writes)


if __name__=='__main__':unittest.main()
