import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
import httpx
from backend.neural_speech import NeuralSpeech
from backend import neural_speech
from backend.reply_request import post_text
from backend.settings import EchoSettings
from backend.speech import synthesize
from backend.speech_jobs import SpeechJobs, SpeechCancelled, check_cancel


class JobTests(unittest.TestCase):
    def test_cancelled_finished_result_cannot_be_delivered(self):
        with ThreadPoolExecutor(1) as worker, SpeechJobs(worker) as jobs:
            job=jobs.submit(lambda *,cancel: b'not playable after cancel')
            self.assertEqual(job.future.result(timeout=1),b'not playable after cancel')
            job.cancel()
            with self.assertRaises(SpeechCancelled): job.result()

    def test_session_exit_cancels_running_and_queued_work_before_joining(self):
        entered=threading.Event(); executed=[]
        def active(*,cancel):
            entered.set()
            if not cancel.wait(2): raise AssertionError('Session failed to cancel')
            check_cancel(cancel)
        started=time.monotonic()
        with ThreadPoolExecutor(1) as worker:
            with SpeechJobs(worker) as jobs:
                job=jobs.submit(active); self.assertTrue(entered.wait(1))
                queued=jobs.submit(lambda *,cancel: executed.append(True))
            with self.assertRaises(SpeechCancelled): job.future.result(timeout=1)
            self.assertTrue(queued.future.cancelled())
        self.assertFalse(executed); self.assertLess(time.monotonic()-started,1)

    def test_cancelling_lock_waiter_does_not_release_another_request(self):
        cancel=threading.Event()
        with neural_speech._lock, ThreadPoolExecutor(1) as worker:
            pending=worker.submit(neural_speech.prepare,EchoSettings(tts_engine='pocket'),cancel=cancel)
            cancel.set()
            with self.assertRaises(SpeechCancelled): pending.result(timeout=1)
            self.assertTrue(neural_speech._lock.locked())


class ChildCancellationTests(unittest.TestCase):
    def launcher(self,script):
        original=subprocess.Popen; children=[]; launched=threading.Event()
        def launch(*_,**kwargs):
            # The fake uses this test interpreter, not the separate deployed TTS
            # runtime. Its Python home/library path must match that interpreter.
            if 'env' in kwargs:kwargs['env']={k:v for k,v in kwargs['env'].items() if k not in {'PYTHONHOME','LD_LIBRARY_PATH'}}
            child=original([sys.executable,'-u','-c',script],**kwargs)
            children.append(child); launched.set()
            return child
        def cleanup():
            for child in children:
                if child.poll() is None: child.kill(); child.wait(timeout=2)
        self.addCleanup(cleanup)
        return launch,children,launched

    def test_cancelling_cold_model_load_kills_only_owned_child(self):
        launch,children,launched=self.launcher('import time; time.sleep(20)')
        cancel=threading.Event()
        with patch('backend.neural_speech.subprocess.Popen',side_effect=launch), ThreadPoolExecutor(1) as executor:
            pending=executor.submit(NeuralSpeech,'kokoro',cancel=cancel)
            self.assertTrue(launched.wait(1)); started=time.monotonic(); cancel.set()
            with self.assertRaises(SpeechCancelled): pending.result(timeout=2)
            self.assertLess(time.monotonic()-started,1)
            self.assertIsNotNone(children[0].poll())

    def test_cancelling_generation_does_not_wait_for_model_timeout(self):
        script="import json,struct,sys,time; d=json.dumps(dict(ok=True,ready=True,engine='kokoro',network_attempts=0)).encode(); sys.stdout.buffer.write(struct.pack('<II',len(d),0)+d); sys.stdout.buffer.flush(); sys.stdin.buffer.read(4); time.sleep(20)"
        launch,children,_=self.launcher(script)
        cancel=threading.Event(); waiting=threading.Event()
        with patch('backend.neural_speech.subprocess.Popen',side_effect=launch):
            client=NeuralSpeech('kokoro'); self.addCleanup(client.close)
            original_get=client._get
            def wait(*args): waiting.set(); return original_get(*args)
            client._get=wait
            with ThreadPoolExecutor(1) as executor:
                pending=executor.submit(client.synthesize,'Synthetic test',cancel=cancel)
                self.assertTrue(waiting.wait(1)); started=time.monotonic(); cancel.set()
                with self.assertRaises(SpeechCancelled): pending.result(timeout=2)
                self.assertLess(time.monotonic()-started,1)
                self.assertIsNotNone(children[0].poll())

    @unittest.skipUnless(os.name=='nt','Windows speech adapter')
    def test_sapi_cancellation_also_closes_child(self):
        launch,children,launched=self.launcher('import sys,time; sys.stdin.buffer.read(); time.sleep(20)')
        cancel=threading.Event()
        with patch('backend.speech.subprocess.Popen',side_effect=launch), ThreadPoolExecutor(1) as executor:
            pending=executor.submit(synthesize,'Synthetic greeting',settings=EchoSettings(),cancel=cancel)
            self.assertTrue(launched.wait(1)); cancel.set()
            with self.assertRaises(SpeechCancelled): pending.result(timeout=2)
            self.assertIsNotNone(children[0].poll())


class ReplyRequestTests(unittest.TestCase):
    def test_cancel_aborts_only_the_reply_connection(self):
        entered=threading.Event(); aborted=threading.Event(); cancel=threading.Event()
        async def slow(request):
            entered.set()
            try: await asyncio.sleep(20)
            except asyncio.CancelledError: aborted.set(); raise
            return httpx.Response(200,json={'text':'late reply'})
        with ThreadPoolExecutor(1) as executor:
            pending=executor.submit(post_text,'Synthetic text','test-token',cancel=cancel,transport=httpx.MockTransport(slow))
            self.assertTrue(entered.wait(1)); cancel.set()
            with self.assertRaises(SpeechCancelled): pending.result(timeout=2)
        self.assertTrue(aborted.is_set())

    def test_request_uses_only_loopback_and_preserves_response(self):
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json={'status':'complete','text':'Synthetic reply'})
        result=post_text('Synthetic text','test-token',transport=httpx.MockTransport(handler))
        self.assertEqual(result.json()['text'],'Synthetic reply')
        self.assertEqual(str(calls[0].url),'http://127.0.0.1:8768/v1/text')
        self.assertEqual(json.loads(calls[0].content),{'text':'Synthetic text'})
        self.assertEqual(calls[0].headers['Authorization'],'Bearer test-token')
        post_text('Synthetic draft','test-token',transport=httpx.MockTransport(handler),calendar_review=True)
        self.assertEqual(json.loads(calls[-1].content),{'text':'Synthetic draft','calendar_review':True})


if __name__=='__main__': unittest.main()
