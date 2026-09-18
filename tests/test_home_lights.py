import copy
import unittest
from concurrent.futures import Future
from unittest.mock import Mock
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.home import HomeBridge, HomeUnavailable
from backend.home_access import HomeAccessStore
from backend.home_lights import RoomLights
from backend.display import HomeDisplay, home_lines
from backend.cable import Decoder


def bulb(name, room, state='off'):
    return {'entity_id':'light.'+name,'domain':'light','name':name,'area':room,
            'state':state,'available':state!='unavailable','attributes':{}}


class RoomLightTests(unittest.TestCase):
    def setUp(self):
        self.access=HomeAccessStore(synchronizer=lambda _:None)
        self.catalog=Mock()
        self.inventory={'areas':['Bedroom','Patio'],'devices':[
            bulb('one','Bedroom','on'),bulb('two','Bedroom'),bulb('outside','Patio'),bulb('unnamed',None)]}
        self.catalog.snapshot.side_effect=lambda **_:copy.deepcopy(self.inventory)
        self.bridge=Mock();self.bridge._request.return_value={'state':'off'}
        self.rooms=RoomLights(self.bridge,self.catalog,self.access)

    def test_actual_rooms_mixed_and_unassigned_are_truthful(self):
        data=self.rooms.snapshot();rooms=data['rooms']
        self.assertEqual([r['state'] for r in rooms],['mixed','unassigned','unassigned','off'])
        self.assertEqual(rooms[0]['count'],2)
        self.assertEqual(home_lines({'lights':data})[4],f"HOME_LIGHTS 9 1 1 9 {data['revision']}\n")
        self.bridge._request.assert_not_called()

    def test_touch_explicit_state_once_for_only_this_room(self):
        data=self.rooms.snapshot();result=self.rooms.action('bedroom','turn_off',data['revision'])
        self.assertTrue(result['verified'])
        writes=[c.args for c in self.bridge._request.call_args_list if c.args[0]=='POST']
        self.assertEqual(writes,[('POST','/api/services/light/turn_off',{'entity_id':['light.one','light.two']})])
        self.assertEqual(self.access.snapshot()['policy']['devices'],{}) # No agent grants.

    def test_single_bulb_control_uses_one_exact_target_without_agent_grant(self):
        before=self.access.snapshot()
        self.bridge._request.side_effect=[{'state':'off'},{},{'state':'on'}]
        result=self.rooms.light_action('light.unnamed','turn_on',before['revision'])
        self.assertEqual(result,{'entity_id':'light.unnamed','action':'turn_on','status':'accepted','verified':True,'state':'on'})
        writes=[c.args for c in self.bridge._request.call_args_list if c.args[0]=='POST']
        self.assertEqual(writes,[('POST','/api/services/light/turn_on',{'entity_id':'light.unnamed'})])
        self.assertEqual(self.access.snapshot(),before)

    def test_single_bulb_noop_and_unverified_readback(self):
        revision=self.access.snapshot()['revision']
        result=self.rooms.light_action('light.unnamed','turn_off',revision)
        self.assertEqual(result['status'],'already_set');self.assertTrue(result['verified'])
        self.assertFalse(any(c.args[0]=='POST' for c in self.bridge._request.call_args_list))
        for observed in ({'state':'off'},HomeUnavailable('read failed')):
            self.bridge._request.reset_mock();self.bridge._request.side_effect=[{'state':'off'},{},observed]
            result=self.rooms.light_action('light.unnamed','turn_on',revision)
            self.assertEqual(result['status'],'accepted');self.assertFalse(result['verified'])
            self.assertEqual(sum(c.args[0]=='POST' for c in self.bridge._request.call_args_list),1)

    def test_single_bulb_rejects_stale_hidden_missing_invalid_and_unavailable(self):
        revision=self.access.snapshot()['revision']
        for entity,action,rev in [('light.unnamed','turn_on','0'*64),('light.missing','turn_on',revision),
                                  ('media_player.test','turn_on',revision),('light.unnamed','toggle',revision)]:
            with self.assertRaises(ValueError):self.rooms.light_action(entity,action,rev)
        self.access.update({'default_access':'read','devices':{'light.unnamed':{'access':'hidden','room':''}}},revision)
        with self.assertRaises(ValueError):self.rooms.light_action('light.unnamed','turn_on',self.access.snapshot()['revision'])
        self.bridge._request.assert_not_called()
        self.bridge._request.return_value={'state':'unavailable'}
        with self.assertRaises(HomeUnavailable):self.rooms.light_action('light.one','turn_off',self.access.snapshot()['revision'])
        self.assertFalse(any(c.args[0]=='POST' for c in self.bridge._request.call_args_list))

    def test_single_bulb_busy_ambiguous_send_and_policy_change_do_not_retry(self):
        revision=self.access.snapshot()['revision']
        self.rooms.lock.acquire()
        try:
            with self.assertRaises(HomeUnavailable):self.rooms.light_action('light.unnamed','turn_on',revision)
        finally:self.rooms.lock.release()
        self.bridge._request.assert_not_called()
        self.bridge._request.side_effect=[{'state':'off'},HomeUnavailable('reply lost')]
        with self.assertRaisesRegex(HomeUnavailable,'not confirmed'):self.rooms.light_action('light.unnamed','turn_on',revision)
        self.assertEqual(sum(c.args[0]=='POST' for c in self.bridge._request.call_args_list),1)
        def change_policy(*args):
            self.access.update({'default_access':'hidden','devices':{}},revision)
            return {'state':'off'}
        self.bridge._request.reset_mock();self.bridge._request.side_effect=change_policy
        with self.assertRaises(ValueError):self.rooms.light_action('light.unnamed','turn_on',revision)
        self.assertFalse(any(c.args[0]=='POST' for c in self.bridge._request.call_args_list))

    def test_single_bulb_route_auth_validation_and_success(self):
        token='test-owner-token-at-least-32-characters'
        path='/v1/home/lights/light.unnamed/actions';body={'action':'turn_on','revision':self.access.snapshot()['revision']}
        headers={'Authorization':'Bearer '+token}
        app=create_app(token,home=self.bridge,home_catalog=self.catalog,home_access_store=self.access)
        with TestClient(app) as client:
            self.assertEqual(client.post(path,json=body).status_code,401)
            self.assertEqual(client.post(path,headers=headers,json={**body,'action':'toggle'}).status_code,422)
            self.assertEqual(client.post(path,headers=headers,json={**body,'revision':'0'*64}).status_code,409)
            self.bridge._request.assert_not_called()
            self.bridge._request.side_effect=[{'state':'off'},{},{'state':'on'}]
            self.assertTrue(client.post(path,headers=headers,json=body).json()['verified'])
        self.bridge._request.reset_mock()
        app=create_app(token,home=self.bridge,home_catalog=self.catalog,home_access_store=self.access,deployment_mode='validation')
        with TestClient(app) as client:
            self.assertEqual(client.post(path,headers=headers,json=body).status_code,409)
        self.bridge._request.assert_not_called()

    def test_stale_room_binding_cannot_operate_new_members(self):
        before=self.rooms.snapshot()['revision']
        self.inventory['devices'].append(bulb('three','Bedroom'))
        with self.assertRaises(ValueError):self.rooms.action('bedroom','turn_off',before)
        self.bridge._request.assert_not_called()

    def test_unavailable_member_and_unassigned_room_do_not_partially_act(self):
        self.inventory['devices'][1]['state']='unavailable'
        for room in ('bedroom','dining_room'):
            with self.assertRaises(HomeUnavailable):self.rooms.action(room,'turn_on',self.rooms.snapshot()['revision'])
        self.bridge._request.assert_not_called()

    def test_saved_room_overrides_registry_hidden_stays_hidden(self):
        p=self.access.snapshot()
        self.access.update({'default_access':'read','devices':{
            'light.one':{'access':'read','room':'Living Room'},
            'light.two':{'access':'hidden','room':'Bedroom'}}},p['revision'])
        data=self.rooms.snapshot()
        self.assertEqual(data['rooms'][0]['state'],'unassigned')
        self.assertEqual(data['rooms'][1]['entities'],['light.one'])

    def test_transport_failure_is_not_retried_or_claimed_verified(self):
        self.bridge._request.side_effect=HomeUnavailable('lost response')
        with self.assertRaises(HomeUnavailable):self.rooms.action('bedroom','turn_on',self.rooms.snapshot()['revision'])
        self.assertEqual(self.bridge._request.call_count,1)
        self.bridge._request.reset_mock();self.bridge._request.side_effect=[{},HomeUnavailable('readback failed')]
        result=self.rooms.action('bedroom','turn_on',self.rooms.snapshot()['revision'])
        self.assertEqual(result['status'],'accepted');self.assertFalse(result['verified'])

    def test_unknown_actions_and_overlapping_requests_rejected(self):
        revision=self.rooms.snapshot()['revision']
        for room,action in [('garage','turn_off'),('bedroom','toggle')]:
            with self.assertRaises(ValueError):self.rooms.action(room,action,revision)
        self.rooms.lock.acquire()
        try:
            with self.assertRaises(HomeUnavailable):self.rooms.action('bedroom','turn_off',revision)
        finally:self.rooms.lock.release()
        self.bridge._request.assert_not_called()

    def test_new_route_auth_and_binding_contract(self):
        token='test-owner-token-at-least-32-characters'
        app=create_app(token,home=HomeBridge.__new__(HomeBridge),home_catalog=self.catalog,home_access_store=self.access)
        # Only room route is exercised; all requests are rejected before any HA IO.
        with TestClient(app) as client:
            path='/v1/home/rooms/bedroom/actions'
            self.assertEqual(client.post(path,json={'action':'turn_on','revision':'0'*64}).status_code,401)
            headers={'Authorization':'Bearer '+token}
            self.assertEqual(client.post(path,headers=headers,json={'action':'toggle','revision':'0'*64}).status_code,422)
            self.assertEqual(client.post(path,headers=headers,json={'action':'turn_on','revision':'0'*64}).status_code,409)

    def test_button_events_pass_decoder_and_light_commands_are_bounded(self):
        decoder=Decoder();_,lines=decoder.feed(b'BUTTON ready=1 level=0 toggles=2 errors=0\n')
        self.assertEqual(len(lines),1)
        worker=Mock();worker.submit.return_value=Future();write=Mock()
        display=HomeDisplay(Mock(),worker,write)
        event='EVENT light_action=bedroom:off request=71 binding='+'a'*64
        display.receive(event);display.receive(event)
        self.assertEqual(worker.submit.call_count,1)
        self.assertEqual(worker.submit.call_args.args[1:],('bedroom','off','a'*64))
        self.assertEqual(write.call_args.args[0],b'HOME_ACK 71 pending\n')
        worker.reset_mock()
        for invalid in ('EVENT light_action=garage:on request=2 binding='+'a'*64,
                        'EVENT light_action=bedroom:toggle request=3 binding='+'a'*64,
                        'EVENT light_action=bedroom:on request=0 binding='+'a'*64,
                        event+'\nEVENT home_action=sound_on'):
            display.receive(invalid)
        worker.submit.assert_not_called()


if __name__=='__main__':unittest.main()
