from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, MagicMock
from tools import check_voice_session as observer


class VoiceObservationTests(unittest.TestCase):
    def observe(self, corrupt=False, remote=False):
        with TemporaryDirectory() as directory:
            root=Path(directory); (root/'local').mkdir()
            (root/'local/api-token').write_text('test-token', encoding='utf-8')
            if remote:(root/'local/host-target.json').write_text('{"mode":"remote"}')
            result_path=root/'local/voice-endurance.json'
            result_path.write_text('{"result":"PASS","old":true}', encoding='utf-8')
            now=[0]
            def fetch(*args):
                return {'status':'armed', 'phase':'armed', 'connection_id':'one', 'transport':'usb',
                        'pcm_frames':int(now[0]*60), 'muted':False,
                        'usb_errors':1 if corrupt and now[0] else 0,
                        'device':{'version':'0.8.3','volume':'0','usb_drops':'0','stream_drops':'0','audio_errors':'0'},
                        'recognition':{'alive':True,'dropped':0,'errors':0},
                        'framing':{'header':int(corrupt and now[0]>0),'checksum':0,'noise':0,'console_interference':0},
                        'music':{'title':'private-media-title'}, 'transcript':'private-words'}
            api=MagicMock()
            def remote_read(*args,**kwargs):
                response=MagicMock();response.json.return_value=fetch();return response
            api.get.side_effect=remote_read
            with patch.object(observer,'ROOT',root), patch.object(observer,'fetch',side_effect=fetch) as local_read, patch('tools.remote_device.client',return_value=api):
                with patch.object(observer.time,'monotonic',side_effect=lambda:now[0]), patch.object(observer.time,'sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)):
                    with patch('sys.argv',['check_voice_session.py','--seconds','10']), redirect_stdout(io.StringIO()):
                        if corrupt:
                            with self.assertRaises(SystemExit) as stopped: observer.main()
                            self.assertEqual(stopped.exception.code,1)
                        else: observer.main()
                if remote:local_read.assert_not_called();self.assertTrue(api.get.called)
            content=result_path.read_text(encoding='utf-8')
            self.assertNotIn('private-media-title',content); self.assertNotIn('private-words',content)
            self.assertNotIn('old',json.loads(content))
            return json.loads(content)

    def test_failed_observation_replaces_old_pass_with_content_free_evidence(self):
        result=self.observe(True)
        self.assertEqual(result['result'],'FAIL')
        self.assertEqual(result['reason'],'usb_errors increased')
        self.assertEqual(result['framing']['header'],1)
        self.assertEqual(result['firmware'],'0.8.3')

    def test_pass_identifies_firmware_and_muted_output(self):
        result=self.observe()
        self.assertEqual(result['result'],'PASS')
        self.assertEqual(result['microphone_frames'],600)
        self.assertEqual(result['speaker_volume'],'0')
        self.assertFalse(result['microphone_muted'])

    def test_migrated_observation_uses_the_server_and_never_reads_laptop_health(self):
        self.assertEqual(self.observe(remote=True)['result'],'PASS')


if __name__=='__main__': unittest.main()
