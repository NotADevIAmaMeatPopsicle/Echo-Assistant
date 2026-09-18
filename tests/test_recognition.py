import json
import threading
import time
import unittest
from backend.recognition import Recognition, accepted_command
from backend.voice import activate, recognition_mode


class Detector:
    def __init__(self, phrase=None, blocked=False):
        self.phrase = phrase
        self.entered = threading.Event()
        self.release = threading.Event()
        if not blocked: self.release.set()

    def reset(self): pass

    def feed(self, pcm):
        phrase = self.phrase
        self.entered.set()
        if not self.release.wait(3): raise RuntimeError('Test detector timed out')
        return phrase


class Command:
    def __init__(self, confidence=1, blocked=False):
        self.confidence = confidence
        self.entered = threading.Event()
        self.release = threading.Event()
        if not blocked: self.release.set()

    def Reset(self): pass

    def AcceptWaveform(self, pcm):
        self.entered.set()
        if not self.release.wait(3): raise RuntimeError('Test command timed out')
        return True

    def Result(self):
        return json.dumps({'text': 'what time is it', 'result': [{'conf': self.confidence}]})


class Echo:
    def __init__(self, fail=False):
        self.fail = fail
        self.frames = []; self.closed = False
    def reset(self): pass
    def process_frame(self, mic, ref):
        if self.fail: raise RuntimeError('Test worker unavailable')
        self.frames.append((mic, ref)); return b'cleaned'
    def close(self): self.closed = True


