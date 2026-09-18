import unittest
from backend.speaker import Speaker


class SpeakerTests(unittest.TestCase):
    def test_backpressure_completion_and_padding(self):
        writes = []
        speaker = Speaker(writes.append)
        speaker.start(b'\0\0' * (256*300-3))
        session = speaker.session
        speaker.pump()
        self.assertEqual(speaker.sent, 0)
        speaker.receive(f'EVENT audio_ready={session} capacity=256')
        for _ in range(50):
            speaker.pump()
            speaker.receive(f'EVENT audio_session={session} received={speaker.sent} consumed=0 active=1 underruns=0')
        self.assertEqual(speaker.sent, 256)
        self.assertFalse(speaker.ended)
        speaker.receive(f'EVENT audio_session={session} received=256 consumed=128 active=1 underruns=0')
        for _ in range(10):
            speaker.pump()
            speaker.receive(f'EVENT audio_session={session} received={speaker.sent} consumed=128 active=1 underruns=0')
        self.assertEqual(speaker.sent, 300)
        self.assertTrue(speaker.ended)
        self.assertEqual(writes[-1], b'AUDIO_END\n')
        speaker.receive(f'EVENT audio_session={session} received=300 consumed=300 active=0 underruns=0')
        self.assertFalse(speaker.active)
        self.assertEqual(speaker.pcm, b'')

    def test_wrong_session_cannot_grant_credits(self):
        speaker = Speaker(lambda _: None)
        speaker.start(b'\0'*1024)
        speaker.receive(f'EVENT audio_ready={speaker.session+1} capacity=256')
        speaker.pump()
        self.assertEqual(speaker.sent, 0)

    def test_usb_receive_window_is_smaller_than_audio_buffer(self):
        speaker = Speaker(lambda _: None)
        speaker.start(b'\0'*512*300)
        speaker.receive(f'EVENT audio_ready={speaker.session} capacity=256')
        for _ in range(50): speaker.pump()
        self.assertEqual(speaker.sent, 96)

    def test_timeout_stops_and_erases_pending_audio(self):
        now = [0.]
        writes = []
        speaker = Speaker(writes.append, lambda: now[0])
        speaker.start(b'\0'*512)
        now[0] = 3
        with self.assertRaises(RuntimeError): speaker.pump()
        self.assertFalse(speaker.active)
        self.assertEqual(speaker.pcm, b'')
        self.assertEqual(writes[-1], b'AUDIO_STOP\n')

    def test_invalid_credits_and_early_end_fail_closed(self):
        for fields in ('received=10 consumed=10 active=1', 'received=0 consumed=0 active=0'):
            speaker = Speaker(lambda _: None)
            speaker.start(b'\0'*512)
            with self.assertRaises(RuntimeError):
                speaker.receive(f'EVENT audio_session={speaker.session} {fields} underruns=0')
            self.assertFalse(speaker.active)


if __name__ == '__main__': unittest.main()
