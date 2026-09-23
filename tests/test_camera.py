"""Camera permission/lifecycle and image-provider contracts without hardware or network."""
import base64
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.settings import EchoSettings
from backend.vision import install

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from local_camera import LocalCamera, DEFAULTS, meet_url, validate
from spotify import Unavailable


class CameraTests(unittest.TestCase):
    def test_lease_is_exclusive_bound_to_client_and_revoked_on_profile_change(self):
        with TemporaryDirectory() as tmp:
            session={'profile':{'mode':'household'},'profile_revision':2}
            camera=LocalCamera(lambda *a,**k:session,Mock(),Mock(),home=tmp)
            camera.stop.set();camera.thread.join(2)
            camera.start_worker=Mock();camera.end_worker=Mock()
            try:
                lease=camera.start_capture('a'*32,'preview');body={'client':'a'*32,'lease':lease['lease']}
                with self.assertRaises(Unavailable):camera.start_capture('b'*32,'preview')
                with self.assertRaises(Unavailable):camera.pulse({**body,'client':'b'*32})
                self.assertTrue(camera.presence_suspended)
                session['profile_revision']=3
                with self.assertRaises(Unavailable):camera.pulse(body)
                self.assertIsNone(camera.lease);camera.end_worker.assert_called()
            finally:camera.close()

    def test_meet_link_and_settings_reject_arbitrary_targets_and_invalid_focus(self):
        self.assertEqual(meet_url('abc-defg-hij'),'https://meet.google.com/abc-defg-hij')
        for value in ['https://evil.invalid/abc-defg-hij','abc-defg-hij?redirect=x','; reboot']:
            with self.assertRaises(ValueError):meet_url(value)
        self.assertEqual(validate({**DEFAULTS,'focus':4095})['focus'],4095)
        with self.assertRaises(ValueError):validate({**DEFAULTS,'focus':4096})
        with self.assertRaises(ValueError):validate({**DEFAULTS,'presence':'yes'})


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.settings=EchoSettings(provider='openai',model='synthetic-vision')
        self.state={'profile':{'mode':'household'},'profile_revision':1}
        self.store=SimpleNamespace(revision=0,snapshot=lambda:(self.settings,{'openai':'synthetic-key'},0))
        self.app=FastAPI();install(self.app,self.store,lambda:'owner',SimpleNamespace(profile_for=lambda p:self.state))
        self.api=TestClient(self.app)
        self.body={'image':base64.b64encode(b'\xff\xd8'+b'x'*100+b'\xff\xd9').decode(),'question':'What color?'}

    def test_one_frame_has_no_tools_or_storage_and_response_is_plain_text(self):
        with patch('backend.vision.Provider._request',return_value={'output':[{'type':'message','content':[{'type':'output_text','text':'Blue.'}]}]}) as send:
            response=self.api.post('/v1/display/vision',json=self.body)
            self.assertEqual(response.status_code,200);self.assertEqual(response.json()['text'],'Blue.')
            payload=send.call_args.args[3]
            self.assertIs(payload['store'],False);self.assertNotIn('tools',payload)
            self.assertEqual(payload['input'][0]['content'][1]['type'],'input_image')

    def test_guest_malformed_image_and_profile_change_never_leak_answer(self):
        with patch('backend.vision.Provider._request') as send:
            self.state['profile']['mode']='guest'
            self.assertEqual(self.api.post('/v1/display/vision',json=self.body).status_code,403);send.assert_not_called()
            self.state['profile']['mode']='household'
            self.assertEqual(self.api.post('/v1/display/vision',json={**self.body,'image':'z'*100}).status_code,422);send.assert_not_called()
            def changed(*a,**k):
                self.state['profile_revision']+=1
                return {'output':[{'type':'message','content':[{'type':'output_text','text':'private answer'}]}]}
            send.side_effect=changed
            response=self.api.post('/v1/display/vision',json=self.body)
            self.assertEqual(response.status_code,409);self.assertNotIn('private answer',response.text)


if __name__=='__main__':unittest.main()