class RecognitionTests(unittest.TestCase):
    def test_music_pause_tolerates_one_uncertain_word_without_weakening_home_controls(self):
        def result(text, confidences): return {'text':text,'result':[{'conf':value} for value in confidences]}
        self.assertEqual(accepted_command(result('pause the music', [.54,1,1])), 'pause the music')
        for text, confidences in [('pause the music', [.4,1,1]), ('pause the music', [.6,.6,.6]),
                                  ('play the music', [.54,1,1]), ('set thermostat to off', [.54,1,1,1]),
                                  ('pause the soundbar', [.54,1,1]), ('pause the music', [float('nan'),1,1])]:
            self.assertIsNone(accepted_command(result(text, confidences)))

    def make_worker(self, detector=None, command=None):
        worker = Recognition(detector=detector or Detector(), command=command or Command())
        self.addCleanup(worker.close)
        self.addCleanup(worker.detector.release.set)
        self.addCleanup(worker.command.release.set)
        return worker

    def result(self, worker):
        until = time.monotonic()+2
        while time.monotonic() < until:
            events = worker.poll()
            if events: return events
            time.sleep(.005)
        self.fail('Recognition result did not arrive')

    def test_stalled_recognizer_does_not_block_transport_and_overflow_invalidates_speech(self):
        detector = Detector('hey echo', blocked=True)
        worker = self.make_worker(detector)
        worker.set_mode('armed'); worker.submit(b'first')
        self.assertTrue(detector.entered.wait(1))
        # All calls return while recognition remains blocked. No PCM can grow
        # without bound, and overflow invalidates the pending wake result.
        for _ in range(33): worker.submit(b'queued')
        self.assertEqual(worker.health()['dropped'], 1)
        self.assertEqual(worker.health()['queue'], 0)
        self.assertEqual(worker.health()['high_water'], 32)
        detector.release.set()
        worker.close()
        self.assertEqual(worker.poll(), [])
        self.assertFalse(worker.health()['alive'])

    def test_mute_discards_inflight_wake_and_unmute_can_detect_again(self):
        detector = Detector('hey echo', blocked=True)
        worker = self.make_worker(detector)
        worker.set_mode('armed'); worker.submit(b'old')
        self.assertTrue(detector.entered.wait(1))
        worker.set_mode(None); detector.phrase = 'okay echo'; detector.release.set()
        worker.set_mode('armed'); worker.submit(b'new')
        self.assertEqual(self.result(worker), [{'kind': 'wake', 'value': 'okay echo'}])
        worker.submit(b'duplicate')
        worker.close()
        self.assertEqual(worker.poll(), [])

    def test_cancel_discards_inflight_command(self):
        command = Command(blocked=True)
        detector = Detector('hey echo')
        worker = self.make_worker(detector, command)
        worker.set_mode('listening'); worker.submit(b'cancelled')
        self.assertTrue(command.entered.wait(1))
        worker.set_mode('armed'); command.release.set(); worker.submit(b'wake')
        self.assertEqual(self.result(worker), [{'kind': 'wake', 'value': 'hey echo'}])

    def test_confident_command_only_and_phase_change_resets_latch(self):
        command = Command(.3)
        worker = self.make_worker(Detector('hey echo'), command)
        worker.set_mode('listening'); worker.submit(b'uncertain')
        self.assertTrue(command.entered.wait(1))
        worker.set_mode('armed'); worker.submit(b'wake')
        self.assertEqual(self.result(worker), [{'kind': 'wake', 'value': 'hey echo'}])
        command.confidence = 1
        worker.set_mode('listening'); worker.submit(b'certain')
        self.assertEqual(self.result(worker), [{'kind': 'command', 'value': 'what time is it'}])

    def test_close_clears_audio_and_disabled_mode_rejects_it(self):
        worker = self.make_worker()
        worker.submit(b'ignored')
        self.assertEqual(worker.health()['queue'], 0)
        worker.close(); worker.set_mode('armed'); worker.submit(b'ignored')
        self.assertEqual(worker.health()['queue'], 0)
        self.assertFalse(worker.health()['alive'])

    def test_health_distinguishes_rejected_speech_without_retaining_text(self):
        command = Command(.3)
        worker = self.make_worker(command=command)
        worker.set_mode('listening'); worker.submit(b'private-audio')
        until = time.monotonic()+1
        while not worker.health()['command_rejected'] and time.monotonic()<until:
            time.sleep(.005)
        health = worker.health()
        self.assertEqual(health['listening_frames'], 1)
        self.assertEqual(health['command_endpoints'], 1)
        self.assertEqual(health['command_rejected'], 1)
        self.assertEqual(health['command_accepted'], 0)
        self.assertEqual(worker.poll(), [])
        self.assertNotIn('what time', json.dumps(health))
        self.assertNotIn('private-audio', json.dumps(health))
        command.confidence=1; worker.submit(b'accepted-audio')
        self.assertEqual(self.result(worker), [{'kind':'command','value':'what time is it'}])
        self.assertEqual(worker.health()['command_accepted'], 1)

    def test_music_requires_echo_reference_and_mute_invalidates_wake(self):
        detector = Detector('hey echo', blocked=True); echo = Echo()
        worker = self.make_worker(detector); worker.echo = echo
        worker.set_mode('armed_music'); worker.submit(b'raw')
        worker.submit(b'mic', b'reference')
        self.assertTrue(detector.entered.wait(1))
        self.assertEqual(echo.frames, [(b'mic', b'reference')])
        worker.set_mode(None); detector.release.set(); worker.close()
        self.assertEqual(worker.poll(), [])
        self.assertTrue(echo.closed)

    def test_failed_echo_keeps_idle_recognition_usable(self):
        worker = self.make_worker(Detector('okay echo')); worker.echo = Echo(fail=True)
        worker.set_mode('armed_music'); worker.submit(b'mic', b'ref')
        until = time.monotonic()+1
        while worker.echo_ready and time.monotonic() < until: time.sleep(.005)
        self.assertEqual(worker.health()['echo'], 'failed')
        self.assertTrue(worker.echo.closed)
        self.assertEqual(worker.health()['echo_errors'], 1)
        self.assertEqual(recognition_mode('music', False, worker.echo_ready), None)
        worker.set_mode('armed'); worker.submit(b'voice')
        self.assertEqual(self.result(worker), [{'kind':'wake', 'value':'okay echo'}])

    def test_wake_pauses_and_stops_music_before_dong_and_requires_unmuted_echo(self):
        events = []
        class Port:
            def write(self, data): events.append(data)
        class Speaker:
            active = True
            def stop(self): events.append('speaker_stop')
        class Music:
            def command(self, action): events.append(action)
            def clear(self): events.append('clear')
        self.assertTrue(activate(Port(), Speaker(), Music(), 'music'))
        self.assertEqual(events, ['pause', 'clear', 'speaker_stop', b'WAKE\n'])
        self.assertEqual(recognition_mode('music', False, True), 'armed_music')
        self.assertIsNone(recognition_mode('music', True, True))
        self.assertIsNone(recognition_mode('music', False, False))
        self.assertEqual(recognition_mode('armed', False, False), 'armed')


if __name__ == '__main__': unittest.main()
