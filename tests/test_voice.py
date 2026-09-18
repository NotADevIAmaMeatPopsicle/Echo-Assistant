import json
from pathlib import Path
import random
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from backend.cable import Decoder, encode_pcm
from backend.wake import match_wake
from backend.voice_status import voice_status
from backend.voice import write_status, waiting_for_board


class CableTests(unittest.TestCase):
    def test_waiting_listener_keeps_fresh_health_and_pauses_music_once(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root/'local').mkdir()
            music = Mock(status='playing', pause_pending=False)
            music.health.return_value = {'status': 'playing', 'pcm_frames': 20}
            def pause(command):
                self.assertEqual(command, 'pause')
                music.pause_pending = True
            music.command.side_effect = pause
            state = {'status': 'connecting', 'transport': 'wifi', 'engine': 'vosk-local',
                     'last_disconnect_reason': 'microphone_timeout'}
            with patch('backend.voice.ROOT', root), patch('backend.voice.time.time', return_value=100):
                waiting_for_board(state, music)
                self.assertEqual(voice_status(root, 101)['status'], 'connecting')
            with patch('backend.voice.ROOT', root), patch('backend.voice.time.time', return_value=110):
                waiting_for_board(state, music)
                observed = voice_status(root, 111)
                self.assertEqual(observed['last_disconnect_reason'], 'microphone_timeout')
                self.assertEqual(observed['engine'], 'vosk-local')
                self.assertNotIn('device', observed)
            music.command.assert_called_once_with('pause')
            self.assertEqual(music.poll.call_count, 2)
            self.assertEqual(music.clear.call_count, 2)
            self.assertEqual(voice_status(root, 116)['status'], 'disconnected')

    def test_windows_health_reader_does_not_disconnect_voice(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root/'local').mkdir()
            with patch('backend.voice.ROOT', root), patch.object(Path, 'replace', side_effect=PermissionError):
                with patch('backend.voice.time.sleep'):
                    self.assertFalse(write_status({'status': 'armed'}))

    def test_fragmented_frames_and_interleaved_status(self):
        decoder = Decoder()
        pcm = struct.pack('<256h', *range(256))
        data = b'STATUS product=round-voice\n'+encode_pcm(pcm, 0)+b'NETWORK disconnects=0 reason=0\nUSB partial=0\nUI weather=1 timers=1\nRENDER state=listening last_us=32000 max_us=33000 frames=20\n'+encode_pcm(pcm, 1)+b'EVENT cancelled=1\n'
        packets, lines = [], []
        for i in range(0, len(data), 7):
            p, l = decoder.feed(data[i:i+7]); packets.extend(p); lines.extend(l)
        self.assertEqual(packets, [pcm, pcm])
        self.assertEqual(len(lines), 6)
        self.assertIn('UI weather=1 timers=1', lines)
        self.assertIn('RENDER state=listening last_us=32000 max_us=33000 frames=20', lines)
        self.assertIn('NETWORK disconnects=0 reason=0', lines)
        self.assertEqual((decoder.errors, decoder.gaps), (0, 0))

    def test_corruption_resync_gap_and_sequence_wrap(self):
        decoder = Decoder()
        bad = bytearray(encode_pcm(b'\0'*512, 1)); bad[-1] ^= 1
        pcm = b'\1\0'*256
        p, _ = decoder.feed(encode_pcm(pcm, 0)+bad+encode_pcm(pcm, 2))
        self.assertEqual(p, [pcm, pcm]); self.assertEqual(decoder.errors, 1)
        self.assertEqual(decoder.checksum_errors, 1)
        self.assertEqual(decoder.gaps, 1)
        decoder = Decoder(); decoder.feed(encode_pcm(pcm, 0xffffffff))
        decoder.feed(encode_pcm(pcm, 0)); self.assertEqual(decoder.gaps, 0)

    def test_noise_stays_bounded_and_recovers(self):
        decoder = Decoder()
        for _ in range(50): decoder.feed(b'garbage'*500)
        self.assertLessEqual(len(decoder.buffer), 2048)
        self.assertEqual(decoder.feed(encode_pcm(b'\0\0', 1))[0], [b'\0\0'])


class WakeTests(unittest.TestCase):
    def test_corrupt_health_cannot_break_status_or_claim_connection(self):
        bad = [[], None, 'armed', {}, {'status':['armed'], 'updated_at':100},
               {'status':'ready', 'updated_at':100}, {'status':'armed', 'updated_at':float('nan')},
               {'status':'armed', 'updated_at':'100'}, {'status':'armed', 'updated_at':True},
               {'status':'armed', 'updated_at':100, 'music':[]},
               {'status':'armed', 'updated_at':100, 'transport':{}},
               {'status':'armed', 'updated_at':10**400}]
        for value in bad:
            with self.subTest(value=value), patch.object(Path, 'read_text', return_value=json.dumps(value)):
                self.assertEqual(voice_status(Path('unused'), 102)['status'], 'disconnected')

    @staticmethod
    def result(text, conf=1):
        return {'text': text, 'result': [{'word': w, 'conf': conf} for w in text.split()]}

    def test_both_complete_phrases(self):
        for phrase in ('hey echo', 'okay echo'):
            self.assertEqual(match_wake(self.result(phrase)), phrase)

    def test_incomplete_unrelated_low_confidence_rejected(self):
        for phrase in ('echo', 'hey', 'okay', 'hey jarvis', 'okay echo chamber', 'say hey echo'):
            self.assertIsNone(match_wake(self.result(phrase)))
        self.assertIsNone(match_wake(self.result('hey echo', .7)))
        self.assertIsNone(match_wake({'text': 'hey echo'}))

    def test_stale_bridge_is_disconnected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root/'local').mkdir()
            path = root/'local/voice-status.json'
            path.write_text(json.dumps({'status':'armed','updated_at':100,'phrases':['hey echo']}))
            self.assertEqual(voice_status(root, 102)['status'], 'armed')
            self.assertEqual(voice_status(root, 106)['status'], 'disconnected')

    def test_status_published_during_read_is_not_a_false_disconnect(self):
        with patch('backend.voice_status.time.time', return_value=100) as clock:
            def read_snapshot(*args, **kwargs):
                clock.return_value = 101
                return json.dumps({'status': 'armed', 'updated_at': 100.5})
            with patch.object(Path, 'read_text', side_effect=read_snapshot):
                self.assertEqual(voice_status(Path('unused'))['status'], 'armed')


if __name__ == '__main__': unittest.main()
