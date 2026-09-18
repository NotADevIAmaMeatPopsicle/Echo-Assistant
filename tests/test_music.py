import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import threading
import time
from unittest.mock import Mock, patch
from backend.music import Music


class MusicTests(unittest.TestCase):
    def event(self, *kinds):
        socket=Mock()
        socket.recvfrom.side_effect=[(json.dumps({'key':self.music.key,'event':kind}).encode(),None) for kind in kinds]+[BlockingIOError()]
        self.music.socket=socket; self.music.poll()

    def assert_audio_delivered(self):
        before=self.music.nonzero_frames
        self.music._read_audio(Mock(stdout=io.BytesIO(b'\x01\x01\x01\x01'*4410)))
        self.assertGreater(self.music.nonzero_frames,before)

    def test_pausing_an_idle_receiver_does_not_silence_future_phone_playback(self):
        for state in ('connected','paused','stopped'):
            with self.subTest(state=state):
                self.music=Music(Path(self.directory.name))
                self.music.process=Mock(stdin=io.BytesIO()); self.music.process.poll.return_value=None
                self.music.status=state
                self.music.command('pause')
                # Native pause can be ignored when already idle, so no pause event
                # is promised before the phone's next explicit Play.
                self.event('playing')
                self.assert_audio_delivered()

    def test_pause_during_transfer_is_applied_once_activation_finishes(self):
        self.music.process=Mock(stdin=io.BytesIO()); self.music.process.poll.return_value=None
        self.music.status='connected'
        self.music.command('play'); self.music.command('pause')
        before=self.music.process.stdin.getvalue().count(b'pause\n')
        self.event('session_connected','playing')
        self.assertGreater(self.music.process.stdin.getvalue().count(b'pause\n'),before)
        self.event('paused','playing')
        self.assert_audio_delivered()

    def test_new_session_does_not_inherit_an_old_pending_pause(self):
        self.music.pause_pending=self.music.discard_pcm=True
        self.event('session_disconnected','session_connected','playing')
        self.assert_audio_delivered()

    def test_explicit_play_transfers_cached_session_and_resumes_paused_track(self):
        process = Mock(stdin=io.BytesIO()); process.poll.return_value = None
        self.music.process = process; self.music.status = 'connected'
        self.music.command('toggle')
        self.assertEqual(process.stdin.getvalue(), b'transfer\n')
        socket = Mock()
        socket.recvfrom.side_effect = [(json.dumps({'key':self.music.key,'event':'session_connected'}).encode(), None),
            (json.dumps({'key':self.music.key,'event':'paused'}).encode(), None), BlockingIOError()]
        self.music.socket = socket; self.music.poll()
        self.assertEqual(process.stdin.getvalue(), b'transfer\nplay\n')
        self.assertFalse(self.music.play_after_transfer)

    def test_pause_unblocks_full_audio_pipe_before_receiver_acknowledges(self):
        process = Mock(stdout=io.BytesIO(b'\x01\x01\x01\x01'*44100), stdin=io.BytesIO())
        process.poll.return_value = None
        self.music.process = process; self.music.status = 'playing'
        thread = threading.Thread(target=self.music._read_audio, args=(process,), daemon=True)
        thread.start()
        until = time.monotonic()+2
        while not self.music.pcm.full() and time.monotonic()<until: time.sleep(.005)
        self.assertTrue(self.music.pcm.full())
        self.assertTrue(self.music.command('pause'))
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive(), 'Pause left the receiver pipe blocked')
        self.assertEqual(self.music.status, 'playing', 'Do not fabricate a pause acknowledgement')
        self.assertTrue(self.music.discard_pcm)
        socket = Mock()
        socket.recvfrom.side_effect = [(json.dumps({'key':self.music.key, 'event':'paused'}).encode(), None),
            (json.dumps({'key':self.music.key, 'event':'playing'}).encode(), None), BlockingIOError()]
        self.music.socket = socket; self.music.poll()
        self.assertFalse(self.music.discard_pcm, 'Phone resume must restore PCM consumption')

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.music = Music(Path(self.directory.name))

    def test_dead_receiver_clears_pcm_and_retries_with_backoff(self):
        process = Mock()
        process.poll.return_value = 1
        process.stdin = io.BytesIO(); process.stdout = io.BytesIO(); process.stderr = io.BytesIO()
        self.music.process = process
        self.music.pcm.put(b'\0'*512)
        with patch('backend.music.time.monotonic', return_value=100): self.music.poll()
        self.assertEqual(self.music.status, 'unavailable')
        self.assertTrue(self.music.pcm.empty())
        self.assertEqual(self.music.next_restart, 105)
        with patch.object(self.music, 'start', side_effect=OSError('not available')) as start:
            with patch('backend.music.time.monotonic', return_value=104): self.music.poll()
            start.assert_not_called()
            with patch('backend.music.time.monotonic', return_value=105): self.music.poll()
            start.assert_called_once()
        self.assertEqual(self.music.next_restart, 115)
        self.assertEqual(self.music.restart_count, 1)

    def test_explicit_close_cancels_recovery(self):
        self.music.next_restart = 1
        self.music.close()
        with patch.object(self.music, 'start') as start:
            self.music.poll(); start.assert_not_called()

    def test_untrusted_event_cannot_change_playback_or_metadata(self):
        socket = Mock()
        socket.recvfrom.side_effect = [(json.dumps({'key':'wrong', 'event':'playing'}).encode(), None), BlockingIOError()]
        self.music.socket = socket
        self.music.poll()
        self.assertEqual(self.music.status, 'not_configured')

    def test_session_loss_clears_metadata_and_audio(self):
        self.music.title = 'Fixture'
        self.music.pcm.put(b'\0'*512)
        socket = Mock()
        socket.recvfrom.side_effect = [(json.dumps({'key':self.music.key, 'event':'session_disconnected'}).encode(), None), BlockingIOError()]
        self.music.socket = socket
        self.music.poll()
        self.assertTrue(self.music.pcm.empty())
        self.assertEqual(self.music.title, '')
        self.assertEqual(self.music.status, 'discoverable')

    def test_pipe_downmix_avoids_integer_overflow(self):
        import numpy as np
        samples = np.full((4410, 2), 20000, dtype='<i2')
        process = Mock(stdout=io.BytesIO(samples.tobytes()))
        self.music.status = 'playing'
        self.music._read_audio(process)
        output = []
        while (block := self.music.read()) is not None:
            self.assertEqual(len(block), 512)
            output.append(block)
        self.assertTrue(output)
        converted = np.frombuffer(b''.join(output), dtype='<i2')
        self.assertGreater(np.median(converted), 19000)
        self.assertEqual(self.music.errors, 0)
        self.assertGreater(self.music.health()['nonzero_frames'], 0)
        self.assertEqual(self.music.health()['pcm_bytes'], len(samples.tobytes()))

    def test_receiver_diagnostics_never_keep_raw_log_content(self):
        private = b'WARN On event program secret-account failed to start: private-path\n'
        self.music._drain_errors(Mock(stderr=io.BytesIO(private)))
        health = self.music.health()
        self.assertEqual(health['last_diagnostic'], 'event_hook_failed')
        self.assertEqual(health['warnings'], 1)
        self.assertNotIn('secret-account', json.dumps(health))
        self.assertNotIn('private-path', json.dumps(health))

    def test_error_categories_are_fixed_and_do_not_contain_remote_details(self):
        private=b'ERROR could not dispatch player event: secret-id https://private.example/token\n'
        self.music._drain_errors(Mock(stderr=io.BytesIO(private)))
        health=self.music.health()
        self.assertEqual(health['error_categories'],{'player_event':1})
        self.assertNotIn('secret-id',json.dumps(health))
        self.assertNotIn('private.example',json.dumps(health))


if __name__ == '__main__': unittest.main()
