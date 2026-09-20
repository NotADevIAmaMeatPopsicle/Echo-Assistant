"""Owner video selection and display isolation; no network, browser or media."""
import base64
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.display_auth import Displays
from backend.experiences import ExperienceConflict
from backend.linux_protection import LinuxProtector
from backend.members import PersonalPrincipal
from backend.video_provider import MAX_FILE_BYTES, VideoProvider, VideoSettings, VideoStore, VideoUnavailable, install


class VideoFixture:
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        key = self.root / 'key'
        key.write_bytes(os.urandom(32))
        key.chmod(0o600)
        self.protector = LinuxProtector(key)
        self.displays = Displays(None, self.protector)
        self.first = self.displays.enroll(self.displays.pairing('Synthetic selected display')['code'])
        self.second = self.displays.enroll(self.displays.pairing('Synthetic unselected display')['code'])
        self.store = VideoStore(self.root, self.protector)
        self.service = VideoProvider(self.store, self.displays)
        self.settings = {'revision': 0, 'enabled': True, 'video_id': 'Abcdef_12-3',
                         'allowed_display_ids': [self.first['id']]}


class VideoProviderTests(VideoFixture, unittest.TestCase):
    def test_disabled_defaults_expose_no_selection(self):
        self.assertEqual(self.service.settings(), {'provider': 'youtube', 'revision': 0, 'enabled': False,
                                                  'video_id': '', 'allowed_display_ids': []})
        owner = self.service.snapshot('owner')
        self.assertEqual(owner, {'provider': 'youtube', 'revision': 0, 'profile_revision': 0,
                                 'available': False, 'reason': 'disabled'})
        display = self.service.snapshot('display:' + self.first['id'])
        self.assertEqual(display['reason'], 'display_not_allowed')
        self.assertNotIn('video_id', display)
        self.assertNotIn('watch_url', display)
        self.assertFalse(self.store.path.exists())

    def test_selected_household_and_owner_preview_have_distinct_authority_reasons(self):
        saved = self.service.configure(self.settings)
        self.assertEqual(saved['revision'], 1)
        display = self.service.snapshot('display:' + self.first['id'])
        self.assertEqual(display, {'provider': 'youtube', 'revision': 1, 'profile_revision': 0,
            'available': True, 'reason': 'allowed', 'video_id': 'Abcdef_12-3',
            'watch_url': 'https://www.youtube.com/watch?v=Abcdef_12-3'})
        owner = self.service.snapshot('owner')
        self.assertTrue(owner['available'])
        self.assertEqual(owner['reason'], 'owner_preview')
        unselected = self.service.snapshot('display:' + self.second['id'])
        self.assertEqual(unselected['reason'], 'display_not_allowed')
        self.assertFalse(unselected['available'])
        self.assertNotIn('video_id', unselected)
        self.assertNotIn('watch_url', unselected)

    def test_video_id_and_settings_are_strict_without_arbitrary_url_or_provider(self):
        for video_id in (' ', '\n', 'abc', 'Abcdef_12-3 ', 'https://youtu.be/Abcdef_12-3', '../example1', 'Abcdef/12-3'):
            with self.subTest(video_id=video_id), self.assertRaises(ValidationError):
                VideoSettings.model_validate({**self.settings, 'video_id': video_id})
        for changed in ({'video_id': ''}, {'revision': True}, {'enabled': 1}, {'provider': 'other'},
                        {'watch_url': 'https://example.com'}, {'allowed_display_ids': ['A' * 32]},
                        {'allowed_display_ids': [self.first['id'], self.first['id']]},
                        {'allowed_display_ids': [format(index, '032x') for index in range(33)]}):
            with self.subTest(changed=changed), self.assertRaises(ValidationError):
                VideoSettings.model_validate({**self.settings, **changed})
        self.assertEqual(VideoSettings.model_validate({'revision': 0, 'enabled': False}).video_id, '')

    def test_owner_cannot_select_unknown_or_current_guest_display(self):
        with self.assertRaisesRegex(ValueError, 'Household'):
            self.service.configure({**self.settings, 'allowed_display_ids': ['a' * 32]})
        self.displays.save_profile(self.first['id'], {'mode': 'guest'}, 0)
        with self.assertRaisesRegex(ValueError, 'Household'):
            self.service.configure(self.settings)
        self.assertEqual(self.store.snapshot()['revision'], 0)

    def test_profile_change_personal_and_mini_deny_even_when_device_is_selected(self):
        self.service.configure(self.settings)
        self.displays.save_profile(self.first['id'], {'mode': 'guest'}, 0)
        guest = self.service.snapshot('display:' + self.first['id'])
        self.assertEqual((guest['reason'], guest['profile_revision']), ('guest_not_allowed', 1))
        personal = self.service.snapshot(PersonalPrincipal('display:' + self.first['id'], 'a' * 32, 'b' * 32))
        self.assertEqual(personal['reason'], 'personal_not_allowed')
        mini = self.service.snapshot('round')
        self.assertEqual(mini['reason'], 'mini_not_allowed')
        for result in (guest, personal, mini):
            self.assertFalse(result['available'])
            self.assertNotIn('video_id', result)
            self.assertNotIn('watch_url', result)

    def test_disabling_and_removing_allowlist_hide_previously_selected_video(self):
        self.service.configure(self.settings)
        self.service.configure({**self.settings, 'revision': 1, 'enabled': False})
        disabled = self.service.snapshot('display:' + self.first['id'])
        self.assertEqual(disabled['reason'], 'disabled')
        self.assertNotIn('video_id', disabled)
        self.service.configure({**self.settings, 'revision': 2, 'allowed_display_ids': []})
        removed = self.service.snapshot('display:' + self.first['id'])
        self.assertEqual(removed['reason'], 'display_not_allowed')
        self.assertNotIn('watch_url', removed)

    def test_display_revocation_cannot_reuse_retained_selection(self):
        self.service.configure(self.settings)
        self.displays.revoke(self.first['id'])
        with self.assertRaises(HTTPException) as raised:
            self.service.snapshot('display:' + self.first['id'])
        self.assertEqual(raised.exception.status_code, 401)
        with self.assertRaises(ValueError):
            self.service.configure({**self.settings, 'revision': 1})

    def test_revision_conflict_and_encrypted_roundtrip_preserve_existing_selection(self):
        self.service.configure(self.settings)
        with self.assertRaises(ExperienceConflict):
            self.service.configure({**self.settings, 'video_id': 'Xbcdef_12-3'})
        raw = self.store.path.read_bytes()
        self.assertNotIn(b'Abcdef_12-3', raw)
        self.assertNotIn(self.first['id'].encode(), raw)
        restored = VideoStore(self.root, self.protector)
        self.assertEqual(restored.snapshot(), {**self.settings, 'revision': 1})
        result = restored.snapshot()
        result['allowed_display_ids'].clear()
        self.assertEqual(restored.snapshot()['allowed_display_ids'], [self.first['id']])

    def test_unreadable_oversized_and_invalid_encrypted_state_are_preserved(self):
        invalid_model = json.dumps({**self.settings, 'video_id': 'not valid'}).encode()
        envelope = json.dumps({'version': 1, 'protected': base64.b64encode(self.protector.encrypt(invalid_model)).decode()}).encode()
        for raw in (b'not-json', b'x' * (MAX_FILE_BYTES + 1), envelope):
            with self.subTest(size=len(raw)):
                self.store.path.parent.mkdir(parents=True, exist_ok=True)
                self.store.path.write_bytes(raw)
                restored = VideoStore(self.root, self.protector)
                self.assertTrue(restored.error)
                with self.assertRaises(VideoUnavailable):
                    restored.snapshot()
                with self.assertRaises(VideoUnavailable):
                    restored.save(self.settings)
                self.assertEqual(self.store.path.read_bytes(), raw)

    def test_failed_save_retains_memory_and_encrypted_file(self):
        self.service.configure(self.settings)
        before = self.store.path.read_bytes()
        with patch.object(self.protector, 'encrypt', side_effect=RuntimeError('Synthetic protector failure')):
            with self.assertRaises(VideoUnavailable):
                self.service.configure({**self.settings, 'revision': 1, 'enabled': False})
        self.assertTrue(self.store.snapshot()['enabled'])
        self.assertEqual(self.store.snapshot()['revision'], 1)
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_snapshot_and_configure_take_display_lock_before_store_lock(self):
        for action in (lambda: self.service.snapshot('owner'), lambda: self.service.configure(self.settings)):
            started, finished = Event(), Event()
            failures = []

            def run():
                started.set()
                try:
                    action()
                except Exception as error:
                    failures.append(error)
                finally:
                    finished.set()

            with self.displays.lock:
                worker = Thread(target=run, daemon=True)
                worker.start()
                self.assertTrue(started.wait(1))
                acquired = self.store.lock.acquire(timeout=1)
                try:
                    self.assertTrue(acquired, 'Video access held the store while waiting on display access')
                finally:
                    if acquired:
                        self.store.lock.release()
            self.assertTrue(finished.wait(2))
            worker.join(1)
            self.assertEqual(failures, [])


