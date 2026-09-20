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
from listener import Detector, Listener, Segment, validate
from backend.conversation_activity import Conversations, ConversationBusy


class Music:
    def __init__(self):self.lock=RLock();self.holds={};self.ducks={}
    def held(self):return bool(self.holds)
    def focus(self,client,busy):
        if busy:self.holds[client]=True
        else:self.holds.pop(client,None)
    def duck(self,client,busy):
        if busy:self.ducks[client]=True
        else:self.ducks.pop(client,None)


class PiListenerTests(unittest.TestCase):
    def test_account_switch_after_capture_discards_reply_before_playback(self):
        with TemporaryDirectory() as directory:
            paths=[];played=[]
            def request(path,*args):
                paths.append(path)
                if path=='/v1/display/voice':return {'available':True,'access_revision':42}
                return {'status':'complete','text':'Old personal reply','access_revision':41,'audio':{'data':'never decode'}}
            listener=Listener(request,Music(),directory);listener.access_revision=41
            listener.config.update(enabled=True,muted=False,input='mic',output='speaker')
            listener.host_ready=True;listener.last_host=time.monotonic()
            class FakeDetector:
                def reset(self):pass
                def feed(self,pcm):return False
            listener.detector=FakeDetector();voice=array('h',[1000,-1000]*640).tobytes()
            def frames():
                for _ in range(5):yield voice
                while True:yield b'\0'*2560
            listener.frames=frames();listener.play=lambda *args,**kwargs:played.append(listener.phase)
            with self.assertRaises(InterruptedError):listener.command(dict(listener.config))
            self.assertIn('&access_revision=41',paths[0]);self.assertEqual(played,['cue']);self.assertIsNone(listener.result)

    def test_diagnostics_are_bounded_measurements_without_recordings(self):
        with TemporaryDirectory() as directory:
            listener=Listener(lambda *args:None,Music(),directory)
            listener.measure(array('h',[1000,-1000]*640).tobytes())
            for i in range(40):listener.note('capture_finished',voiced_ms=i,transcript='not retained')
            d=listener.diagnostics()
            self.assertEqual(len(d['events']),32);self.assertEqual(d['frames'],1)
            self.assertAlmostEqual(d['level_dbfs'],-30.3,places=1)
            self.assertFalse(d['audio_saved']);self.assertNotIn('not retained',json.dumps(d))
            with patch('listener.time.monotonic',return_value=time.monotonic()+901):
                self.assertEqual(listener.diagnostics()['events'],[])
                self.assertIsNone(listener.diagnostics()['level_dbfs'])
            listener.control('clear_diagnostics');self.assertEqual(listener.diagnostics()['events'],[])

    def test_music_duck_and_legacy_pause_do_not_claim_echo_cancellation(self):
        with TemporaryDirectory() as directory:
            music=Music();listener=Listener(lambda *args:None,music,directory)
            legacy={k:v for k,v in listener.config.items() if k!='music_mode'}
            self.assertEqual(validate(legacy)['music_mode'],'pause')
            config={**listener.config,'music_mode':'duck'}
            self.assertFalse(validate(config)['echo_cancelled_input'])
            listener.audio_focus(config,True)
            self.assertTrue(music.ducks);self.assertFalse(music.holds)
            listener.audio_focus(config,False)
            self.assertFalse(music.ducks);self.assertFalse(music.holds)
            with self.assertRaises(ValueError):validate({**config,'music_mode':'loud'})

    def test_music_no_longer_blocks_wake_without_aec(self):
        with TemporaryDirectory() as directory:
            music=Music();music.snapshot=lambda:{'status':'playing'}
            class Wake:
                def reset(self):pass
                def feed(self,pcm):return True
            listener=Listener(lambda *args:None,music,directory,captures=lambda:[{'id':'mic'}],speakers=lambda:[{'id':'out'}],detector_factory=lambda path:Wake())
            listener.config.update(enabled=True,muted=False,input='mic',output='out')
            listener.host_ready=True;listener.last_host=time.monotonic()
            listener.microphone=lambda config:(frame for frame in [b'\0'*2560])
            activated=[]
            def command(config):activated.append(True);listener.stop.set()
            listener.command=command
            listener.run()
            self.assertEqual(activated,[True])

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

    def test_stable_partial_wake_does_not_wait_for_music_to_fall_silent(self):
        class Recognizer:
            value={'partial':'hey echo','partial_result':[{'word':'hey','conf':.95},{'word':'echo','conf':.95}]}
            def AcceptWaveform(self,pcm):return False
            def PartialResult(self):return json.dumps(self.value)
            def Reset(self):pass
        detector=Detector.__new__(Detector);detector.recognizer=Recognizer();detector.reset()
        self.assertFalse(detector.feed(b''));self.assertTrue(detector.feed(b''))
        detector.reset();detector.recognizer.value={'partial':'hey','partial_result':[{'word':'hey','conf':1.}]}
        self.assertFalse(detector.feed(b''));self.assertFalse(detector.feed(b''))

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
