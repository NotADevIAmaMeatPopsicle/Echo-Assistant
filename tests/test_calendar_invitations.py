"""Invitation payload/consent checks using only the synthetic Google transport."""
from copy import deepcopy
import hashlib
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.calendar_events import CalendarWriter
from backend.calendar_invitations import (CalendarInvitations, ConfirmInvitations, ReadInvitations,
    ReviewInvitations, MAX_PENDING, invitation_event, reference_for, install)
from backend.experiences import ExperienceConflict, ExperienceUnavailable
from backend.google_calendar_write import editable_event
from backend.members import PersonalPrincipal
from tests.test_google_calendar_write import WriteFixture


class InvitationFixture(WriteFixture):
    def setUp(self):
        super().setUp()
        self.now = 1000
        self.service = CalendarInvitations(self.writer, clock=lambda: self.now)
        self.item = self.items['single']
        self.item['organizer'] = {'email': 'owner@example.com', 'self': True}
        self.item['attendees'] = [
            {'email': 'owner@example.com', 'organizer': True, 'self': True, 'responseStatus': 'accepted'},
            {'email': 'keep@example.com', 'displayName': 'Keep this guest', 'responseStatus': 'tentative',
             'comment': 'Preserve my note', 'optional': True, 'additionalGuests': 2, 'id': 'provider-guest-id'},
            {'email': 'remove@example.com', 'resource': True, 'responseStatus': 'accepted'}]
        self.binding = 'a' * 64

    def ref(self):
        return reference_for(self.item, self.entity, '2026-09-22')

    def read(self, **kwargs):
        return self.service.read({'reference': self.ref(), 'revision': 1}, self.binding, **kwargs)

    def reviewed(self, mode='all', **kwargs):
        read = self.read()
        return self.service.review({'read_id': read['read_id'], 'add': ['new@example.com'],
            'remove': ['remove@example.com'], 'send_updates': mode}, self.binding, **kwargs)

    @staticmethod
    def confirmation(review):
        return {**{k: review[k] for k in ('review_id', 'review_proof', 'request_id', 'reference', 'revision')}, 'confirmed': True}