class VideoProviderApiTests(VideoFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app = FastAPI()

        def authorize(request: Request):
            principal = request.headers.get('x-test-principal', 'owner')
            if principal == 'personal':
                return PersonalPrincipal('display:' + self.first['id'], 'a' * 32, 'b' * 32)
            if principal.startswith('display:'):
                self.displays.profile_for(principal)
            return principal

        def owner(request: Request):
            if authorize(request) != 'owner':
                raise HTTPException(403, 'Owner only')

        install(self.app, self.service, authorize, owner)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_exact_settings_and_selection_routes_enforce_owner_and_omit_denied_ids(self):
        self.assertIs(self.app.state.video_provider, self.service)
        path = '/v1/display/video/settings'
        display = {'x-test-principal': 'display:' + self.first['id']}
        self.assertEqual(self.client.get(path, headers=display).status_code, 403)
        self.assertEqual(self.client.put(path, headers=display, json=self.settings).status_code, 403)
        self.assertEqual(self.client.put(path, json=self.settings).json()['revision'], 1)
        self.assertEqual(self.client.put(path, json=self.settings).status_code, 409)
        self.assertEqual(self.client.get('/v1/display/video', headers=display).json()['reason'], 'allowed')
        self.assertEqual(self.client.get('/v1/display/video').json()['reason'], 'owner_preview')
        for principal in ('personal', 'round', 'display:' + self.second['id']):
            response = self.client.get('/v1/display/video', headers={'x-test-principal': principal})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['available'])
            self.assertNotIn('video_id', response.json())
            self.assertNotIn('watch_url', response.json())

    def test_bad_settings_and_unreadable_store_map_to_bounded_api_errors(self):
        path = '/v1/display/video/settings'
        self.assertEqual(self.client.put(path, json={**self.settings, 'video_id': 'https://example.com'}).status_code, 422)
        self.assertEqual(self.client.put(path, json={**self.settings, 'allowed_display_ids': ['a' * 32]}).status_code, 422)
        self.store.error = True
        self.assertEqual(self.client.get(path).status_code, 503)
        self.assertEqual(self.client.get('/v1/display/video').status_code, 503)


if __name__ == '__main__':
    unittest.main()
