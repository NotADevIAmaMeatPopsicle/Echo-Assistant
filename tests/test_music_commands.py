import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.lifecycle import Lifecycle
from backend.music_commands import request,take


class MusicCommandTests(unittest.TestCase):
    def test_command_targets_only_the_current_voice_generation(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaises(ValueError):request(root,'play')
            with Lifecycle(root) as voice:
                (root/'local/voice-status.json').write_text(json.dumps({'updated_at':time.time(),'status':'armed','music':{'status':'connected'}}))
                self.assertEqual(request(root,'play')['status'],'queued')
                self.assertIsNone(take(root,'a-different-generation'))
                request(root,'pause');self.assertEqual(take(root,voice.identity),'pause')
                self.assertIsNone(take(root,voice.identity))
                with self.assertRaises(ValueError):request(root,'anything-else')
                (root/'local/voice-status.json').write_text(json.dumps({'updated_at':time.time(),'status':'speaking','music':{'status':'connected'}}))
                with self.assertRaises(ValueError):request(root,'play')

    def test_pause_is_allowed_during_interaction_but_play_and_offline_commands_are_not(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            with Lifecycle(root) as owner:
                def publish(phase):
                    (root/'local/voice-status.json').write_text(json.dumps({
                        'updated_at':time.time(),'status':phase,'music':{'status':'paused'}}))
                for phase in ('activation','listening','thinking','speaking','alarm'):
                    with self.subTest(phase=phase):
                        publish(phase)
                        self.assertEqual(request(root,'pause')['status'],'queued')
                        self.assertEqual(take(root,owner.identity),'pause')
                        for action in ('play','toggle','next','previous'):
                            with self.assertRaises(ValueError): request(root,action)
                for phase in ('connecting','disconnected'):
                    publish(phase)
                    with self.assertRaises(ValueError): request(root,'pause')

    def test_validation_rejects_playback_and_internal_credentials_have_no_music_access(self):
        with patch('backend.app.request_music') as send:
            app=create_app('a'*40,deployment_mode='validation',home_tools_token='b'*40)
            with TestClient(app) as client:
                self.assertEqual(client.post('/v1/music/control',headers={'Authorization':'Bearer '+'a'*40},json={'action':'play'}).status_code,409)
                self.assertEqual(client.post('/v1/music/control',headers={'Authorization':'Bearer '+'b'*40},json={'action':'play'}).status_code,401)
            send.assert_not_called()


if __name__=='__main__':unittest.main()
