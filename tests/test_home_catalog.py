import unittest
import httpx
from backend.home import HomeBridge, HomeConfig
from backend.home_catalog import HomeCatalog


class HomeCatalogTests(unittest.TestCase):
    def catalog(self, registry):
        states = [
            {'entity_id':'light.desk','state':'on','attributes':{'friendly_name':'Living room lamp',
              'brightness':80,'access_token':'must-not-escape'}},
            {'entity_id':'light.other','state':'unavailable','attributes':{}},
            {'entity_id':'person.owner','state':'home','attributes':{'latitude':1}},
        ]
        def http(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.url.path, '/api/states')
            return httpx.Response(200,json=states)
        config = HomeConfig(enabled=True, base_url='http://192.168.1.2:8123',token='synthetic',
                            entities={'soundbar':'media_player.test'})
        return HomeCatalog(HomeBridge(config, httpx.MockTransport(http)), registry)

    def test_room_uses_registry_and_private_attributes_are_removed(self):
        registry = lambda: ([{'area_id':'office','name':'Office'}],
            [{'id':'device1','area_id':'office'}], [{'entity_id':'light.desk','device_id':'device1','area_id':None}])
        result = self.catalog(registry).snapshot('light','Office')
        self.assertEqual(len(result['devices']),1)
        self.assertEqual(result['devices'][0]['area'],'Office')
        self.assertNotIn('access_token',result['devices'][0]['attributes'])
        self.assertEqual(result['devices'][0]['attributes']['brightness'],80)

    def test_unavailable_registry_does_not_guess_from_name(self):
        def broken(): raise ConnectionError()
        result = self.catalog(broken).snapshot()
        self.assertFalse(result['registry_available'])
        self.assertEqual(len(result['devices']),2)
        self.assertIsNone(result['devices'][0]['area'])
        self.assertFalse(result['devices'][1]['available'])
        self.assertEqual(self.catalog(broken).snapshot(area='Living room')['devices'],[])

    def test_unknown_entities_and_domains_are_rejected(self):
        catalog = self.catalog(lambda:([],[],[]))
        with self.assertRaises(ValueError): catalog.state('person.owner')
        with self.assertRaises(ValueError): catalog.snapshot(domain='person')
