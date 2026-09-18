import io
import json
from pathlib import Path
import queue
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.neural_speech import NeuralSpeech, MAX_PCM
from backend.settings import EchoSettings, SettingsStore, speech_settings
from backend.speech import synthesize
from backend.tts_catalog import catalog, validate_selection


def installed(root):
    files = ['local/tts-python/Scripts/python.exe','local/models/kokoro-82m-official/kokoro-v1_0.pth',
             'local/models/kokoro-82m-official/voices/bm_george.pt',
             'local/models/pocket-tts-english-official/languages/english/model.safetensors']
    for relative in files:
        path = root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.touch()
    (root/'local/tts-runtime-ready.json').write_text(json.dumps({'engines':{'kokoro':True,'pocket':True}}))


class SelectionTests(unittest.TestCase):
    def test_existing_settings_keep_sapi_and_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'local').mkdir()
            (root/'local/echo-settings.json').write_text(json.dumps({'settings':{'tts_voice':'old Windows voice','tts_rate':-1}}))
            result = speech_settings(root)
            self.assertEqual((result.tts_engine,result.tts_voice,result.tts_rate),('sapi','old Windows voice',-1))

    def test_corrupt_or_missing_readiness_does_not_enable_models(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); installed(root)
            for value in ['[]','null','{"engines":[]}','bad json','{}']:
                (root/'local/tts-runtime-ready.json').write_text(value)
                self.assertFalse(any(e['available'] for e in catalog(root,[]) if e['id']!='sapi'))

    def test_voice_engine_and_pace_must_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); installed(root)
            for options in [{'tts_engine':'kokoro','tts_voice':'george'},
                            {'tts_engine':'pocket','tts_voice':'bm_george'},
                            {'tts_engine':'pocket','tts_voice':'george','tts_rate':1},
                            {'tts_engine':'kokoro','tts_voice':'../../outside'}]:
                with self.assertRaises(ValueError): validate_selection(EchoSettings(**options),root,[])
            for engine in ['kokoro','pocket']: validate_selection(EchoSettings(tts_engine=engine),root,[])

    def test_dispatch_uses_selected_engine_and_never_falls_back(self):
        settings = EchoSettings(tts_engine='pocket')
        with patch('backend.neural_speech.synthesize',return_value=(b'\x01\x02',{})) as neural, patch('backend.speech.subprocess.run') as windows:
            self.assertEqual(synthesize('Hello',settings=settings),b'\x01\x02')
            neural.assert_called_once_with('Hello',settings,cancel=None); windows.assert_not_called()
            neural.side_effect = RuntimeError('unavailable')
            with self.assertRaises(RuntimeError): synthesize('Hello',settings=settings)
            windows.assert_not_called()


class ProtocolTests(unittest.TestCase):
    def client(self,data):
        client = NeuralSpeech.__new__(NeuralSpeech); client.engine='kokoro'
        client.replies=queue.Queue(maxsize=2); client.close=Mock()
        client.process=Mock(stdin=io.BytesIO(),stdout=io.BytesIO(data))
        return client

    def packet(self,metadata,pcm=b''):
        meta=json.dumps(metadata).encode(); return struct.pack('<II',len(meta),len(pcm))+meta+pcm

    def test_pcm_framing_preserves_binary_content(self):
        pcm=bytes(range(256))*8
        client=self.client(self.packet({'ok':True,'engine':'kokoro','sample_rate':48000,'network_attempts':0},pcm))
        client._read()
        self.assertEqual(client.synthesize('No file or speaker involved')[0],pcm)
        raw=client.process.stdin.getvalue(); size,=struct.unpack('<I',raw[:4])
        self.assertEqual(size,len(raw)-4)
        self.assertEqual(json.loads(raw[4:])['voice'],'bm_george')

    def test_invalid_or_truncated_frame_fails_without_waiting(self):
        for raw in [struct.pack('<II',4097,0),struct.pack('<II',1,MAX_PCM+2),b'bad',
                    self.packet({'ok':True,'engine':'pocket','sample_rate':48000},b'\0\0'),
                    self.packet({'ok':True,'engine':'kokoro','sample_rate':24000},b'\0\0')]:
            client=self.client(raw); client._read()
            with self.assertRaises(RuntimeError): client.synthesize('Hello')
            client.close.assert_called_once()

    def test_remote_request_and_error_details_are_never_delivered(self):
        for metadata in [{'ok':False,'error':'private spoken text'},
                         {'ok':True,'engine':'kokoro','network_attempts':1}]:
            client=self.client(self.packet(metadata)); client._read()
            with self.assertRaises(RuntimeError) as caught: client._get(.1)
            self.assertNotIn('private spoken text',str(caught.exception))


class VoiceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); installed(self.root)
        self.store=SettingsStore()
        self.client=TestClient(create_app('t'*32,runtime_root=self.root,settings_store=self.store),base_url='http://127.0.0.1')
        self.auth={'Authorization':'Bearer '+'t'*32}

    def test_check_is_authenticated_silent_and_does_not_save_selection(self):
        body={'tts_engine':'pocket','tts_voice':'george','tts_rate':0}
        with patch('backend.app.synthesize_checked',return_value=(b'\0\0',{'engine':'pocket','seconds':1,'generation_ms':12})) as synth, patch('backend.app.speech_voices',return_value=[]):
            self.assertEqual(self.client.post('/v1/settings/check-voice',json=body).status_code,401)
            synth.assert_not_called()
            response=self.client.post('/v1/settings/check-voice',json=body,headers=self.auth)
            self.assertEqual(response.status_code,200)
            self.assertFalse(response.json()['playback']); self.assertNotIn('pcm',response.text)
            self.assertEqual(self.store.settings.tts_engine,'sapi')
            self.assertEqual(synth.call_args.kwargs['settings'].tts_engine,'pocket')
            self.assertEqual(self.client.get('/v1/state',headers=self.auth).json()['timers'],[])

    def test_unavailable_invalid_selection_and_failure_are_reported(self):
        with patch('backend.app.speech_voices',return_value=[]), patch('backend.app.synthesize_checked',side_effect=RuntimeError('private text')) as synth:
            for body in [{'tts_engine':'pocket','tts_rate':1},{'tts_engine':'kokoro','tts_voice':'george'},
                         {'tts_engine':'pocket','text':'should not be accepted'}]:
                response=self.client.post('/v1/settings/check-voice',headers=self.auth,json=body)
                self.assertEqual(response.status_code,422)
            synth.assert_not_called()
            response=self.client.post('/v1/settings/check-voice',headers=self.auth,json={'tts_engine':'pocket'})
            self.assertEqual(response.status_code,503); self.assertNotIn('private text',response.text)
            (self.root/'local/tts-runtime-ready.json').unlink()
            response=self.client.put('/v1/settings',headers=self.auth,json={'settings':{'tts_engine':'pocket'}})
            self.assertEqual(response.status_code,422)

    def test_saved_engine_drives_health_and_available_voices(self):
        with patch('backend.app.speech_voices',return_value=[]):
            result=self.client.put('/v1/settings',headers=self.auth,json={'settings':{'tts_engine':'kokoro','tts_voice':'bm_george'}})
            self.assertEqual(result.status_code,200)
            self.assertEqual(self.client.get('/health').json()['text_to_speech'],'local_kokoro')
            items=self.client.get('/v1/settings/speech',headers=self.auth).json()['engines']
            self.assertEqual([v['id'] for v in items[1]['voices']],['bm_george'])
            self.assertFalse(items[2]['pace'])


if __name__=='__main__': unittest.main()
