from array import array
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, RLock, Thread
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from listener import Detector, Listener, Segment
from backend.conversation_activity import Conversations, ConversationBusy


class Music:
    def __init__(self):self.lock=RLock();self.holds={}
    def held(self):return bool(self.holds)
    def focus(self,client,busy):
        if busy:self.holds[client]=True
        else:self.holds.pop(client,None)


class PiListenerTests(unittest.TestCase):
    def test_exact_wake_and_confidence(self):
        detector=Detector.__new__(Detector)
        class Recognizer:
            value={}
            def AcceptWaveform(self,pcm):return True
            def Result(self):return json.dumps(self.value)
        detector.recognizer=Recognizer()
        for phrase,confidence,expected in [('hey echo',.92,True),('okay echo',.99,True),('hey echo',.4,False),('echo',.99,False),('hey echo turn on lights',.99,False)]:
            detector.recognizer.value={'text':phrase,'result':[{'word':word,'conf':confidence} for word in phrase.split()]}
            self.assertEqual(detector.feed(b''),expected)

    def test_bounded_capture_silence_and_trailing_pause(self):
        quiet=b'\0'*2560;voice=array('h',[1000,-1000]*640).tobytes()
        silent=Segment()
        for _ in range(100):done=silent.feed(quiet)
        self.assertTrue(done);self.assertEqual(silent.result(),b'')
        spoken=Segment()
        for _ in range(5):self.assertFalse(spoken.feed(voice))
        for _ in range(11):self.assertFalse(spoken.feed(quiet))
        self.assertTrue(spoken.feed(quiet));self.assertGreater(len(spoken.result()),3200)
        long=Segment()
        for _ in range(100):done=long.feed(voice)
        self.assertTrue(done);self.assertLessEqual(len(long.result()),256000)

    def test_stop_before_upload_and_old_stop_do_not_affect_new_conversation(self):
        jobs=Conversations();jobs.stop_capture('display-a','1'*32)
        with self.assertRaises(ConversationBusy):jobs.begin('display-a',capture_id='1'*32)
        current=jobs.begin('display-a',capture_id='2'*32)
        jobs.stop_capture('display-a','1'*32);self.assertFalse(current.cancel.is_set())
        jobs.stop_capture('display-b','2'*32);self.assertFalse(current.cancel.is_set())
        jobs.stop_capture('display-a','2'*32);self.assertTrue(current.cancel.is_set())

    def test_muted_config_restart_and_no_process_by_default(self):
        with TemporaryDirectory() as directory:
            started=[]
            listener=Listener(lambda *args:None,Music(),directory,captures=lambda:[{'id':'mic'}],speakers=lambda:[{'id':'speaker'}],popen=lambda *args,**kw:started.append(args))
            self.assertFalse(listener.config['enabled']);self.assertTrue(listener.config['muted']);self.assertEqual(started,[])
            with patch.object(listener,'ready',return_value=True):
                listener.configure({**listener.config,'enabled':True,'input':'mic','output':'speaker'})
                self.assertTrue(listener.config['muted']);listener.control('unmute');listener.control('mute')
            restored=Listener(lambda *args:None,Music(),directory)
            self.assertTrue(restored.config['muted']);self.assertEqual(restored.config['volume'],2)
            listener.path.write_text('broken')
            self.assertTrue(Listener(lambda *args:None,Music(),directory).config_error)
            self.assertEqual(listener.path.read_text(),'broken');self.assertEqual(started,[])

    def test_stop_during_reply_request_closes_inputs_and_discards_delayed_audio(self):
        with TemporaryDirectory() as directory:
            waiting=Event();cancelled=Event();played=[];failures=[]
            def request(path,*args):
                if path.endswith('/stop'):cancelled.set();return {'cancel_requested':True}
                waiting.set();cancelled.wait(2)
                return {'status':'complete','text':'Stale response','audio':{'data':'must never decode'}}
            listener=Listener(request,Music(),directory);listener.config.update(enabled=True,muted=False,input='mic',output='speaker')
            listener.host_ready=True;listener.last_host=time.monotonic()
            class FakeDetector:
                def reset(self):pass
                def feed(self,pcm):return False
            listener.detector=FakeDetector()
            quiet=b'\0'*2560;voice=array('h',[1000,-1000]*640).tobytes()
            def frames():
                for _ in range(5):yield voice
                while True:
                    listener.check(listener.config);time.sleep(.001);yield quiet
            listener.frames=frames();listener.play=lambda *args,**kwargs:played.append(listener.phase)
            def run():
                try:listener.command(dict(listener.config))
                except InterruptedError:failures.append('stopped')
            thread=Thread(target=run);thread.start();self.assertTrue(waiting.wait(2))
            listener.interrupt();thread.join(3)
            self.assertFalse(thread.is_alive());self.assertTrue(cancelled.is_set());self.assertEqual(failures,['stopped'])
            self.assertEqual(played,['cue']);self.assertIsNone(listener.result)


if __name__=='__main__':unittest.main()
