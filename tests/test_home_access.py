import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.home_access import HomeAccessStore, HomeAccessUnavailable
from backend.home_policy import apply_policy, validate_policy
from backend.agent import EchoAgent
from backend.settings import SettingsStore, EchoSettings, SettingsUpdate


POLICY = {'default_access':'hidden','devices':{'light.desk':{'access':'read','room':'Study'}}}
INVENTORY = {'registry_available':True,'areas':['Bedroom','Kitchen'], 'devices':[
    {'entity_id':'light.desk','name':'Desk','domain':'light','area':'Bedroom','state':'on','available':True,'attributes':{}},
    {'entity_id':'light.private','name':'Private','domain':'light','area':'Kitchen','state':'unavailable','available':False,'attributes':{}}]}


class HomeAccessTests(unittest.TestCase):
    def test_hidden_devices_removed_from_states_rooms_and_counts(self):
        visible = apply_policy(INVENTORY,POLICY)
        self.assertEqual(visible['counts'],{'total':1,'available':1,'unavailable':0,'without_area':0})
        self.assertEqual(visible['areas'],['Study'])
        self.assertEqual(visible['devices'][0]['ha_area'],'Bedroom')
        self.assertEqual(visible['devices'][0]['area_source'],'echo')
        self.assertNotIn('Private',json.dumps(visible))
        self.assertEqual(len(apply_policy(INVENTORY,POLICY,management=True)['devices']),2)
        self.assertEqual(INVENTORY['devices'][0]['area'],'Bedroom')

    def test_invalid_policies_cannot_grant_write_or_arbitrary_entities(self):
        for candidate in ({}, {'default_access':'write','devices':{}},
                          {'default_access':'read','devices':{'lock.front':{'access':'read','room':''}}},
                          {'default_access':'read','devices':{'light.desk':{'access':'write','room':''}}},
                          {'default_access':'read','devices':{'light.desk':{'access':'read','room':'bad\nroom'}}}):
            with self.assertRaises(ValueError): validate_policy(candidate)

    def test_encrypted_reload_requires_remote_sync_and_compare_revision(self):
        with TemporaryDirectory() as folder:
            sync=Mock();store=HomeAccessStore(Path(folder),synchronizer=sync)
            initial=store.snapshot()['revision'];store.update(POLICY,initial)
            self.assertNotIn('Study',store.path.read_text())
            restored=HomeAccessStore(Path(folder),synchronizer=sync)
            self.assertFalse(restored.snapshot()['applied'])
            restored.ensure_applied();self.assertTrue(restored.snapshot()['applied'])
            self.assertEqual(restored.snapshot()['policy'],POLICY)
            with self.assertRaises(ValueError):restored.update(POLICY,initial)

    def test_failed_sync_keeps_saved_restriction_pending_for_retry(self):
        sync=Mock(side_effect=RuntimeError('private transport detail'))
        store=HomeAccessStore(synchronizer=sync)
        with self.assertRaisesRegex(HomeAccessUnavailable,'saved locally'):
            store.update(POLICY,store.snapshot()['revision'])
        self.assertEqual(store.snapshot()['policy'],POLICY)
        self.assertFalse(store.snapshot()['applied'])
        sync.side_effect=None;store.ensure_applied();self.assertTrue(store.snapshot()['applied'])

    def test_failed_atomic_save_and_corrupt_file_preserve_settings(self):
        with TemporaryDirectory() as folder:
            store=HomeAccessStore(Path(folder),synchronizer=Mock())
            store.update(POLICY,store.snapshot()['revision']);before=store.path.read_bytes()
            with patch.object(Path,'replace',side_effect=PermissionError):
                with self.assertRaises(HomeAccessUnavailable):store.update({'default_access':'read','devices':{}},store.snapshot()['revision'])
            self.assertEqual(store.path.read_bytes(),before)
            store.path.write_text('corrupt')
            with self.assertRaises(HomeAccessUnavailable):HomeAccessStore(Path(folder)).snapshot()
            self.assertEqual(store.path.read_text(),'corrupt')

    def test_authenticated_management_rejects_unknown_entities_without_actuation(self):
        sync=Mock();access=HomeAccessStore(synchronizer=sync)
        catalog=Mock();catalog.snapshot.return_value=copy.deepcopy(INVENTORY)
        client=TestClient(create_app('s'*40,home_catalog=catalog,home_access_store=access))
        self.assertEqual(client.get('/v1/home/devices').status_code,401)
        headers={'Authorization':'Bearer '+'s'*40}
        state=client.get('/v1/home/devices',headers=headers).json()
        unknown=copy.deepcopy(POLICY);unknown['devices']['light.fictional']={'access':'read','room':''}
        self.assertEqual(client.put('/v1/home/access',headers=headers,json={'policy':unknown,'revision':state['revision']}).status_code,422)
        sync.assert_not_called()
        response=client.put('/v1/home/access',headers=headers,json={'policy':POLICY,'revision':state['revision']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['applied']);sync.assert_called_once_with(POLICY)

    def test_changed_home_access_discards_inflight_reply_and_history(self):
        settings=SettingsStore();settings.save(SettingsUpdate(settings=EchoSettings(provider='local',model='test')))
        provider=Mock();provider.complete.return_value='Previous state'
        agent=EchoAgent(settings,provider);access=HomeAccessStore(synchronizer=Mock());agent.home_access=access
        self.assertEqual(agent.respond('Read something')['status'],'complete')
        self.assertTrue(agent.messages('device'))
        def changing(*args,**kwargs):
            access.update(POLICY,access.snapshot()['revision']);return 'Stale private state'
        provider.complete.side_effect=changing
        answer=agent.respond('Read again')
        self.assertEqual(answer['status'],'unavailable')
        self.assertNotIn('Stale private state',answer['text'])
        self.assertEqual(agent.messages('device'),[])
