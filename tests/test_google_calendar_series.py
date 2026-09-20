"""Synthetic finite-series review, rescheduling, deletion and recovery checks."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
from threading import Event, RLock, Thread
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.calendar_events import CalendarWriter
from backend.experiences import ExperienceConflict, ExperienceUnavailable
from backend.google_calendar import GoogleRejected
from backend.google_calendar_series import change_following, review_following
from backend.google_calendar_write import GoogleCalendarWriter
from backend.home import HomeUnavailable
from tests.test_google_calendar_write import WriteFixture


class SeriesFixture(WriteFixture):
    def setUp(self):
        self.instances = []
        self.page_size = 366
        self.page_loop = False
        self.stored_exceptions = []
        self.exception_page = False
        self.write_failures = {}
        self.write_index = 0
        self.after_write = None
        super().setUp()
        self.series()
        self.adapter = GoogleCalendarWriter(self.writer)

    def series(self, dates=None, all_day=False, rule='RRULE:FREQ=WEEKLY;COUNT=6'):
        if dates is None:
            dates = ['2026-10-20T10:00', '2026-10-27T10:00', '2026-11-03T10:00',
                     '2026-11-10T10:00', '2026-11-17T10:00', '2026-11-24T10:00']
        zone = ZoneInfo('America/New_York')

        def bounds(value):
            start = datetime.fromisoformat(value).replace(tzinfo=zone)
            end = start + timedelta(days=1) if all_day else start + timedelta(hours=1)
            if all_day:
                return {'date': start.date().isoformat()}, {'date': end.date().isoformat()}
            return ({'dateTime': start.isoformat(), 'timeZone': zone.key},
                    {'dateTime': end.isoformat(), 'timeZone': zone.key})

        start, end = bounds(dates[0])
        master = {'id': 'master', 'etag': '"master-v1"', 'iCalUID': 'synthetic-series@example.com', 'summary': 'Weekly studio',
                  'description': 'Keep series notes', 'location': 'Studio',
                  'recurrence': [rule], 'start': start, 'end': end,
                  'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 15}]},
                  'colorId': '4', 'transparency': 'transparent', 'visibility': 'private'}
        self.items['master'] = master
        self.instances = []
        for index, value in enumerate(dates):
            start, end = bounds(value)
            instance = {**deepcopy(master), 'id': 'instance_' + str(index), 'etag': '"instance-' + str(index) + '"',
                        'recurringEventId': 'master', 'originalStartTime': deepcopy(start),
                        'start': start, 'end': end}
            instance.pop('recurrence')
            self.instances.append(instance)
            self.items[instance['id']] = instance

    def request(self, method, url, **kwargs):
        if method == 'GET' and url.endswith('/events') and kwargs.get('params', {}).get('singleEvents') == 'false':
            self.calls.append((method, url, deepcopy(kwargs)))
            if self.interrupt:
                self.interrupt(method, url)
            if self.exception_page:
                if kwargs['params'].get('pageToken'):
                    return {'items': deepcopy(self.stored_exceptions)}
                return {'items': [deepcopy(self.items['master'])], 'nextPageToken': 'exceptions'}
            return {'items': [deepcopy(self.items['master']), *deepcopy(self.stored_exceptions)]}
        if method == 'GET' and url.endswith('/instances'):
            self.calls.append((method, url, deepcopy(kwargs)))
            if self.interrupt:
                self.interrupt(method, url)
            offset = int(kwargs.get('params', {}).get('pageToken', '0'))
            rows = self.instances[offset:offset + self.page_size]
            result = {'items': deepcopy(rows)}
            if self.page_loop:
                result['nextPageToken'] = '0'
            elif offset + self.page_size < len(self.instances):
                result['nextPageToken'] = str(offset + self.page_size)
            return result
        if method in {'POST', 'PATCH', 'DELETE'} and not url.endswith('/token'):
            self.calls.append((method, url, deepcopy(kwargs)))
            if self.interrupt:
                self.interrupt(method, url)
            self.write_index += 1
            failure = self.write_failures.get(self.write_index)
            if failure == 'reject':
                raise GoogleRejected('Synthetic rejection')
            if failure == 'lost':
                raise HomeUnavailable('Synthetic response loss')
            payload = kwargs.get('json', {})
            uid = payload.get('id') or url.rsplit('/', 1)[1]
            current = self.items.get(uid, {})
            etag = kwargs['headers'].get('If-Match')
            if etag and etag != current.get('etag'):
                raise GoogleRejected('Synthetic ETag conflict')
            if method == 'DELETE':
                self.items.pop(uid, None)
                result = {}
            else:
                result = {**deepcopy(current), **deepcopy(payload), 'id': uid, 'etag': '"accepted-v2"'}
                self.items[uid] = deepcopy(result)
            if self.after_write:
                self.after_write(self.write_index)
            if failure == 'lost_after':
                raise HomeUnavailable('Synthetic response lost after mutation')
            if failure == 'malformed':
                return {}
            if failure == 'wrong_count':
                result['recurrence'] = ['RRULE:FREQ=WEEKLY;COUNT=99']
            return result
        return super().request(method, url, **kwargs)

    def review(self, index=2):
        return review_following(self.adapter, self.reference('instance_' + str(index)), 1)

    def change(self, review, operation='edit', event=None, request_id='1' * 32, adapter=None):
        replacement = event if event is not None else review['editor_event'] if operation == 'edit' else None
        return change_following(adapter or self.adapter, operation, review['reference'], replacement, 1, request_id)


class GoogleSeriesTests(SeriesFixture, unittest.TestCase):
    def test_review_paginates_provider_originals_and_reorders_without_guessing_dates(self):
        self.page_size = 2
        self.instances.reverse()
        review = self.review()
        self.assertEqual(review['editor_event']['start'], '2026-11-03T10:00')
        self.assertEqual((review['prior_count'], review['remaining_count']), (2, 4))
        self.assertFalse(review['following_start_locked'])
        self.assertEqual(len(review['reference']['following_version']), 64)
        calls = [call for call in self.calls if call[1].endswith('/instances')]
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call[2]['params']['showDeleted'] == 'true' for call in calls))
        self.assertTrue(all('timeMin' not in call[2]['params'] and 'timeMax' not in call[2]['params'] for call in calls))
        self.assertEqual(self.writes(), [])

    def test_moving_following_start_across_dst_retains_prior_dates_remaining_count_and_metadata(self):
        before = deepcopy(self.items['master'])
        review = self.review(1)
        event = {**review['editor_event'], 'start': '2026-11-04T12:00', 'end': '2026-11-04T13:00'}
        result = self.change(review, event=event)
        self.assertEqual(result['status'], 'accepted')
        writes = self.writes()
        self.assertEqual([row[0] for row in writes], ['PATCH', 'POST'])
        trim, insert = writes[0][2], writes[1][2]
        self.assertEqual(trim['json'], {'recurrence': ['RRULE:FREQ=WEEKLY;COUNT=1']})
        self.assertEqual(trim['headers']['If-Match'], before['etag'])
        self.assertEqual(self.items['master']['start'], before['start'])
        self.assertEqual(self.items['master']['end'], before['end'])
        self.assertEqual(insert['json']['recurrence'], ['RRULE:FREQ=WEEKLY;COUNT=5'])
        self.assertEqual(insert['json']['start']['dateTime'], '2026-11-04T12:00:00-05:00')
        self.assertEqual(insert['json']['start']['timeZone'], 'America/New_York')
        for field in ('reminders', 'colorId', 'visibility', 'transparency'):
            self.assertEqual(insert['json'][field], before[field])
        self.assertNotIn('attendees', insert['json'])
        self.assertNotIn('If-Match', insert['headers'])
        self.assertEqual(insert['json']['id'], 'echo' + hashlib.sha256(('following:' + '1' * 32).encode()).hexdigest())
        self.assertTrue(all(row[2]['params'] == {'sendUpdates': 'none'} for row in writes))

    def test_month_end_provider_enumeration_preserves_remaining_count(self):
        self.series(['2026-01-31T10:00', '2026-03-31T10:00', '2026-05-31T10:00', '2026-07-31T10:00'],
                    rule='RRULE:COUNT=4;FREQ=MONTHLY;INTERVAL=1')
        review = self.review(1)
        self.assertEqual(review['remaining_count'], 3)
        event = {**review['editor_event'], 'start': '2026-04-30T11:00', 'end': '2026-04-30T12:00'}
        self.assertEqual(self.change(review, event=event)['status'], 'accepted')
        self.assertEqual(self.writes()[0][2]['json']['recurrence'], ['RRULE:COUNT=1;FREQ=MONTHLY;INTERVAL=1'])
        self.assertEqual(self.writes()[1][2]['json']['recurrence'], ['RRULE:COUNT=3;FREQ=MONTHLY;INTERVAL=1'])

    def test_all_day_reschedule_and_last_occurrence_count_one(self):
        self.series(['2026-09-20', '2026-09-21', '2026-09-22'], all_day=True, rule='RRULE:FREQ=DAILY;COUNT=3')
        review = self.review(2)
        event = {**review['editor_event'], 'start': '2026-09-25', 'end': '2026-09-26'}
        self.assertEqual(self.change(review, event=event)['status'], 'accepted')
        payload = self.writes()[1][2]['json']
        self.assertEqual(payload['start'], {'date': '2026-09-25'})
        self.assertEqual(payload['recurrence'], ['RRULE:FREQ=DAILY;COUNT=1'])
        self.assertEqual(self.items['master']['start'], {'date': '2026-09-20'})

    def test_dst_fold_is_preserved_and_nonexistent_replacement_time_is_rejected(self):
        review = self.review()
        nonexistent = {**review['editor_event'], 'start': '2027-03-14T02:30', 'end': '2027-03-14T03:30'}
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            self.change(review, event=nonexistent)
        self.assertEqual(self.writes(), [])
        folded = {**review['editor_event'], 'start': '2026-11-01T01:30', 'end': '2026-11-01T02:30',
                  'start_fold': 1, 'end_fold': 1}
        self.assertEqual(self.change(review, event=folded)['status'], 'accepted')
        self.assertEqual(self.writes()[1][2]['json']['start']['dateTime'], '2026-11-01T01:30:00-05:00')

    def test_first_occurrence_edit_is_one_conditional_patch_preserving_count(self):
        review = self.review(0)
        event = {**review['editor_event'], 'start': '2026-10-21T12:00', 'end': '2026-10-21T13:00'}
        self.assertEqual(self.change(review, event=event)['status'], 'accepted')
        self.assertEqual(len(self.writes()), 1)
        self.assertNotIn('recurrence', self.writes()[0][2]['json'])
        self.assertEqual(self.items['master']['recurrence'], ['RRULE:FREQ=WEEKLY;COUNT=6'])

    def test_following_delete_trims_count_without_insert_and_first_delete_removes_master(self):
        review = self.review(2)
        self.assertEqual(self.change(review, operation='delete')['status'], 'accepted')
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.writes()[0][2]['json'], {'recurrence': ['RRULE:FREQ=WEEKLY;COUNT=2']})
        self.series()
        review = self.review(0)
        self.assertEqual(self.change(review, operation='delete', request_id='2' * 32)['status'], 'accepted')
        self.assertEqual(self.writes()[-1][0], 'DELETE')
        self.assertEqual(self.writes()[-1][2]['headers']['If-Match'], '"master-v1"')

    def test_cancelled_moved_changed_and_duration_exceptions_are_refused_before_writes(self):
        for mutation in (
            {'status': 'cancelled'}, {'summary': 'Changed occurrence'},
            {'start': {'dateTime': '2026-11-04T10:00:00-05:00', 'timeZone': 'America/New_York'}},
            {'end': {'dateTime': '2026-11-03T12:00:00-05:00', 'timeZone': 'America/New_York'}},
            {'reminders': {'useDefault': True}}, {'colorId': '7'},
        ):
            with self.subTest(mutation=mutation):
                self.series()
                self.instances[2].update(deepcopy(mutation))
                with self.assertRaises(ValueError):
                    self.review(1)
        self.assertEqual(self.writes(), [])

    def test_exception_outside_selected_interval_is_still_checked(self):
        self.instances[0]['summary'] = 'Earlier customized occurrence'
        with self.assertRaisesRegex(ValueError, 'exceptions'):
            self.review(4)
        self.assertEqual(self.writes(), [])

    def test_identical_visible_fields_do_not_hide_stored_exception_in_later_page(self):
        self.stored_exceptions = [deepcopy(self.instances[0])]
        self.exception_page = True
        with self.assertRaisesRegex(ValueError, 'stored exceptions'):
            self.review(4)
        calls = [call for call in self.calls if call[2].get('params', {}).get('singleEvents') == 'false']
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][2]['params']['iCalUID'], 'synthetic-series@example.com')
        self.assertEqual(calls[0][2]['params']['showDeleted'], 'true')
        self.assertEqual(self.writes(), [])

    def test_stored_exception_created_after_review_invalidates_change(self):
        review = self.review()
        self.stored_exceptions = [deepcopy(self.instances[5])]
        with self.assertRaisesRegex(ValueError, 'stored exceptions'):
            self.change(review)
        self.assertEqual(self.writes(), [])

    def test_incomplete_duplicate_looped_and_unsupported_series_deny(self):
        for rule in ('RRULE:FREQ=WEEKLY;COUNT=367', 'RRULE:FREQ=WEEKLY;UNTIL=20261201T100000Z',
                     'RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=6', 'RRULE:FREQ=WEEKLY;COUNT=6;COUNT=6',
                     'RRULE:FREQ=HOURLY;COUNT=6'):
            with self.subTest(rule=rule):
                self.series(rule=rule)
                with self.assertRaises(ValueError):
                    self.review()
        self.series()
        self.items['master']['recurrence'].append('EXDATE:20261027T140000Z')
        with self.assertRaises(ValueError):
            self.review()
        self.series()
        self.instances.pop()
        with self.assertRaisesRegex(ValueError, 'complete provider'):
            self.review()
        self.series()
        self.instances[-1] = deepcopy(self.instances[0])
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.review()
        self.series()
        self.page_loop = True
        with self.assertRaises((ValueError, HomeUnavailable)):
            self.review()
        self.assertEqual(self.writes(), [])

    def test_guest_special_and_unknown_properties_cannot_be_silently_lost(self):
        for fields in ({'attendees': [{'email': 'synthetic@example.com'}]}, {'attendeesOmitted': True},
                       {'eventType': 'birthday'}, {'attachments': [{'fileUrl': 'https://example.com/file'}]},
                       {'conferenceData': {'conferenceId': 'synthetic'}}, {'extendedProperties': {'private': {'key': 'value'}}}):
            with self.subTest(fields=fields):
                self.series()
                self.items['master'].update(fields)
                with self.assertRaises(ValueError):
                    self.review()
        self.assertEqual(self.writes(), [])

    def test_review_proof_selected_master_and_nonselected_versions_all_rechecked(self):
        for target in ('master', 'instance_2', 'instance_5'):
            with self.subTest(target=target):
                self.series()
                review = self.review()
                self.items[target]['etag'] = '"changed"'
                with self.assertRaises(ExperienceConflict):
                    self.change(review)
        self.series()
        review = self.review()
        review['reference'].pop('following_version')
        with self.assertRaisesRegex(ValueError, 'Load and review'):
            self.change(review)
        self.assertEqual(self.writes(), [])

    def test_master_change_during_pagination_prevents_review(self):
        self.interrupt = lambda method, url: self.items['master'].update(etag='"changed"') if url.endswith('/instances') else None
        with self.assertRaises(ExperienceConflict):
            self.review()
        self.assertEqual(self.writes(), [])

    def test_split_needs_separate_creation_grant_before_any_trim(self):
        review = self.review()
        self.exp.store.save({'calendars': [self.entity], 'managed_calendars': [self.entity]}, 1)
        with self.assertRaises(PermissionError):
            change_following(self.adapter, 'edit', review['reference'], review['editor_event'], 2, '1' * 32)
        self.assertEqual(self.writes(), [])
        # A following deletion creates no new event and still uses the management grant.
        review = review_following(self.adapter, self.reference('instance_2'), 2)
        result = change_following(self.adapter, 'delete', review['reference'], None, 2, '2' * 32)
        self.assertEqual(result['status'], 'accepted')

    def test_all_day_timezone_and_new_recurrence_cannot_change(self):
        review = self.review()
        for event in ({**review['editor_event'], 'timezone': 'UTC'},
                      {**review['editor_event'], 'all_day': True, 'start': '2026-11-04', 'end': '2026-11-05'},
                      {**review['editor_event'], 'recurrence': {'frequency': 'daily', 'count': 3}}):
            with self.assertRaises(ValueError):
                self.change(review, event=event)
        self.assertEqual(self.writes(), [])

    def test_first_rejection_or_timeout_never_sends_insert_or_retries_after_restart(self):
        for failure, status in (('reject', 'rejected'), ('lost', 'unconfirmed'), ('lost_after', 'unconfirmed'),
                                ('malformed', 'unconfirmed'), ('wrong_count', 'unconfirmed')):
            with self.subTest(failure=failure):
                self.series()
                self.writer.commit({})
                self.calls.clear()
                self.write_index = 0
                self.write_failures = {1: failure}
                review = self.review()
                result = self.change(review)
                self.assertEqual(result['status'], status)
                loaded = CalendarWriter(self.exp, self.root, self.protector)
                self.assertEqual(self.change(review, adapter=GoogleCalendarWriter(loaded)), result)
                self.assertEqual(len(self.writes()), 1)

    def test_insert_rejection_and_timeout_are_honest_partial_results_without_restart_resumption(self):
        for failure, step in (('reject', 'insert_rejected'), ('lost', 'insert_unconfirmed'), ('lost_after', 'insert_unconfirmed')):
            with self.subTest(failure=failure):
                self.series()
                self.writer.commit({})
                self.calls.clear()
                self.write_index = 0
                self.write_failures = {2: failure}
                review = self.review()
                result = self.change(review)
                self.assertEqual((result['status'], result['series_step']), ('unconfirmed', step))
                self.assertIn('original series was shortened', result['text'])
                if failure == 'reject':
                    self.assertIn('not created', result['text'])
                loaded = CalendarWriter(self.exp, self.root, self.protector)
                self.assertFalse(loaded.error)
                self.assertEqual(self.change(review, adapter=GoogleCalendarWriter(loaded)), result)
                self.assertEqual(len(self.writes()), 2)

    def test_crash_at_each_receipt_checkpoint_never_resumes_writes(self):
        for stage, expected_writes in (('trim_pending', 0), ('trim_accepted', 1), ('insert_pending', 1)):
            with self.subTest(stage=stage):
                self.series()
                self.writer.commit({})
                self.calls.clear()
                self.write_index = 0
                review = self.review()
                commit = self.writer.commit

                def crash(receipts):
                    commit(receipts)
                    if any(row.get('series_step') == stage for row in receipts.values()):
                        raise RuntimeError('Synthetic process crash after durable checkpoint')

                with patch.object(self.writer, 'commit', side_effect=crash):
                    with self.assertRaises(RuntimeError):
                        self.change(review)
                loaded = CalendarWriter(self.exp, self.root, self.protector)
                result = self.change(review, adapter=GoogleCalendarWriter(loaded))
                self.assertEqual((result['status'], result['series_step']), ('unconfirmed', stage))
                self.assertEqual(len(self.writes()), expected_writes)

    def test_receipt_commit_failure_after_trim_leaves_durable_unknown_and_stops_insert(self):
        review = self.review()
        commit = self.writer.commit

        def fail(receipts):
            if any(row.get('series_step') == 'trim_accepted' for row in receipts.values()):
                raise ExperienceUnavailable('Synthetic receipt storage failure')
            commit(receipts)

        with patch.object(self.writer, 'commit', side_effect=fail):
            with self.assertRaises(ExperienceUnavailable):
                self.change(review)
        loaded = CalendarWriter(self.exp, self.root, self.protector)
        result = self.change(review, adapter=GoogleCalendarWriter(loaded))
        self.assertEqual(result['series_step'], 'trim_pending')
        self.assertEqual(len(self.writes()), 1)

    def test_access_revocation_between_steps_records_partial_and_does_not_insert(self):
        review = self.review()
        allowed = [True]

        def validate():
            if not allowed[0]:
                raise PermissionError('Synthetic session revocation')

        self.adapter = GoogleCalendarWriter(self.writer, validate)
        self.after_write = lambda _: allowed.__setitem__(0, False)
        with self.assertRaisesRegex(ExperienceUnavailable, 'same request identifier'):
            self.change(review)
        self.assertEqual(len(self.writes()), 1)
        result = self.change(review, adapter=GoogleCalendarWriter(self.writer))
        self.assertEqual(result['series_step'], 'insert_blocked')
        self.assertIn('not created', result['text'])
        self.assertEqual(len(self.writes()), 1)

    def test_parallel_and_changed_intent_retries_do_not_duplicate_split(self):
        review = self.review()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.change(review), range(2)))
        self.assertEqual([item['status'] for item in results], ['accepted', 'accepted'])
        self.assertEqual(len(self.writes()), 2)
        with self.assertRaises(ExperienceConflict):
            self.change(review, event={**review['editor_event'], 'title': 'Different review'})
        self.assertEqual(len(self.writes()), 2)

    def test_receipts_contain_only_digests_status_steps_and_counts_and_are_encrypted(self):
        review = self.review()
        self.change(review)
        receipt = next(iter(self.writer.receipts.values()))
        self.assertEqual(set(receipt), {'digest', 'status', 'series_step', 'prior_count', 'remaining_count'})
        raw = self.writer.path.read_bytes()
        for content in (b'Weekly studio', b'synthetic/calendar@example.com', b'Keep series notes', b'2026-11-03', b'instance_2'):
            self.assertNotIn(content, raw)

    def test_review_and_change_acquire_access_lock_before_source_lock(self):
        review = self.review()
        for operation in ('review', 'change'):
            member_lock = RLock()
            attempted, finished = Event(), Event()
            results = []

            class AccessLock:
                def __enter__(self):
                    attempted.set()
                    member_lock.acquire()

                def __exit__(self, *args):
                    member_lock.release()

            adapter = GoogleCalendarWriter(self.writer, access_lock=AccessLock())

            def run():
                try:
                    results.append(review_following(adapter, self.reference('instance_2'), 1) if operation == 'review' else self.change(review, adapter=adapter))
                except Exception as error:
                    results.append(error)
                finally:
                    finished.set()

            with member_lock:
                worker = Thread(target=run, daemon=True)
                worker.start()
                self.assertTrue(attempted.wait(2))
                acquired = self.exp.store.lock.acquire(timeout=2)
                try:
                    self.assertTrue(acquired, 'Following review inverted member/source locks')
                finally:
                    if acquired:
                        self.exp.store.lock.release()
            self.assertTrue(finished.wait(3))
            worker.join(1)
            self.assertIsInstance(results[0], dict)


if __name__ == '__main__':
    unittest.main()