class CalendarInvitationTests(InvitationFixture, unittest.TestCase):
    def test_reads_and_reviews_never_send_and_preserve_provider_metadata(self):
        review = self.reviewed()
        self.assertEqual(self.writes(), [])
        self.assertEqual(review['added'], ['new@example.com'])
        self.assertEqual(review['removed'], ['remove@example.com'])
        self.assertEqual(review['affected_guests'], ['owner@example.com', 'keep@example.com', 'remove@example.com', 'new@example.com'])
        result = self.service.confirm(self.confirmation(review), self.binding)
        self.assertEqual(result['status'], 'accepted')
        method, _, options = self.writes()[0]
        self.assertEqual(method, 'PATCH')
        self.assertEqual(set(options['json']), {'attendees'})
        self.assertEqual(options['json']['attendees'], self.item['attendees'][:2] + [{'email': 'new@example.com'}])
        self.assertEqual(options['headers']['If-Match'], '"single-v1"')
        self.assertEqual(options['params'], {'sendUpdates': 'all'})
        self.assertNotIn(b'keep@example.com', self.writer.path.read_bytes())
        self.assertFalse(editable_event(self.item))

    def test_supported_notification_modes_are_deliberate_and_disclosed(self):
        for mode in ('all', 'externalOnly', 'none'):
            with self.subTest(mode=mode):
                review = self.reviewed(mode)
                self.assertTrue(review['notification_effect'])
                self.service.confirm(self.confirmation(review), self.binding)
                self.assertEqual(self.writes()[-1][2]['params']['sendUpdates'], mode)
        with self.assertRaises(ValidationError):
            ReviewInvitations.model_validate({'read_id': 'a' * 32})
        with self.assertRaises(ValidationError):
            ReviewInvitations.model_validate({'read_id': 'a' * 32, 'send_updates': 'selected'})
        self.assertIn('some emails may still be sent', self.reviewed('none')['notification_effect'])

    def test_proof_identity_and_exact_review_are_required(self):
        body = self.confirmation(self.reviewed())
        for changed in ({'review_proof': '0' * 64}, {'request_id': '0' * 32}, {'revision': 0}):
            with self.assertRaises(ExperienceConflict):
                self.service.confirm({**body, **changed}, self.binding)
        with self.assertRaises(ExperienceConflict):
            self.service.confirm(body, 'b' * 64)
        for value in (False, 1, 'true'):
            with self.assertRaises(ValidationError):
                ConfirmInvitations.model_validate({**body, 'confirmed': value})
        self.assertEqual(self.writes(), [])

    def test_re_review_invalidates_prior_proof_and_cannot_silently_drop_guests(self):
        read = self.read()
        changes = {'read_id': read['read_id'], 'add': ['new@example.com'], 'send_updates': 'all'}
        old = self.service.review(changes, self.binding)
        latest = self.service.review({**changes, 'add': ['different@example.com']}, self.binding)
        with self.assertRaises(ExperienceConflict):
            self.service.confirm(self.confirmation(old), self.binding)
        self.service.confirm(self.confirmation(latest), self.binding)
        self.assertEqual(self.writes()[0][2]['json']['attendees'][:-1], self.item['attendees'])

    def test_unknown_duplicate_and_protected_removals_are_rejected(self):
        read = self.read()
        for changes in ({}, {'remove': ['unknown@example.com']}, {'remove': ['owner@example.com']},
                        {'add': ['KEEP@example.com']}, {'add': ['new@example.com', 'NEW@example.com']},
                        {'add': ['remove@example.com'], 'remove': ['remove@example.com']}, {'add': ['bad email']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.service.review({'read_id': read['read_id'], 'send_updates': 'all', **changes}, self.binding)
        self.assertEqual(self.writes(), [])

    def test_omitted_special_master_and_unowned_events_are_not_invitable(self):
        for changes in ({'attendeesOmitted': True}, {'locked': True}, {'eventType': 'birthday'},
                        {'organizer': None}, {'organizer': {}}, {'organizer': {'self': False}},
                        {'attendees': [{'displayName': 'No email'}]}, {'attendees': self.item['attendees'] * 100},
                        {'recurrence': ['RRULE:FREQ=DAILY;COUNT=3']}):
            with self.subTest(changes=changes):
                self.assertFalse(invitation_event({**self.item, **changes}))
        self.item['recurringEventId'] = 'master'
        review = self.reviewed()
        self.assertEqual(review['event']['scope'], 'occurrence')
        self.assertEqual(review['reference']['recurrence_id'], 'master')

    def test_etag_changes_require_fresh_agenda_and_provider_412_is_final(self):
        read = self.read();self.item['etag'] = '"changed"'
        with self.assertRaises(ExperienceConflict):
            self.service.review({'read_id': read['read_id'], 'add': ['new@example.com'], 'send_updates': 'all'}, self.binding)
        body = self.confirmation(self.reviewed());self.item['etag'] = '"changed-again"'
        with self.assertRaises(ExperienceConflict):
            self.service.confirm(body, self.binding)
        self.assertEqual(self.writes(), [])
        body = self.confirmation(self.reviewed());self.failure = 'etag'
        for _ in range(2):
            self.assertEqual(self.service.confirm(body, self.binding)['status'], 'rejected')
        self.assertEqual(len(self.writes()), 1)

    def test_uncertain_response_and_restart_never_dispatch_again(self):
        for failure in ('lost', 'malformed'):
            body = self.confirmation(self.reviewed());self.failure = failure
            self.assertEqual(self.service.confirm(body, self.binding)['status'], 'unconfirmed')
            loaded = CalendarWriter(self.exp, self.root, self.protector)
            fresh = CalendarInvitations(loaded)
            self.assertEqual(fresh.confirm(body, self.binding)['status'], 'unconfirmed')
            self.service = fresh;self.writer = loaded
        self.assertEqual(len(self.writes()), 2)

    def test_pending_receipt_covers_result_persistence_failure(self):
        body = self.confirmation(self.reviewed());original = self.writer.commit
        def commit(receipts):
            if any(r['status'] != 'pending' for r in receipts.values()):
                raise ExperienceUnavailable('Synthetic result storage failure')
            original(receipts)
        with patch.object(self.writer, 'commit', side_effect=commit):
            with self.assertRaises(ExperienceUnavailable):
                self.service.confirm(body, self.binding)
        self.assertEqual(self.service.confirm(body, self.binding)['status'], 'unconfirmed')
        self.assertEqual(len(self.writes()), 1)

    def test_expiry_capacity_and_access_change_discard_drafts(self):
        body = self.confirmation(self.reviewed());self.now += 301
        with self.assertRaises(ExperienceConflict):
            self.service.confirm(body, self.binding)
        self.service.prune();self.assertEqual(self.service.reads, {});self.assertEqual(self.service.reviews, {})
        def denied():
            raise HTTPException(401, 'Synthetic revoked access')
        with self.assertRaises(HTTPException):
            self.read(validate=denied)
        for _ in range(MAX_PENDING):
            self.read()
        with self.assertRaises(ExperienceUnavailable):
            self.read()
        self.assertEqual(self.writes(), [])

    def test_policy_changes_and_revocation_during_read_or_dispatch(self):
        count = 0
        def validate():
            nonlocal count
            count += 1
            if count > 1:
                raise HTTPException(401, 'Synthetic revoked access')
        with self.assertRaises(HTTPException):
            self.read(validate=validate)
        self.assertEqual(self.service.reads, {})
        body = self.confirmation(self.reviewed())
        self.writer.enabled = False
        with self.assertRaises(PermissionError):
            self.service.confirm(body, self.binding)
        self.writer.enabled = True
        def during_dispatch():
            if self.writes():
                raise HTTPException(401, 'Synthetic revoked access')
        with self.assertRaises(ExperienceUnavailable):
            self.service.confirm(body, self.binding, validate=during_dispatch)
        self.assertEqual(self.service.confirm(body, self.binding)['status'], 'accepted')
        self.assertEqual(len(self.writes()), 1)


class CalendarInvitationRouteTests(InvitationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.profile = {'profile': {'mode': 'household'}, 'profile_revision': 0}
        self.principal = 'display:' + 'd' * 32
        self.displays = SimpleNamespace(profile_for=lambda _: deepcopy(self.profile), members=None, lock=RLock())
        self.app = FastAPI()
        def authorize(request: Request):
            return self.principal
        install(self.app, self.writer, authorize, self.displays)
        self.client = TestClient(self.app)

    def post(self, endpoint, body):
        return self.client.post('/v1/display/calendar/invitations/' + endpoint, json=body)

    def test_household_flow_and_same_endpoint_binding(self):
        read = self.post('read', {'reference': self.ref(), 'revision': 1})
        self.assertEqual(read.status_code, 200, read.text)
        review = self.post('review', {'read_id': read.json()['read_id'], 'add': ['new@example.com'], 'send_updates': 'all'})
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(self.writes(), [])
        body = self.confirmation(review.json());self.principal = 'device'
        self.assertEqual(self.post('confirm', body).status_code, 409)
        self.principal = 'display:' + 'd' * 32
        self.assertEqual(self.post('confirm', body).json()['status'], 'accepted')

    def test_guest_personal_round_and_profile_revision_changes_are_denied(self):
        body = {'reference': self.ref(), 'revision': 1}
        for principal, profile in [('device', {'mode': 'guest'}), ('round', {'mode': 'household'}),
                (PersonalPrincipal('device', 'b' * 32, 'c' * 32), {'mode': 'household'})]:
            self.principal = principal;self.profile['profile'] = profile
            self.assertEqual(self.post('read', body).status_code, 403)
        self.principal = 'device';self.profile['profile'] = {'mode': 'household'}
        read = self.post('read', body).json();self.profile['profile_revision'] = 1
        result = self.post('review', {'read_id': read['read_id'], 'add': ['new@example.com'], 'send_updates': 'all'})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.writes(), [])


if __name__ == '__main__':
    unittest.main()
