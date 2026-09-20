"""Private Google OAuth/storage/agenda isolation against an entirely fake provider."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.display_profiles import DisplayProfile, ScopedSources
from backend.experiences import Experiences, ExperienceConflict
from backend.google_calendar import READ_SCOPES, WRITE_SCOPE
from backend.home import HomeUnavailable
from backend.member_google import MemberGoogle
from backend.member_google_api import install
from backend.member_agenda import MemberAgenda
from backend.members import Members
from tests.test_google_calendar_write import WriteFixture


class PrivateFixture(WriteFixture):
    def setUp(self):
        super().setUp()
        self.now = 1000
        self.members = Members(self.root, self.protector, clock=lambda: self.now, wall=lambda: self.now)
        self.members.base_profile = lambda endpoint: {'profile': DisplayProfile().model_dump(), 'profile_revision': 0}
        self.alice = self.members.create('Synthetic Alice')
        self.bob = self.members.create('Synthetic Bob')
        self.service = MemberGoogle(self.members, self.google, self.root, self.protector)
        self.members.on_lock = self.service.cancel_session
        self.principal = self.login(self.alice)
        self.calls.clear()

    def login(self, member, endpoint='owner-one'):
        return self.members.login(endpoint, member['id'], member['passcode'])

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, deepcopy(kwargs)))
        if self.interrupt:
            self.interrupt(method, url)
        if url.endswith('/token'):
            data = kwargs['data']
            identity = (data['code'] if data['grant_type'] == 'authorization_code' else data['refresh_token'].removeprefix('refresh-'))
            return {'access_token': 'access-' + identity, 'refresh_token': 'refresh-' + identity,
                    'scope': ' '.join((*READ_SCOPES, WRITE_SCOPE)), 'expires_in': 3600}
        identity = kwargs.get('headers', {}).get('Authorization', '').removeprefix('Bearer access-')
        if '/calendarList' in url:
            row = {'id': identity + '@example.com', 'summary': identity + ' calendar',
                   'timeZone': 'America/New_York', 'accessRole': 'owner'}
            return {'items': [row]} if url.endswith('/calendarList') else row
        if method == 'GET' and url.endswith('/events'):
            return {'items': [{'id': 'event_' + identity, 'etag': '"v1"', 'summary': identity + ' event',
                               'organizer': {'self': True},
                               'start': {'dateTime': '2026-09-22T10:00:00-04:00'},
                               'end': {'dateTime': '2026-09-22T11:00:00-04:00'}}]}
        raise AssertionError('Unexpected synthetic Google operation')

    def link(self, principal=None, identity='alice', *, select=True):
        principal = principal or self.principal
        flow = self.service.begin(principal, identity + ' private label', 'a' * 64)
        state = parse_qs(urlsplit(flow['url']).query)['state'][0]
        self.assertTrue(self.service.callback(state, identity, ''))
        account = self.service.finish(principal, flow['id'], 'a' * 64)
        self.service.sync(principal, account['id'])
        settings = self.service.settings(principal)
        entity = settings['calendars'][-1]['entity_id']
        if select:
            self.service.select(principal, [entity], settings['revision'])
        return account, entity


class MemberGoogleTests(PrivateFixture, unittest.TestCase):
    def test_read_only_consent_uses_owner_client_and_separate_callback_state(self):
        flow = self.service.begin(self.principal, 'Private account', 'a' * 64)
        query = parse_qs(urlsplit(flow['url']).query)
        self.assertEqual(set(query['scope'][0].split()), set(READ_SCOPES))
        self.assertEqual(query['client_id'][0], self.google.config.client_id)
        self.assertEqual(query['redirect_uri'][0], self.google.config.redirect_uri)
        self.assertFalse(self.service.callback('unowned-state-value' * 3, 'code', ''))
        self.assertTrue(self.service.callback(query['state'][0], 'alice', ''))
        with self.assertRaises(HTTPException):
            self.service.finish(self.principal, flow['id'], 'b' * 64)
        result = self.service.finish(self.principal, flow['id'], 'a' * 64)
        private = self.service.providers[self.principal.member]
        self.assertFalse(private.accounts[0]['write_access'])
        self.assertNotIn(result['id'], [account['id'] for account in self.google.accounts])
        self.assertEqual(len(self.google.accounts), 1)
        self.assertEqual(self.service.settings(self.principal)['calendars'], [])
        public = json.dumps(self.service.settings(self.principal))
        self.assertNotIn('refresh-', public)
        self.assertNotIn('client_secret', public)
        self.assertNotIn('client_id', public)

    def test_private_selection_works_without_any_shared_calendar_and_is_read_only(self):
        _, entity = self.link()
        self.assertEqual(self.members.profile_for(self.principal)['profile']['calendars'], [])
        scoped = self.service.scoped(self.principal, self.exp)
        self.assertEqual(scoped.store.snapshot()['sources']['calendars'], [entity])
        sources = scoped.sources()['items']
        self.assertEqual(len(sources), 1)
        self.assertFalse(any(sources[0][key] for key in ('writable', 'editable', 'deletable')))
        agenda = scoped.agenda('2026-09-22', 1)
        self.assertEqual([event['title'] for event in agenda['events']], ['alice event'])
        self.assertIsNone(agenda['events'][0]['reference'])
        self.assertIsNone(agenda['events'][0]['invitation_reference'])

    def test_personal_agenda_voice_path_reads_private_calendar_without_shared_grants(self):
        self.link()
        schedules = SimpleNamespace(snapshot=lambda: {'quiet': {'timezone': 'UTC'}})
        displays = SimpleNamespace(profile_for=self.members.profile_for)
        clock = lambda: datetime(2026, 9, 22, 13, tzinfo=timezone.utc).timestamp()
        agenda = MemberAgenda(self.exp, displays, schedules, clock=clock, personal_google=self.service)
        result = agenda.respond('today', self.principal, self.members.profile_for(self.principal))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['event_count'], 1)
        self.assertIn('alice event', result['text'])

    def test_corrupt_member_provider_data_does_not_fall_back_to_household_credentials(self):
        self.link()
        saved = deepcopy(self.service.records)
        saved[self.alice['id']]['google']['accounts'][0]['refresh_token'] = None
        self.service.commit(saved)
        restored = MemberGoogle(self.members, self.google, self.root, self.protector)
        self.calls.clear()
        with self.assertRaises(HomeUnavailable):
            restored.settings(self.principal)
        self.assertEqual(self.calls, [])

    def test_private_and_explicit_shared_union_never_exports_to_household_guest_or_other_member(self):
        _, alice_entity = self.link()
        self.members.change(self.alice['id'], 0, profile={'mode': 'guest', 'calendars': [self.entity]})
        self.principal = self.login(self.alice)
        scoped = self.service.scoped(self.principal, self.exp)
        self.assertEqual(set(scoped.store.snapshot()['sources']['calendars']), {alice_entity, self.entity})
        self.assertEqual({event['title'] for event in scoped.agenda('2026-09-22', 1)['events']}, {'alice event', 'synthetic-code event'})
        self.assertNotIn(alice_entity, [row['entity_id'] for row in self.exp.sources()['items']])
        self.assertEqual([event['title'] for event in self.exp.agenda('2026-09-22', 1)['events']], ['synthetic-code event'])
        guest = Experiences(self.exp.home, ScopedSources(self.exp.store, lambda: DisplayProfile(mode='guest').model_dump()), google=self.google)
        self.assertEqual(guest.agenda('2026-09-22', 1)['events'], [])
        bob = self.login(self.bob, 'owner-two')
        _, bob_entity = self.link(bob, 'bob')
        self.assertEqual([event['title'] for event in self.service.scoped(bob, self.exp).agenda('2026-09-22', 1)['events']], ['bob event'])
        self.assertNotIn(alice_entity, [row['entity_id'] for row in self.service.settings(bob)['calendars']])
        self.assertNotEqual(alice_entity, bob_entity)

    def test_selection_rejects_foreign_shared_and_stale_identifiers(self):
        _, own = self.link()
        bob = self.login(self.bob, 'owner-two')
        _, other = self.link(bob, 'bob')
        revision = self.service.settings(self.principal)['revision']
        for entity in (self.entity, other):
            with self.assertRaises(ValueError):
                self.service.select(self.principal, [entity], revision)
        with self.assertRaises(ExperienceConflict):
            self.service.select(self.principal, [own], revision - 1)
        with self.assertRaises(ValueError):
            self.service.select(self.principal, [own, own], revision)

    def test_registry_restart_reuses_core_provider_validation_and_encrypted_selection(self):
        account, entity = self.link()
        content = self.service.path.read_bytes()
        for private in (b'alice private label', b'alice@example.com', b'refresh-alice', b'client_secret', entity.encode()):
            self.assertNotIn(private, content)
        restored = MemberGoogle(self.members, self.google, self.root, self.protector)
        settings = restored.settings(self.principal)
        self.assertEqual(settings['accounts'][0]['id'], account['id'])
        self.assertTrue(settings['calendars'][0]['selected'])
        self.assertEqual(restored.flows, {})
        self.assertEqual([event['title'] for event in restored.scoped(self.principal, self.exp).agenda('2026-09-22', 1)['events']], ['alice event'])
        self.assertFalse((self.root / 'local/member-google').exists())

    def test_switch_same_endpoint_cancels_flow_and_old_nonce_cannot_finish(self):
        flow = self.service.begin(self.principal, 'Private Alice', 'a' * 64)
        state = parse_qs(urlsplit(flow['url']).query)['state'][0]
        old = self.principal
        self.principal = self.login(self.bob)
        self.assertFalse(self.service.callback(state, 'alice', ''))
        with self.assertRaises(HTTPException):
            self.service.finish(old, flow['id'], 'a' * 64)
        with self.assertRaises(HTTPException):
            self.service.finish(self.principal, flow['id'], 'a' * 64)
        self.assertEqual(self.service.settings(self.principal)['accounts'], [])
        self.assertFalse(any(call[1].endswith('/token') for call in self.calls))

    def test_expired_session_and_deleted_member_clear_volatile_flows_and_private_storage(self):
        self.link()
        flow = self.service.begin(self.principal, 'Second private account', 'a' * 64)
        state = parse_qs(urlsplit(flow['url']).query)['state'][0]
        self.now += 901
        self.service.prune()
        self.assertFalse(self.service.callback(state, 'alice', ''))
        with self.assertRaises(HTTPException):
            self.service.settings(self.principal)
        self.members.change(self.alice['id'], 0, delete=True)
        self.service.remove_member(self.alice['id'])
        self.assertNotIn(self.alice['id'], self.service.records)
        self.assertNotIn(self.alice['id'], self.service.providers)
        restored = MemberGoogle(self.members, self.google, self.root, self.protector)
        self.assertNotIn(self.alice['id'], restored.records)

    def test_revocation_during_token_exchange_never_saves_a_grant(self):
        flow = self.service.begin(self.principal, 'Private account', 'a' * 64)
        state = parse_qs(urlsplit(flow['url']).query)['state'][0]
        self.interrupt = lambda method, url: self.members.lock_session(str(self.principal)) if url.endswith('/token') else None
        with self.assertRaises(HTTPException):
            self.service.callback(state, 'alice', '')
        self.assertEqual(self.service.providers[self.alice['id']].accounts, [])
        self.assertNotIn('refresh-alice', json.dumps(self.service.records))

    def test_owner_configuration_change_during_exchange_cancels_private_flow(self):
        flow = self.service.begin(self.principal, 'Private account', 'a' * 64)
        state = parse_qs(urlsplit(flow['url']).query)['state'][0]

        def change(method, url):
            if url.endswith('/token'):
                self.google.config = self.google.config.model_copy(update={'revision': self.google.config.revision + 1})

        self.interrupt = change
        with self.assertRaises(HTTPException):
            self.service.callback(state, 'alice', '')
        self.assertEqual(self.service.providers[self.alice['id']].accounts, [])

    def test_owner_client_replacement_requires_private_reconnect_but_disconnect_still_works(self):
        account, _ = self.link()
        self.google.config = self.google.config.model_copy(update={'revision': 2, 'client_id': 'replacement.apps.googleusercontent.com'})
        self.assertTrue(self.service.settings(self.principal)['needs_reconnect'])
        with self.assertRaises(HomeUnavailable):
            self.service.begin(self.principal, 'Another account', 'a' * 64)
        self.service.disconnect(self.principal, account['id'])
        self.assertFalse(self.service.settings(self.principal)['needs_reconnect'])

    def test_selection_disconnect_and_session_changes_mid_fetch_discard_result(self):
        account, _ = self.link()
        scoped = self.service.scoped(self.principal, self.exp)

        def deselect(method, url):
            if method == 'GET' and url.endswith('/events'):
                self.service.select(self.principal, [], self.service.settings(self.principal)['revision'])

        self.interrupt = deselect
        with self.assertRaises(ExperienceConflict):
            scoped.agenda('2026-09-22', 1)
        self.interrupt = None
        settings = self.service.settings(self.principal)
        self.service.select(self.principal, [settings['calendars'][0]['entity_id']], settings['revision'])
        self.interrupt = lambda method, url: self.service.disconnect(self.principal, account['id']) if method == 'GET' and url.endswith('/events') else None
        with self.assertRaises(ExperienceConflict):
            scoped.agenda('2026-09-22', 1)
        self.interrupt = None
        self.link()
        self.interrupt = lambda method, url: self.members.lock_session(str(self.principal)) if method == 'GET' and url.endswith('/events') else None
        with self.assertRaises(HTTPException):
            scoped.agenda('2026-09-22', 1)

    def test_unreadable_private_registry_preserves_file_and_blocks_private_settings(self):
        self.service.path.parent.mkdir(parents=True, exist_ok=True)
        self.service.path.write_text('not-an-encrypted-registry')
        restored = MemberGoogle(self.members, self.google, self.root, self.protector)
        with self.assertRaises(HomeUnavailable):
            restored.settings(self.principal)
        self.assertEqual(restored.path.read_text(), 'not-an-encrypted-registry')

    def test_no_calendar_api_writes_and_no_implicit_selection(self):
        _, entity = self.link(select=False)
        self.assertFalse(self.service.settings(self.principal)['calendars'][0]['selected'])
        self.assertNotIn(entity, self.service.scoped(self.principal, self.exp).store.snapshot()['sources']['calendars'])
        self.assertTrue(all(method == 'GET' or url.endswith('/token') for method, url, _ in self.calls))


class MemberGoogleApiTests(PrivateFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app = FastAPI()

        def authorize(request: Request):
            endpoint = request.headers.get('x-test-endpoint', 'owner-one')
            return self.members.resolve(endpoint)

        install(self.app, self.service, authorize)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_personal_only_routes_use_strict_read_only_request_shape(self):
        base = '/v1/member/calendar/google'
        self.assertEqual(self.client.get(base).status_code, 200)
        self.assertEqual(self.client.get(base, headers={'x-test-endpoint': 'household'}).status_code, 403)
        response = self.client.post(base + '/flows', json={'label': 'Private', 'client': 'a' * 64, 'write_access': True})
        self.assertEqual(response.status_code, 422)
        response = self.client.post(base + '/flows', json={'label': 'Private', 'client': 'a' * 64})
        self.assertEqual(response.status_code, 200)
        identifier = response.json()['id']
        self.assertEqual(self.client.get(base + '/flows/' + identifier + '?client=' + 'a' * 64).json()['status'], 'waiting')
        self.assertEqual(self.client.delete(base + '/accounts/' + 'b' * 32, headers={'x-test-endpoint': 'household'}).status_code, 403)
        self.members.lock_session('owner-one')
        self.assertEqual(self.client.get(base + '/flows/' + identifier + '?client=' + 'a' * 64).status_code, 403)


if __name__ == '__main__':
    unittest.main()
