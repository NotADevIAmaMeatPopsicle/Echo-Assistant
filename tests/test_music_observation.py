from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import httpx
from tools import check_music_session as observer


class MusicObservationTests(unittest.TestCase):
    def observe(self, failure=None, remote=False):
        with TemporaryDirectory() as directory:
            root=Path(directory); (root/'local').mkdir()
            if remote: (root/'local/host-target.json').write_text('{"mode":"remote"}')
            else: (root/'local/api-token').write_text('test-token')
            receipt=root/'local/music-endurance.json'
            receipt.write_text('{"result":"PASS","old":true}')
            now=[0]
            def reply(request):
                fail=now[0]>0
                state={'phase':'music','status':'music','connection_id':'one',
                       'device':{'version':'0.11.5','audio_errors':0,
                                 'stream_drops':int(fail and failure=='mic_drop')},
                       'speaker':{'active':True,'kind':'M','frames':int(now[0]*(1 if failure=='slow' else 187.5)),
                                  'underruns':int(fail and failure=='underrun')},
                       'music':{'status':'playing','title':'private-media'},
                       'transcript':'private-speech'}
                if failure=='interaction' and now[0]>=5:
                    state.update(phase='listening',status='listening')
                    state['speaker']['active']=False; state['music']['status']='paused'
                return httpx.Response(200,json=state)
            client=httpx.Client(transport=httpx.MockTransport(reply),base_url='http://test')
            with patch.object(observer,'ROOT',root), patch.object(observer.httpx,'Client',return_value=client) as local, \
                 patch('tools.remote_device.client',return_value=client) as server, \
                 patch.object(observer.time,'monotonic',side_effect=lambda:now[0]), \
                 patch.object(observer.time,'sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)), \
                 patch('sys.argv',['check_music_session.py','--seconds','10','--wait-seconds','1']), redirect_stdout(io.StringIO()):
                if failure:
                    with self.assertRaises(SystemExit) as stopped: observer.main()
                    self.assertEqual(stopped.exception.code,2 if failure=='interaction' else 1)
                else: observer.main()
                if remote: local.assert_not_called(); server.assert_called_once()
                else: server.assert_not_called()
            content=receipt.read_text()
            self.assertNotIn('private-',content)
            self.assertNotIn('old',json.loads(content))
            return json.loads(content)

    def test_underrun_replaces_old_pass(self):
        result=self.observe('underrun')
        self.assertEqual(result['result'],'FAIL')
        self.assertEqual(result['reason'],'Speaker underrun')

    def test_microphone_loss_invalidates_duplex_acceptance(self):
        result=self.observe('mic_drop')
        self.assertEqual(result['result'],'FAIL')
        self.assertIn('device.stream_drops',result['reason'])

    def test_pass_requires_advancing_delivered_frames(self):
        result=self.observe()
        self.assertEqual(result['result'],'PASS')
        self.assertGreaterEqual(result['actual_music_seconds'],10)

    def test_migrated_observation_reads_server_without_laptop_token(self):
        self.assertEqual(self.observe(remote=True)['result'],'PASS')

    def test_slowly_advancing_frames_do_not_count_as_sustained_playback(self):
        self.assertEqual(self.observe('slow')['result'],'FAIL')

    def test_voice_interruption_is_incomplete_not_a_stream_failure(self):
        result=self.observe('interaction')
        self.assertEqual(result['result'],'INCOMPLETE')
        self.assertTrue(result['voice_interrupted'])

    def test_migration_never_falls_back_to_old_host(self):
        with TemporaryDirectory() as directory:
            root=Path(directory); (root/'local').mkdir()
            (root/'local/host-target.json').write_text('{"mode":"migrating"}')
            with patch.object(observer,'ROOT',root), patch.object(observer.httpx,'Client') as client:
                with self.assertRaisesRegex(SystemExit,'transfer'): observer.target_client()
                client.assert_not_called()
