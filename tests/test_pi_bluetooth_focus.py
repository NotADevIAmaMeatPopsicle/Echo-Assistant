"""Shared Pi focus/access checks with synthetic sinks; no media or hardware."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread, Event
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from spotify import Spotify, Unavailable
from bluetooth_session import BluetoothSession
from bluetooth_receiver import DEFAULT_CONFIG


class BluetoothFocusTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=100.
        self.music=Spotify(self.temp.name,clock=lambda:self.now,devices=lambda:[],popen=Mock(side_effect=AssertionError('No physical output')))

    def test_focus_and_idle_claim_wait_for_stop_outside_music_lock(self):
        seen=[]
        def stop(reason):
            acquired=Event()
            def read_focus():
                with self.music.lock:
                    self.assertTrue(self.music.held());acquired.set()
            thread=Thread(target=read_focus,daemon=True);thread.start();thread.join(.5)
            self.assertTrue(acquired.is_set(),'Receiver snapshot deadlocked on music lock')
            seen.append(reason);return True
        receiver=Mock();receiver.hard_stop.side_effect=stop;self.music.register_auxiliary(receiver)
        self.assertTrue(self.music.focus('a'*32,True)['paused_for_voice'])
        self.assertFalse(self.music.claim_idle('b'*32))
        self.music.focus('a'*32,False)
        self.assertTrue(self.music.claim_idle('b'*32));self.music.focus('b'*32,False)
        self.assertEqual(seen,['focus','focus'])

    def test_failed_stop_blocks_capture_and_never_resumes_other_output(self):
        receiver=Mock();receiver.hard_stop.return_value=False;self.music.register_auxiliary(receiver)
        with self.assertRaises(Unavailable):self.music.focus('a'*32,True)
        self.assertTrue(self.music.held());self.music.focus('a'*32,False)
        with self.assertRaises(Unavailable):self.music.claim_idle('b'*32)
        self.assertFalse(self.music.held())
        receiver.resume.assert_not_called()
        with self.assertRaises(Unavailable):self.music.stop_auxiliary('spotify')

    def test_duck_does_not_request_hard_stop_or_change_local_volume(self):
        receiver=Mock();self.music.register_auxiliary(receiver)
        self.music.duck('a'*32,True)
        self.assertAlmostEqual(self.music.output_level(44100),.4)
        self.assertEqual(self.music.config['volume'],2)
        self.music.duck('a'*32,False)
        self.assertEqual(self.music.output_level(44100),2)
        receiver.hard_stop.assert_not_called()

    def session(self,enabled):
        path=Path(self.temp.name)/'.config/echo-display/bluetooth.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({**DEFAULT_CONFIG,'enabled':enabled,'device_path':'/org/bluez/hci0/dev_00_11_22_33_44_55'}))
        path.chmod(0o600)
        request=Mock(return_value={'role':'display','receiver_id':'a'*32,'profile_revision':1,'profile':{'mode':'household'}})
        receiver=Mock();receiver.hard_stop.return_value=True;receiver.snapshot.return_value={'phase':'ready','output_active':False}
        session=BluetoothSession(request,self.music,self.temp.name,clock=lambda:self.now,receiver_factory=lambda *args:receiver)
        return session,request,receiver

    def test_disabled_session_has_no_host_or_output_side_effects(self):
        session,request,receiver=self.session(False)
        session.start();self.music.focus('a'*32,True)
        self.assertIsNone(session.thread);self.assertEqual(self.music.auxiliary_outputs,[])
        request.assert_not_called();receiver.start.assert_not_called();receiver.hard_stop.assert_not_called()

    def test_access_age_identity_and_personal_switch_fail_closed(self):
        session,request,receiver=self.session(True)
        self.assertFalse(session.focus_snapshot()['access_valid'])
        session.refresh_access();state=session.focus_snapshot();self.assertTrue(state['access_valid'])
        self.now+=1.01;self.assertFalse(session.focus_snapshot()['access_valid'])
        session.refresh_access();self.assertTrue(session.focus_snapshot()['access_valid'])
        request.return_value['profile_revision']=2;session.refresh_access()
        self.assertGreater(session.focus_snapshot()['generation'],state['generation'])
        request.return_value['member']={'id':'b'*32};session.refresh_access()
        self.assertFalse(session.focus_snapshot()['access_valid']);self.assertEqual(receiver.hard_stop.call_args.args,('access',))
        request.side_effect=OSError('Synthetic host outage');session.refresh_access()
        self.assertFalse(session.focus_snapshot()['access_valid'])

    def test_pending_spotify_and_music_configuration_are_visible(self):
        session,_,_=self.session(True);session.refresh_access()
        first=session.focus_snapshot();self.music.status='playing';self.music.silenced=False
        self.assertTrue(session.focus_snapshot()['spotify_active'])
        self.music.generation+=1
        self.assertGreater(session.focus_snapshot()['generation'],first['generation'])
        session.close();self.assertFalse(session.focus_snapshot()['access_valid'])


if __name__=='__main__':unittest.main()
