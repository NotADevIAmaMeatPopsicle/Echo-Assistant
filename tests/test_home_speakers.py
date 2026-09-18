import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from concurrent.futures import Future
from unittest.mock import Mock
import httpx
from fastapi.testclient import TestClient
from backend.home import HomeBridge,HomeConfig,HomeUnavailable
from backend.home_speakers import HomeSpeakers
from backend.settings import default_protector
from backend.app import create_app
from backend.display import HomeDisplay,home_lines


class SpeakerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.protector=default_protector()
        self.states={k:{'entity_id':'media_player.'+k,'state':'off','attributes':{'volume_level':.1,'supported_features':4|8|128|256|16384|1}} for k in ('bose','bedroom')}
        self.writes=[]
        def request(r):
            if r.method=='GET':return httpx.Response(200,json=self.states[r.url.path.rsplit('.',1)[-1]])
            self.writes.append((r.url.path,json.loads(r.content)));return httpx.Response(200,json=[])
        self.bridge=HomeBridge(HomeConfig(True,'http://192.168.1.2:8123','test-secret',{'soundbar':'media_player.bose'}),httpx.MockTransport(request))
        self.catalog=Mock();self.catalog.snapshot.side_effect=lambda **_: {'devices':[
            {'entity_id':v['entity_id'],'name':k.title(),'domain':'media_player','available':v['state']!='unavailable',
             'state':v['state'],'attributes':copy.deepcopy(v['attributes'])} for k,v in self.states.items()]}
        self.speakers=HomeSpeakers(self.bridge,self.catalog,self.root,self.protector)

    def test_select_is_silent_encrypted_and_survives_restart(self):
        s=self.speakers.snapshot();self.assertEqual(s['name'],'Bose')
        self.speakers.select(0,s['revision'])
        self.assertFalse(self.writes)
        self.assertNotIn('media_player.bedroom',(self.root/'local/speaker-selection.json').read_text())
        restored=HomeSpeakers(self.bridge,self.catalog,self.root,self.protector)
        self.assertEqual(restored.snapshot()['name'],'Bedroom')
        self.assertEqual(self.bridge.config.entities['soundbar'],'media_player.bose')

    def test_buttons_only_change_selected_target_in_small_steps(self):
        s=self.speakers.snapshot();self.speakers.select(0,s['revision']);s=self.speakers.snapshot()
        self.speakers.action('up',s['binding']);self.speakers.action('down',s['binding'])
        self.assertEqual(self.writes,[('/api/services/media_player/volume_set',{'entity_id':'media_player.bedroom','volume_level':.12}),
                                      ('/api/services/media_player/volume_set',{'entity_id':'media_player.bedroom','volume_level':.08})])

    def test_old_button_binding_and_changed_list_rejected(self):
        old=self.speakers.snapshot();self.speakers.select(0,old['revision'])
        with self.assertRaises(ValueError):self.speakers.action('up',old['binding'])
        self.states.pop('bose')
        with self.assertRaises(ValueError):self.speakers.select(1,old['revision'])
        self.assertFalse(self.writes)

    def test_unavailable_and_unsupported_volume_do_not_write(self):
        self.states['bose']['state']='unavailable'
        with self.assertRaises(HomeUnavailable):self.speakers.action('up',self.speakers.snapshot()['binding'])
        self.states['bose']['state']='off';self.states['bose']['attributes']['supported_features']=0
        with self.assertRaises(ValueError):self.speakers.action('up',self.speakers.snapshot()['binding'])
        self.assertFalse(self.writes)

    def test_corrupt_selection_preserved_and_never_falls_back_to_bose(self):
        p=self.root/'local/speaker-selection.json';p.parent.mkdir();p.write_text('damaged')
        broken=HomeSpeakers(self.bridge,self.catalog,self.root,self.protector)
        with self.assertRaises(HomeUnavailable):broken.snapshot()
        self.assertEqual(p.read_text(),'damaged')

    def test_display_list_is_bounded_and_commands_are_serialized(self):
        state=self.speakers.snapshot();lines=home_lines({'speakers':state})
        self.assertIn('HOME_SELECTED '+state['binding']+' Bose\n',lines)
        self.assertTrue(all(len(line)<192 for line in lines))
        worker=Mock();worker.submit.return_value=Future();write=Mock();display=HomeDisplay(Mock(),worker,write)
        event='EVENT speaker_action=up request=7 binding='+state['binding']
        display.receive(event);display.receive(event)
        self.assertEqual(worker.submit.call_count,1)
        self.assertEqual(worker.submit.call_args.args[1:],(False,'up',state['binding']))
        self.assertEqual(write.call_args.args[0],b'HOME_ACK 7 pending\n')

    def test_owner_auth_required_and_selection_reaches_real_controller(self):
        token='test-owner-credential-long-enough'
        app=create_app(token,home=self.bridge,runtime_root=self.root,home_catalog=self.catalog)
        with TestClient(app,base_url='http://localhost') as client:
            route='/v1/home/speakers/select';body={'index':0,'revision':self.speakers.snapshot()['revision']}
            self.assertEqual(client.post(route,json=body).status_code,401)
            response=client.post(route,json=body,headers={'Authorization':'Bearer '+token})
            self.assertEqual(response.status_code,200)
            self.assertFalse(self.writes)


if __name__=='__main__':unittest.main()
