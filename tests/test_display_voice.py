"""Pi voice tests use synthetic PCM and stub speech/models. No hardware or audio."""
import base64
from io import BytesIO
from pathlib import Path
import sys
from threading import Event
import unittest
from unittest.mock import Mock
import wave

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.display_voice import DisplayVoice,capture_pcm,wave_bytes,DisplayVoiceUnavailable
from backend.settings import SettingsStore
from backend.speech_jobs import SpeechCancelled
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from audio_once import scaled_reply


class VoiceTests(unittest.TestCase):
    def test_capture_bounds_and_quiet_output_scaling(self):
        raw=wave_bytes(b'\0\0'*1600,16000)
        self.assertEqual(len(capture_pcm(raw)),3200)
        for invalid in (b'bad',raw[:-1],wave_bytes(b'\0\0'*1600,48000),wave_bytes(b'\0\0'*128001,16000)):
            with self.assertRaises(ValueError):capture_pcm(invalid)
        encoded=base64.b64encode(wave_bytes((1000).to_bytes(2,'little',signed=True)*10,48000)).decode()
        self.assertEqual(int.from_bytes(scaled_reply(encoded,2)[:2],'little',signed=True),20)

    def pipeline(self):
        transcriber=Mock();transcriber.transcribe.return_value='A synthetic question'
        agent=Mock();agent.respond.return_value={'status':'complete','capability':'conversation','text':'A synthetic answer'}
        synth=Mock(return_value=(b'\0\0'*4800,{'sample_rate':48000}))
        pipeline=DisplayVoice(None,SettingsStore(),agent,transcriber=transcriber,synthesizer=synth)
        return pipeline,transcriber,agent,synth

    def test_reply_stays_in_request_and_cancellation_blocks_model_and_speech(self):
        pipeline,transcriber,agent,synth=self.pipeline()
        result=pipeline.respond(b'\0\0'*1600,'display:one',False,True,cancel=Event(),progress=lambda state:None)
        self.assertEqual(result['audio_destination'],'requesting_display');self.assertEqual(result['transcript'],'A synthetic question')
        self.assertEqual(agent.respond.call_args.args[1],'display:one');self.assertFalse(agent.respond.call_args.kwargs['allow_home_actions'])
        self.assertEqual(result['audio']['format'],'wav')
        agent.reset_mock();synth.reset_mock();cancel=Event();cancel.set()
        result=pipeline.respond(b'\0\0'*1600,'display:two',True,True,cancel=cancel,progress=lambda state:None)
        self.assertEqual(result['status'],'cancelled');agent.respond.assert_not_called();synth.assert_not_called()

    def test_busy_and_failed_transcription_do_not_leave_dead_worker(self):
        pipeline,transcriber,agent,synth=self.pipeline()
        pipeline.lock.acquire()
        try:
            with self.assertRaises(DisplayVoiceUnavailable):pipeline.respond(b'\0\0'*1600,'display:one',False,False,cancel=Event(),progress=lambda state:None)
        finally:pipeline.lock.release()
        transcriber.transcribe.side_effect=RuntimeError('synthetic worker failure')
        with self.assertRaises(DisplayVoiceUnavailable):pipeline.respond(b'\0\0'*1600,'display:one',False,False,cancel=Event(),progress=lambda state:None)
        transcriber.close.assert_called_once();self.assertIsNone(pipeline.worker);agent.respond.assert_not_called()

    def test_cancelling_synthesis_preserves_completed_home_action_receipts(self):
        pipeline,transcriber,agent,synth=self.pipeline()
        receipts=[{'entity_id':'light.demo','action':'turn_on','status':'complete','attempted':True}]
        agent.respond.return_value={'status':'complete','text':'Synthetic light action','home_actions':receipts}
        synth.side_effect=SpeechCancelled()
        result=pipeline.respond(b'\0\0'*1600,'display:one',True,True,cancel=Event(),progress=lambda state:None)
        self.assertEqual(result['status'],'cancelled');self.assertEqual(result['home_actions'],receipts)
        self.assertNotIn('audio',result)

    def test_api_identity_validation_mode_and_raw_audio_limits(self):
        app=create_app('synthetic-owner-token-'*3,deployment_mode='validation')
        pipeline,transcriber,agent,synth=self.pipeline();app.state.display_voice=pipeline
        with TestClient(app) as client:
            raw=wave_bytes(b'\0\0'*1600,16000)
            self.assertEqual(client.post('/v1/display/voice',content=raw,headers={'Content-Type':'audio/wav'}).status_code,401)
            client.headers['Authorization']='Bearer '+'synthetic-owner-token-'*3
            code=client.post('/v1/displays/pairing',json={'name':'Synthetic Pi'}).json()['code']
            credential=client.post('/v1/displays/enroll',json={'code':code}).json()['credential']
            client.headers['Authorization']='Display '+credential
            response=client.post('/v1/display/voice?allow_home=true&reply_audio=false',content=raw,headers={'Content-Type':'audio/wav'})
            self.assertEqual(response.status_code,200);self.assertNotIn('audio',response.json())
            self.assertEqual(agent.respond.call_args.args[1],'display:'+credential.split('.')[0]);self.assertFalse(agent.respond.call_args.kwargs['allow_home_actions'])
            synth.assert_not_called()
            self.assertEqual(client.post('/v1/display/voice',content=b'wrong',headers={'Content-Type':'audio/wav'}).status_code,422)
            self.assertEqual(client.post('/v1/display/voice',content=b'x'*270000,headers={'Content-Type':'audio/wav'}).status_code,413)
