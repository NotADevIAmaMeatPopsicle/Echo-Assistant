"""Actual-app video authorization, storage and browser headers; no media calls."""
import base64
import io
import json
import unittest

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.video_provider import MAX_FILE_BYTES
from tests import test_display_profiles as display_fixtures
from tests import test_members as member_fixtures
from tests.test_recovery_archive import record
from tools.recovery_archive import FILES, LIMITS, read_archive, write_archive
from tools.recovery_restore import restore


SELECTION = '/v1/display/video'
SETTINGS = SELECTION + '/settings'
VIDEO_ID = 'Abcdef_12-3'


class VideoAppTests(unittest.TestCase):
    with_runtime = True
    enroll = display_fixtures.DisplayProfileTests.enroll
    save = display_fixtures.DisplayProfileTests.save
    profile = display_fixtures.DisplayProfileTests.profile
    account = member_fixtures.MemberTests.account
    share = member_fixtures.MemberTests.share
    login = member_fixtures.MemberTests.login

    def setUp(self):
        display_fixtures.DisplayProfileTests.setUp(self)
        self.body = {'revision': 0, 'enabled': True, 'video_id': VIDEO_ID,
                     'allowed_display_ids': [self.paired['id']]}
        self.calls.clear()

    def configure(self, **changes):
        response = self.client.put(SETTINGS, headers=self.owner, json={**self.body, **changes})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def denied(self, headers, reason):
        response = self.client.get(SELECTION, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['provider'], 'youtube')
        self.assertEqual(result['reason'], reason)
        self.assertFalse(result['available'])
        self.assertNotIn('video_id', result)
        self.assertNotIn('watch_url', result)
        self.assertNotIn(VIDEO_ID, response.text)
        return result

    def no_settings_access(self, headers):
        for method in ('GET', 'PUT'):
            response = self.client.request(method, SETTINGS, headers=headers,
                **({'json': self.body} if method == 'PUT' else {}))
            self.assertEqual(response.status_code, 403, response.text)
            self.assertNotIn(VIDEO_ID, response.text)

    def test_owner_only_configuration_and_explicit_household_selection(self):
        for path in (SETTINGS, SELECTION):
            self.assertEqual(self.client.get(path).status_code, 401)
        initial = self.client.get(SETTINGS, headers=self.owner)
        self.assertEqual(initial.json(), {'provider': 'youtube', 'revision': 0,
            'enabled': False, 'video_id': '', 'allowed_display_ids': []})
        self.denied(self.owner, 'disabled')
        self.denied(self.guest, 'display_not_allowed')
        self.no_settings_access(self.guest)
        self.assertEqual(self.configure()['revision'], 1)
        selected = self.client.get(SELECTION, headers=self.guest)
        self.assertEqual(selected.json(), {'provider': 'youtube', 'revision': 1,
            'profile_revision': 0, 'available': True, 'reason': 'allowed',
            'video_id': VIDEO_ID, 'watch_url': 'https://www.youtube.com/watch?v=' + VIDEO_ID})
        preview = self.client.get(SELECTION, headers=self.owner).json()
        self.assertTrue(preview['available'])
        self.assertEqual(preview['reason'], 'owner_preview')
        other = self.enroll('Another synthetic display')
        self.denied({'Authorization': 'Display ' + other['credential']}, 'display_not_allowed')
        self.assertEqual(self.calls, [])
        self.provider.complete.assert_not_called()

    def test_configuration_validates_current_displays_and_revision_through_app(self):
        for change in ({'allowed_display_ids': ['a' * 32]}, {'video_id': 'https://example.com'},
                       {'video_id': ' '}, {'provider': 'youtube'}):
            response = self.client.put(SETTINGS, headers=self.owner, json={**self.body, **change})
            self.assertEqual(response.status_code, 422, response.text)
        self.configure()
        stale = self.client.put(SETTINGS, headers=self.owner, json={**self.body, 'enabled': False})
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.save().status_code, 200)
        response = self.client.put(SETTINGS, headers=self.owner, json={**self.body, 'revision': 1})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get(SETTINGS, headers=self.owner).json()['revision'], 1)

    def test_guest_profile_revokes_video_without_inheriting_owner_writes(self):
        self.configure()
        self.assertEqual(self.save().status_code, 200)
        denied = self.denied(self.guest, 'guest_not_allowed')
        self.assertEqual(denied['profile_revision'], 1)
        self.no_settings_access(self.guest)
        self.assertEqual(self.client.get(SETTINGS, headers=self.owner).json()['revision'], 1)

    def test_personal_session_and_mini_do_not_inherit_selected_household_video(self):
        account = self.account('Synthetic video member')
        self.share(account)
        self.configure()
        personal = self.login(account)
        self.denied(personal, 'personal_not_allowed')
        self.no_settings_access(personal)
        self.client.delete('/v1/member/session', headers=personal).raise_for_status()
        self.assertEqual(self.client.get(SELECTION, headers=self.guest).json()['reason'], 'allowed')
        mini = {**self.owner, 'X-Echo-Endpoint': 'round', 'X-Echo-Access-Revision': '0'}
        self.denied(mini, 'mini_not_allowed')
        self.no_settings_access(mini)
        self.assertEqual(self.calls, [])
        self.provider.complete.assert_not_called()

    def test_owner_disable_allowlist_removal_and_pairing_revocation_take_effect(self):
        self.configure()
        self.configure(revision=1, enabled=False)
        self.denied(self.guest, 'disabled')
        self.configure(revision=2, allowed_display_ids=[])
        self.denied(self.guest, 'display_not_allowed')
        self.configure(revision=3)
        revoked = self.client.delete('/v1/displays/' + self.paired['id'], headers=self.owner)
        self.assertEqual(revoked.status_code, 200, revoked.text)
        response = self.client.get(SELECTION, headers=self.guest)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertNotIn(VIDEO_ID, response.text)
        response = self.client.put(SETTINGS, headers=self.owner, json={**self.body, 'revision': 4})
        self.assertEqual(response.status_code, 422, response.text)

    def test_recovery_registration_keeps_encrypted_selection_and_app_binding(self):
        self.configure()
        self.assertIn('echo-video.json', FILES)
        self.assertGreaterEqual(LIMITS.get('echo-video.json', 500_000), MAX_FILE_BYTES)
        key = base64.b64encode((self.root / 'key').read_bytes()).decode()
        names = ('echo-video.json', 'echo-displays.json')
        payload = {'kind': 'echo-remote', 'version': 2, 'created_at': 1.0,
            'files': {name: record((self.root / 'local' / name).read_bytes()) for name in names},
            'photos': {}, 'bootstrap': {'api': {'storage_key': key}, 'agent': {}}}
        archive = self.root / 'synthetic-video.echo-backup'
        write_archive(archive, payload, self.protector, lambda _: self.fail('No photos selected'))
        for private in (VIDEO_ID.encode(), self.paired['id'].encode()):
            self.assertNotIn(private, archive.read_bytes())
            self.assertNotIn(private, (self.root / 'local/echo-video.json').read_bytes())
        loaded = read_archive(archive, self.protector)
        replacement = self.root / 'replacement'
        destination = replacement / 'local'
        destination.mkdir(parents=True)
        header = {'names': FILES, 'limits': LIMITS, 'files': loaded['files'], 'photos': {}, 'storage_key': key}
        restore(destination, io.BytesIO(json.dumps(header).encode() + b'\n'))
        app = create_app('replacement-token-' * 3, home=self.home, home_catalog=self.catalog,
            home_access_store=self.access, settings_store=self.settings, provider=self.provider,
            runtime_root=replacement)
        client = TestClient(app, base_url='http://localhost')
        self.addCleanup(client.close)
        response = client.get(SETTINGS, headers={'Authorization': 'Bearer ' + 'replacement-token-' * 3})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'provider': 'youtube', **self.body, 'revision': 1})
        response = client.get(SELECTION, headers=self.guest)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['reason'], 'allowed')
        self.assertEqual(app.state.video_provider.store.path, destination / 'echo-video.json')

    def test_player_route_has_only_required_youtube_permissions(self):
        response = self.client.get('/display/video-player')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('/assets/display/video-player.js', response.text)
        self.assertIn('/assets/display/video-player.css', response.text)
        self.assertEqual(response.headers['referrer-policy'], 'strict-origin-when-cross-origin')
        self.assertEqual(response.headers['permissions-policy'], 'camera=(), microphone=(), geolocation=()')
        policy = dict((entry.split()[0], entry.split()[1:])
                      for entry in response.headers['content-security-policy'].split(';') if entry.strip())
        self.assertEqual(policy['script-src'], ["'self'", 'https://www.youtube.com', 'https://s.ytimg.com'])
        self.assertEqual(policy['frame-src'], ['https://www.youtube-nocookie.com'])
        for directive in ('default-src', 'style-src', 'connect-src'):
            self.assertEqual(policy[directive], ["'self'"])
        for directive in ('frame-ancestors', 'base-uri', 'form-action', 'object-src'):
            self.assertEqual(policy[directive], ["'none'"])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.calls, [])

    def test_normal_pages_assets_and_api_do_not_inherit_player_policy(self):
        for path in ('/', '/display', '/assets/display/video-provider.js',
                     '/assets/display/video-provider.css', '/assets/display/video-player.js',
                     '/assets/display/video-player.css', '/assets/display/video-player.html',
                     SELECTION, SETTINGS):
            with self.subTest(path=path):
                response = self.client.get(path, headers=self.owner)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
                policy = response.headers['content-security-policy']
                self.assertNotIn('youtube', policy)
                self.assertNotIn('ytimg', policy)
                self.assertIn("script-src 'self'", policy)
                self.assertEqual(response.headers['cache-control'], 'no-store')
        for path in ('/display/video-player/', '/display/video-player-extra'):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
            self.assertNotIn('youtube', response.headers['content-security-policy'])
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
