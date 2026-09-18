import unittest
from unittest.mock import Mock
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.home_access import HomeAccessStore


class ContainerHostTests(unittest.TestCase):
    def setUp(self):
        self.home=Mock();self.home.config.enabled=True
        self.catalog=Mock();self.catalog.snapshot.return_value={
            'areas':['Study','Bedroom'],'registry_available':True,'devices':[
                {'entity_id':'light.allowed','name':'Desk','domain':'light','area':'Study','available':True,'state':'on','attributes':{}},
                {'entity_id':'light.hidden','name':'Private','domain':'light','area':'Bedroom','available':True,'state':'on','attributes':{}}]}
        self.access=HomeAccessStore(synchronizer=lambda policy:None)
        self.access.update({'default_access':'hidden','devices':{'light.allowed':{'access':'read','room':''}}},self.access.snapshot()['revision'])
        self.client=TestClient(create_app('a'*40,self.home,home_catalog=self.catalog,
            home_access_store=self.access,deployment_mode='validation',home_tools_token='t'*40))
        self.owner={'Authorization':'Bearer '+'a'*40}
        self.tool={'Authorization':'Bearer '+'t'*40}

    def test_tool_identity_only_reads_permitted_devices(self):
        self.assertEqual(self.client.get('/internal/home/devices',headers=self.owner).status_code,401)
        result=self.client.get('/internal/home/devices',headers=self.tool).json()
        self.assertEqual([d['entity_id'] for d in result['devices']],['light.allowed'])
        self.assertEqual(result['areas'],['Study'])
        self.assertEqual(self.client.get('/internal/home/state?entity_id=light.hidden',headers=self.tool).status_code,404)
        self.assertEqual(self.client.get('/v1/settings',headers=self.tool).status_code,401)
        self.assertEqual(self.client.get('/internal/home/devices?domain=climate',headers=self.tool).json()['counts']['total'],0)

    def test_validation_mode_rejects_actions_before_any_home_call(self):
        response=self.client.post('/v1/home/soundbar/actions',headers=self.owner,json={'action':'play'})
        self.assertEqual(response.status_code,409)
        self.home.act.assert_not_called()
        # Text bypasses the existing imperative home parser in this isolated host.
        response=self.client.post('/v1/text',headers=self.owner,json={'text':'turn on the soundbar'})
        self.assertEqual(response.json()['status'],'unavailable')
        self.home.answer.assert_not_called()
        self.assertEqual(self.client.get('/health').json()['deployment_mode'],'validation')

    def test_revoked_access_is_applied_without_restarting_tools(self):
        self.access.update({'default_access':'hidden','devices':{}},self.access.snapshot()['revision'])
        result=self.client.get('/internal/home/devices',headers=self.tool).json()
        self.assertEqual(result['devices'],[])
        self.assertEqual(self.client.get('/internal/home/state?entity_id=light.allowed',headers=self.tool).status_code,404)


if __name__=='__main__':unittest.main()
