"""Wave 2 seams through the actual app, with synthetic Google and no lifespan."""
from copy import deepcopy
import hashlib
import json
import unittest

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.calendar_events import CalendarEvent
from backend.calendar_invitations import reference_for
from backend.google_calendar_write import GoogleCalendarWriter
from tests.test_google_calendar import configuration
from tests.test_google_calendar_series import SeriesFixture


class CalendarWave2IntegrationTests(SeriesFixture, unittest.TestCase):
    def setUp(self):
        self.agenda_items = []
        super().setUp()
        self.app = create_app('x' * 40)
        # Deliberately do not enter lifespan: no scheduler, home, media or audio.
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.owner = {'Authorization': 'Bearer ' + 'x' * 40}
        google = self.app.state.google_calendars
        google.transport = self.transport
        google.configure(configuration())
        google.commit(google.config, self.google.accounts)
        self.google = google
        self.writer = self.app.state.calendar_invitations.writer
        self.exp = self.writer.experiences
        self.adapter = GoogleCalendarWriter(self.writer)
        result = self.client.put('/v1/display/source-settings', headers=self.owner, json={
            'revision': 0, 'sources': {'calendars': [self.entity], 'writable_calendars': [self.entity],
                                     'managed_calendars': [self.entity]}})
        self.assertEqual(result.status_code, 200, result.text)
        self.displays = self.app.state.calling.displays
        self.paired = self.displays.enroll(self.displays.pairing('Synthetic household display')['code'])
        self.display = {'Authorization': 'Display ' + self.paired['credential']}
        self.calls.clear()

    def request(self, method, url, **kwargs):
        if method == 'GET' and url.endswith('/events') and kwargs.get('params', {}).get('singleEvents') == 'true':
            self.calls.append((method, url, deepcopy(kwargs)))
            if self.interrupt:
                self.interrupt(method, url)
            return {'items': deepcopy(self.agenda_items)}
        return super().request(method, url, **kwargs)

    def post(self, endpoint, body, headers=None):
        return self.client.post('/v1/display/calendar/' + endpoint, json=body, headers=headers or self.owner)

    def invited(self, uid='single'):
        item = self.items[uid]
        item['organizer'] = {'email': 'owner@example.com', 'self': True}
        item['attendees'] = [{'email': 'retained@example.com', 'responseStatus': 'accepted'}]
        return item

    def agenda(self, headers=None):
        response = self.client.get('/v1/display/agenda?start=2026-09-22&days=7', headers=headers or self.owner)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['events']

    def source_changes(self, **changes):
        current = self.exp.store.snapshot()
        return self.exp.store.save({**current['sources'], **changes}, current['revision'])

    def test_following_review_and_main_writer_dispatch_work_for_owner_and_household(self):
        for index, headers in enumerate((self.owner, self.display)):
            with self.subTest(identity='owner' if index == 0 else 'household'):
                self.series()
                response = self.post('following', {'reference': self.reference('instance_2'), 'revision': 1}, headers)
                self.assertEqual(response.status_code, 200, response.text)
                review = response.json()
                self.assertEqual((review['prior_count'], review['remaining_count']), (2, 4))
                self.assertFalse(review['following_start_locked'])
                self.assertEqual(len(review['reference']['following_version']), 64)
                response = self.post('change', {'operation': 'edit', 'scope': 'following', 'revision': 1,
                    'reference': review['reference'], 'request_id': str(index + 1) * 32,
                    'event': {**review['editor_event'], 'start': '2026-11-05T12:00', 'end': '2026-11-05T13:00'}}, headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['status'], 'accepted')
                self.assertEqual([entry[0] for entry in self.writes()[-2:]], ['PATCH', 'POST'])
                self.assertEqual(self.writes()[-1][2]['json']['recurrence'], ['RRULE:FREQ=WEEKLY;COUNT=4'])

    def test_invitation_routes_share_actual_app_writer_and_preserve_household_access(self):
        self.assertIs(self.app.state.calendar_invitations.writer, self.writer)
        for headers in (self.owner, self.display):
            item = self.invited()
            read = self.post('invitations/read', {'reference': reference_for(item, self.entity, '2026-09-22'),
                                                'revision': 1}, headers)
            self.assertEqual(read.status_code, 200, read.text)
            review = self.post('invitations/review', {'read_id': read.json()['read_id'], 'add': ['new@example.com'],
                                                    'remove': [], 'send_updates': 'all'}, headers)
            self.assertEqual(review.status_code, 200, review.text)
            body = {key: review.json()[key] for key in ('review_id', 'review_proof', 'request_id', 'reference', 'revision')}
            confirm = self.post('invitations/confirm', {**body, 'confirmed': True}, headers)
            self.assertEqual(confirm.status_code, 200, confirm.text)
            self.assertEqual(confirm.json()['status'], 'accepted')
            self.assertEqual(self.writes()[-1][2]['params'], {'sendUpdates': 'all'})

    def test_real_guest_and_personal_middleware_deny_all_new_routes_and_following_changes(self):
        review = self.post('following', {'reference': self.reference('instance_2'), 'revision': 1}).json()
        invited = self.invited()
        bodies = {
            'following': {'reference': self.reference('instance_2'), 'revision': 1},
            'change': {'operation': 'delete', 'scope': 'following', 'reference': review['reference'],
                       'revision': 1, 'request_id': '1' * 32},
            'invitations/read': {'reference': reference_for(invited, self.entity, '2026-09-22'), 'revision': 1},
            'invitations/review': {'read_id': 'a' * 32, 'add': ['new@example.com'], 'send_updates': 'all'},
            'invitations/confirm': {'reference': reference_for(invited, self.entity, '2026-09-22'), 'revision': 1,
                                   'review_id': 'a' * 32, 'review_proof': 'b' * 64, 'request_id': 'c' * 32,
                                   'confirmed': True},
        }
        self.displays.save_profile(self.paired['id'], {'mode': 'guest', 'calendars': [self.entity]}, 0)
        for endpoint, body in bodies.items():
            response = self.post(endpoint, body, self.display)
            self.assertEqual(response.status_code, 403, (endpoint, response.text))
        member = self.app.state.members.create('Synthetic member')
        self.displays.save_profile(self.paired['id'], {'members': [member['id']]}, 1)
        self.app.state.members.login('display:' + self.paired['id'], member['id'], member['passcode'])
        for endpoint, body in bodies.items():
            response = self.post(endpoint, body, self.display)
            self.assertEqual(response.status_code, 403, (endpoint, response.text))
        self.assertEqual(self.writes(), [])

    def test_invitation_agenda_reference_preserves_occurrence_identity_without_normal_write_reference(self):
        item = self.invited('instance_2')
        self.agenda_items = [item]
        event = self.agenda()[0]
        self.assertTrue(event['recurring'])
        self.assertEqual(event['invitation_reference']['uid'], 'instance_2')
        self.assertEqual(event['invitation_reference']['recurrence_id'], 'master')
        self.assertIsNone(event['reference'])
        self.assertEqual(event['change_scopes'], {'edit': [], 'delete': []})
        read = self.post('invitations/read', {'reference': event['invitation_reference'], 'revision': 1})
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()['event']['scope'], 'occurrence')

    def test_only_eligible_managed_events_receive_invitation_reference(self):
        base = deepcopy(self.invited())
        self.agenda_items = [base]
        self.assertIsNotNone(self.agenda()[0]['invitation_reference'])
        for changed in ({'organizer': {'self': False}}, {'attendeesOmitted': True}, {'eventType': 'birthday'},
                        {'recurrence': ['RRULE:FREQ=WEEKLY;COUNT=2']}, {'locked': True}):
            with self.subTest(changed=changed):
                self.agenda_items = [{**base, **changed}]
                self.assertIsNone(self.agenda()[0]['invitation_reference'])
        self.agenda_items = [base]
        self.source_changes(managed_calendars=[])
        self.assertIsNone(self.agenda()[0]['invitation_reference'])
        self.source_changes(managed_calendars=[self.entity])
        self.google.accounts[0]['write_access'] = False
        self.assertIsNone(self.agenda()[0]['invitation_reference'])

    def test_managed_and_google_write_revocation_mid_fetch_strip_invitation_reference(self):
        self.agenda_items = [self.invited()]
        for revoke in ('managed', 'google_write', 'provider_role'):
            with self.subTest(revoke=revoke):
                self.google.accounts[0]['write_access'] = True
                self.google.accounts[0]['calendars'][0]['access_role'] = 'owner'
                self.source_changes(managed_calendars=[self.entity])

                def interrupt(method, url):
                    if method != 'GET' or not url.endswith('/events'):
                        return
                    if revoke == 'managed':
                        self.source_changes(managed_calendars=[])
                    elif revoke == 'google_write':
                        self.google.accounts[0]['write_access'] = False
                    else:
                        self.google.accounts[0]['calendars'][0]['access_role'] = 'reader'

                self.interrupt = interrupt
                event = self.agenda()[0]
                self.assertIsNone(event['invitation_reference'], revoke)
                self.interrupt = None
        self.assertEqual(self.writes(), [])

    def test_source_removal_mid_fetch_discards_entire_agenda_event(self):
        self.agenda_items = [self.invited()]
        self.interrupt = lambda method, url: self.source_changes(calendars=[], managed_calendars=[], writable_calendars=[]) if method == 'GET' and url.endswith('/events') else None
        self.assertEqual(self.agenda(), [])

    def test_guest_and_personal_agenda_never_expose_invitation_controls(self):
        self.agenda_items = [self.invited()]
        self.displays.save_profile(self.paired['id'], {'mode': 'guest', 'calendars': [self.entity]}, 0)
        self.assertIsNone(self.agenda(self.display)[0]['invitation_reference'])
        member = self.app.state.members.create('Synthetic member')
        self.app.state.members.change(member['id'], 0, profile={'mode': 'guest', 'calendars': [self.entity]})
        self.displays.save_profile(self.paired['id'], {'members': [member['id']]}, 1)
        self.app.state.members.login('display:' + self.paired['id'], member['id'], member['passcode'])
        self.assertIsNone(self.agenda(self.display)[0]['invitation_reference'])

    def test_mid_review_session_revocation_discards_following_and_invitation_response(self):
        item = self.invited()
        bodies = {
            'following': {'reference': self.reference('instance_2'), 'revision': 1},
            'invitations/read': {'reference': reference_for(item, self.entity, '2026-09-22'), 'revision': 1},
        }
        for endpoint, body in bodies.items():
            pair = self.displays.enroll(self.displays.pairing('Synthetic revocable display')['code'])
            self.interrupt = lambda method, url: self.displays.revoke(pair['id']) if '/calendarList/' in url else None
            response = self.post(endpoint, body, {'Authorization': 'Display ' + pair['credential']})
            self.assertEqual(response.status_code, 401, response.text)
            self.assertNotIn('Weekly studio', response.text)
            self.assertNotIn('retained@example.com', response.text)
        self.assertEqual(self.writes(), [])

    def test_legacy_single_event_receipt_digest_survives_optional_following_version(self):
        reference = self.reference()
        # Reconstruct exactly the committed Wave 1 reference, including its null
        # recurrence_id but without the new optional following_version field.
        legacy_reference = {**reference, 'recurrence_id': None}
        for index, operation in enumerate(('edit', 'delete')):
            event = CalendarEvent.model_validate(self.event).model_dump() if operation == 'edit' else None
            request_id = str(index + 1) * 32
            intent = {'provider': 'google', 'operation': operation, 'reference': legacy_reference,
                      'event': event, 'scope': 'single'}
            digest = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
            key = hashlib.sha256(request_id.encode()).hexdigest()
            self.writer.commit({**self.writer.receipts, key: {'digest': digest, 'status': 'accepted'}})
            for current_reference in (reference, {**reference, 'following_version': None}):
                response = self.post('change', {'operation': operation, 'reference': current_reference,
                                               'event': event, 'scope': 'single', 'revision': 1,
                                               'request_id': request_id})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['status'], 'accepted')
        self.assertEqual(self.writes(), [])
        response = self.post('change', {'operation': 'delete', 'reference': {**reference, 'following_version': 'a' * 64},
                                       'scope': 'single', 'revision': 1, 'request_id': '3' * 32})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.writes(), [])


if __name__ == '__main__':
    unittest.main()
