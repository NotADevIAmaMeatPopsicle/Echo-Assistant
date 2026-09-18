import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.lifecycle import Lifecycle
from backend.speaker_check import SpeakerCheck


class SpeakerCheckTests(unittest.TestCase):
    def status(self,root,**changes):
        value={'status':'armed','muted':False,'device':{'volume':'2'},'speaker':{'active':False},
               'music':{'status':'connected'},'updated_at':time.time(),**changes}
        (root/'local/voice-status.json').write_text(json.dumps(value));return value

    def test_requires_live_owner_idle_unmuted_and_quiet_volume(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);check=SpeakerCheck(root)
            with self.assertRaises(ValueError):check.request()
            with Lifecycle(root):
                for change in ({'status':'speaking'},{'muted':True},{'music':{'status':'playing'}},
                               {'speaker':{'active':True}},{'device':{'volume':'0'}},{'device':{'volume':'4'}},
                               {'device':{'volume':'unknown'}},{'updated_at':time.time()-10}):
                    self.status(root,**change)
                    with self.assertRaises(ValueError):check.request()
                self.status(root);self.assertEqual(check.request()['status'],'queued')
                with self.assertRaises(ValueError):check.request()

    def test_cancel_and_generation_guard_prevent_old_requests_playing(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);check=SpeakerCheck(root)
            with Lifecycle(root) as owner:
                status=self.status(root);request=check.request()
                check.cancel(request['id']);self.assertIsNone(check.claim(owner.identity,status))
                self.assertEqual(check.state()['status'],'cancelled')
                request=check.request();self.assertIsNone(check.claim('b'*32,status))
                self.assertEqual(check.state()['status'],'failed')
                request=check.request();self.assertEqual(check.claim(owner.identity,status),request['id'])
                self.assertFalse(check.cancelled(request['id'],owner.identity))
                check.cancel(request['id']);self.assertTrue(check.cancelled(request['id'],owner.identity))
            self.assertEqual(check.state()['status'],'failed')

    def test_terminal_result_is_bounded_metadata_and_stale_result_cannot_replace_new_check(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);check=SpeakerCheck(root)
            with Lifecycle(root) as owner:
                status=self.status(root);first=check.request()['id'];check.claim(owner.identity,status)
                check.update(first,'playing');check.update(first,'complete',frames=530)
                self.assertEqual(check.state()['frames'],530)
                self.assertNotIn('run_id',check.state())
                second=check.request()['id'];check.update(first,'complete',frames=999)
                self.assertEqual(check.state()['id'],second)
                self.assertEqual(check.state()['status'],'queued')
                self.assertNotIn('text',json.loads(check.path.read_text()))

    def test_validation_and_internal_identity_cannot_start_sample(self):
        with patch('backend.app.SpeakerCheck.request') as start:
            app=create_app('a'*40,deployment_mode='validation',home_tools_token='b'*40)
            with TestClient(app) as client:
                self.assertEqual(client.post('/v1/settings/speaker-check',headers={'Authorization':'Bearer '+'a'*40}).status_code,409)
                self.assertEqual(client.post('/v1/settings/speaker-check',headers={'Authorization':'Bearer '+'b'*40}).status_code,401)
            start.assert_not_called()


if __name__=='__main__':unittest.main()
