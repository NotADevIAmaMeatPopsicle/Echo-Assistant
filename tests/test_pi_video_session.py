"""Video grants, focus and lease integration with no browser or audio processes."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from spotify import Spotify, Unavailable
from video_session import VideoSession


class Receiver:
    def __init__(self, home, focus):
        self.focus=focus;self.state={'active':False,'phase':'idle','error':None}
        self.stops=[];self.confirm=True;self.pulses=[]
    def snapshot(self):return dict(self.state)
    def check(self):return {'available':True,'error':None}
    def start(self, lease, video):
        focus=self.focus()
        if not focus['access_valid'] or focus['held'] or focus['spotify_active']:return False
        self.state.update(active=True,lease_id=lease,video_id=video,phase='playing')
        return True
    def heartbeat(self, lease):
        self.pulses.append(lease)
        return self.state['active'] and self.state.get('lease_id')==lease
    def hard_stop(self, reason):
        self.stops.append(reason)
        if self.confirm:self.state.update(active=False,phase='stopped')
        return self.confirm
    def close(self):return self.hard_stop('shutdown')


class VideoSessionTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.now=100.
        self.music=Spotify(temporary.name,clock=lambda:self.now,devices=lambda:[],
                           popen=Mock(side_effect=AssertionError('No audio processes')))
        self.selected={'provider':'youtube','available':True,'reason':'allowed',
                       'revision':4,'profile_revision':2,'video_id':'abcdefghijk'}
        self.request=Mock(side_effect=lambda *a,**k:dict(self.selected))
        self.group=Mock();self.group.playback_active.return_value=False
        self.screen=Mock()
        self.video=VideoSession(self.request,self.music,self.group,self.screen,temporary.name,
                               clock=lambda:self.now,receiver_factory=Receiver)
        self.addCleanup(self.video.close)

    def test_owner_preview_guest_and_disabled_never_launch(self):
        for reason in ['owner_preview','guest_not_allowed','personal_not_allowed','disabled']:
            self.selected['reason']=reason
            with self.assertRaises(Unavailable):self.video.launch(4)
            self.assertFalse(self.video.active())
            self.assertFalse(self.video.snapshot()['available'])

    def test_launch_pauses_spotify_then_requires_fresh_selection(self):
        self.music.status='playing';self.music.silenced=False
        self.assertEqual(self.video.launch(4),{'accepted':True})
        self.assertTrue(self.music.silenced)
        self.assertTrue(self.video.active())
        self.assertIn('focus',self.video.receiver.stops)
        state=self.video.receiver.snapshot()
        self.assertRegex(state['lease_id'],r'^[a-f0-9]{32}$')
        self.assertNotIn('lease_id',self.video.snapshot())
        self.assertNotIn('video_id',self.video.snapshot())

    def test_stale_revision_and_group_focus_leave_music_alone(self):
        self.music.silenced=False
        with self.assertRaises(Unavailable):self.video.launch(3)
        self.group.playback_active.return_value=True
        with self.assertRaises(Unavailable):self.video.launch(4)
        self.assertFalse(self.music.silenced)
        self.assertFalse(self.video.active())

    def test_pulse_keeps_screen_awake_and_old_lease_cannot_stop_new_player(self):
        self.video.launch(4);old=self.video.receiver.snapshot()['lease_id']
        response=self.video.pulse(old,'pulse')
        self.assertEqual(response['video_id'],'abcdefghijk')
        self.screen.wake.assert_called()
        self.video.end();self.video.launch(4)
        with self.assertRaises(Unavailable):self.video.pulse(old,'stop')
        self.assertTrue(self.video.active())

    def test_revocation_and_selection_changes_invalidate_active_player(self):
        self.video.launch(4);lease=self.video.receiver.snapshot()['lease_id']
        self.selected['profile_revision']=3
        self.video.refresh_access()
        self.assertFalse(self.video.active())
        with self.assertRaises(Unavailable):self.video.pulse(lease,'pulse')
        self.video.launch(4)
        self.request.side_effect=OSError('synthetic disconnect')
        self.video.refresh_access()
        self.assertFalse(self.video.focus_snapshot()['access_valid'])
        self.assertFalse(self.video.active())

    def test_focus_snapshot_expires_without_new_host_evidence(self):
        self.video.refresh_access();before=self.video.focus_snapshot()
        self.assertTrue(before['access_valid'])
        self.now+=1.01
        self.assertFalse(self.video.focus_snapshot()['access_valid'])
        self.video.refresh_access();self.music.generation+=1
        self.assertGreater(self.video.focus_snapshot()['generation'],before['generation'])
        self.music.duck('d'*32,True)
        self.assertTrue(self.video.focus_snapshot()['ducked'])

    def test_unconfirmed_video_stop_blocks_microphone_focus(self):
        self.video.launch(4);self.video.receiver.confirm=False
        with self.assertRaises(Unavailable):self.music.focus('f'*32,True)
        self.assertTrue(self.music.held())
        with self.assertRaises(Unavailable):self.video.end()
        self.video.receiver.confirm=True

    def test_old_access_response_cannot_restore_replaced_selection(self):
        entered,release=Event(),Event()
        old=dict(self.selected)
        def request(*args,**kwargs):
            if not entered.is_set():
                entered.set();release.wait(2);return old
            return dict(self.selected)
        self.request.side_effect=request
        thread=Thread(target=self.video.refresh_access,daemon=True);thread.start()
        self.assertTrue(entered.wait(1))
        self.selected['video_id']='ABCDEFGHIJK';self.selected['revision']=5
        self.video.refresh_access();release.set();thread.join(1)
        self.assertEqual(self.video.access,(5,2,'ABCDEFGHIJK'))

    def test_slow_native_start_keeps_access_fresh_without_waiting_on_snapshot(self):
        entered,refreshed=Event(),Event()
        original=self.video.receiver.start
        def request(*args,**kwargs):
            if entered.is_set():refreshed.set()
            return dict(self.selected)
        def start(lease,video):
            entered.set()
            self.assertTrue(refreshed.wait(1.5),'Startup blocked its own permission refresh')
            return original(lease,video)
        self.request.side_effect=request
        self.video.receiver.start=start
        self.video.start()
        self.assertEqual(self.video.launch(4),{'accepted':True})


if __name__=='__main__':unittest.main()
