import unittest

from tools.preview_members import PreviewMembers


class PreviewMemberGoogleTests(unittest.TestCase):
    def test_personal_google_dialog_has_safe_empty_preview_settings(self):
        preview = PreviewMembers()
        account = preview.mutate('POST', '/v1/members', {'name': 'Sample person'})
        self.assertIsNone(preview.read('/v1/member/calendar/google'))
        preview.mutate('POST', '/v1/member/session',
                       {'member': account['id'], 'passcode': account['passcode']})
        settings = preview.read('/v1/member/calendar/google')
        self.assertEqual(settings['accounts'], [])
        self.assertEqual(settings['calendars'], [])
        self.assertFalse(settings['enabled'])
        self.assertFalse(settings['configured'])
        self.assertTrue(settings['read_only'])
        self.assertIsNone(preview.mutate('POST', '/v1/member/calendar/google/flows', {}))


if __name__ == '__main__':
    unittest.main()
