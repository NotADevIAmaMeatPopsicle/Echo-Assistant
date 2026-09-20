"""Presence permissions and freshness, using synthetic HA states only."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.experiences import Experiences, SourceStore, Sources
from backend.home import HomeUnavailable


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.states = [
            {'entity_id': 'binary_sensor.study', 'state': 'on', 'attributes': {
                'device_class': 'occupancy', 'friendly_name': 'Study', 'private_attribute': 'never-export'}},
            {'entity_id': 'binary_sensor.motion', 'state': 'off', 'attributes': {'device_class': 'motion'}},
            {'entity_id': 'binary_sensor.presence', 'state': 'off', 'attributes': {'device_class': 'presence'}},
            {'entity_id': 'binary_sensor.door', 'state': 'on', 'attributes': {'device_class': 'door'}},
            {'entity_id': 'device_tracker.phone', 'state': 'home', 'attributes': {}},
        ]
        self.home = SimpleNamespace(config=SimpleNamespace(enabled=True), _request=Mock(side_effect=lambda *_: deepcopy(self.states)))
        self.store = SourceStore(None, None)
        self.features = Experiences(self.home, self.store)

    def select(self):
        self.features.save_sources({'presence_sensors': ['binary_sensor.study']}, 0)
        self.home._request.reset_mock()

    def test_explicit_selection_class_filter_and_no_attributes(self):
        self.assertEqual(self.features.presence()['items'], [])
        self.home._request.assert_not_called()
        inventory = self.features.discovery()['items']
        self.assertEqual({i['entity_id'] for i in inventory if i['can_detect_presence']},
                         {'binary_sensor.study', 'binary_sensor.motion', 'binary_sensor.presence'})
        for value in (['binary_sensor.door'], ['device_tracker.phone'], ['binary_sensor.study'] * 2):
            with self.assertRaises(ValueError): self.features.save_sources({'presence_sensors': value}, 0)
        self.select()
        result = self.features.presence()
        self.assertEqual(result['items'], [{'entity_id': 'binary_sensor.study', 'name': 'Study', 'available': True, 'occupied': True}])
        self.assertNotIn('never-export', str(result))
        self.assertEqual(Sources.model_validate(self.store.snapshot()['sources']).presence_sensors, ['binary_sensor.study'])

    def test_cache_expiry_unavailability_and_class_changes(self):
        self.select()
        with patch('backend.experiences.monotonic', return_value=10): self.features.presence()
        with patch('backend.experiences.monotonic', return_value=11): self.features.presence()
        self.assertEqual(self.home._request.call_count, 1)
        self.home._request.side_effect = HomeUnavailable('offline')
        with patch('backend.experiences.monotonic', return_value=15), self.assertRaises(HomeUnavailable):
            self.features.presence()  # Expired data is never served on failure.
        self.home._request.side_effect = lambda *_: deepcopy(self.states)
        for state in ('unknown', 'unavailable', None):
            self.states[0]['state'] = state
            with patch('backend.experiences.monotonic', return_value=20 + ('unknown', 'unavailable', None).index(state) * 5):
                item = self.features.presence()['items'][0]
            self.assertFalse(item['available']); self.assertIsNone(item['occupied'])
        self.states[0]['state'] = 'on'; self.states[0]['attributes']['device_class'] = 'door'
        with patch('backend.experiences.monotonic', return_value=40):
            self.assertIsNone(self.features.presence()['items'][0]['occupied'])

    def test_revocation_during_request_and_after_cached_reply(self):
        self.select()
        self.features.presence()
        self.features.save_sources({}, 1)
        self.assertEqual(self.features.presence()['items'], [])
        self.features.save_sources({'presence_sensors': ['binary_sensor.study']}, 2)
        def revoke(*_):
            self.store.save({}, 3)
            return deepcopy(self.states)
        self.home._request.side_effect = revoke
        self.assertEqual(self.features.presence()['items'], [])


if __name__ == '__main__': unittest.main()
