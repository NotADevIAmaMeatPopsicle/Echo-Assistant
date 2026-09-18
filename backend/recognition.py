"""Bounded, in-memory recognition worker; never block the device transport on STT."""
import json
import queue
import threading
import time
from .wake import EchoDetector
from .music_voice import music_intent


def accepted_command(result):
    text = result.get('text', '').strip()
    words = result.get('result', [])
    confidence = [word.get('conf', 0) for word in words]
    if not text or not confidence or any(type(value) not in (float, int) or not 0 <= value <= 1 for value in confidence):
        return None
    if min(confidence) >= .8: return text
    # Vosk confuses "pause" with "Paul's" even in a clear synthesized phrase.
    # Exact music pause/stop is reversible and only silences playback. Keep the
    # strict threshold for play, home actions, timers and all other commands.
    if music_intent(text) == 'pause' and min(confidence) >= .5 and sum(confidence)/len(confidence) >= .8:
        return text
    return None


class Recognition:
    def __init__(self, model=None, *, detector=None, command=None, echo=None):
        if command is None:
            from vosk import KaldiRecognizer
            command = KaldiRecognizer(model, 16000)
            command.SetWords(True)
        self.detector = detector if detector is not None else EchoDetector(model)
        self.command = command
        self.echo = echo
        self.echo_failed = False
        self.echo_frames = self.echo_errors = 0
        self.input = queue.Queue(maxsize=32)
        self.output = queue.Queue(maxsize=4)
        self.mode = None
        self.epoch = 0
        self.dropped = self.errors = self.high_water = 0
        self.command_endpoints = self.command_accepted = self.command_rejected = 0
        self.listening_frames = 0
        self.max_feed_ms = 0.
        self.stopped = threading.Event()
        self.decoding = threading.Event()
        self.thread = threading.Thread(target=self._run, name='local-recognition', daemon=True)
        self.thread.start()

    @staticmethod
    def _clear(items):
        while True:
            try: items.get_nowait()
            except queue.Empty: return

    def reset(self):
        self.epoch += 1
        self._clear(self.input)
        self._clear(self.output)

    def set_mode(self, mode):
        if mode not in {None, 'armed', 'armed_music', 'listening'}: raise ValueError('Invalid recognition mode')
        if mode != self.mode:
            self.mode = mode
            self.reset()

    def submit(self, pcm, reference=None):
        if self.mode is None or self.stopped.is_set() or self.decoding.is_set(): return
        try:
            self.input.put_nowait((self.epoch, self.mode, pcm, reference))
            self.high_water = max(self.high_water, self.input.qsize())
        except queue.Full:
            self.dropped += 1
            # Do not join noncontiguous speech or act on an old queued command.
            self.reset()

    def poll(self):
        events = []
        while True:
            try: epoch, event = self.output.get_nowait()
            except queue.Empty: return events
            if epoch == self.epoch: events.append(event)

    def _run(self):
        active_epoch = -1
        latched = False
        while not self.stopped.is_set():
            try: epoch, mode, pcm, reference = self.input.get(timeout=.1)
            except queue.Empty: continue
            if epoch != self.epoch: continue
            try:
                if epoch != active_epoch:
                    self.detector.reset(); self.command.Reset()
                    if mode == 'armed_music' and self.echo_ready:
                        self.echo.reset()
                    active_epoch = epoch; latched = False
                if latched: continue
                started = time.monotonic()
                event = None
                if mode == 'listening': self.listening_frames += 1
                if mode == 'armed_music':
                    # Never recognize raw speaker echo when cancellation is
                    # unavailable or a transition still has legacy mic frames.
                    if not self.echo_ready or reference is None: continue
                    pcm = self.echo.process_frame(pcm, reference)
                    self.echo_frames += 1
                    if not pcm: continue
                if mode in {'armed', 'armed_music'}:
                    phrase = self.detector.feed(pcm)
                    if phrase: event = {'kind': 'wake', 'value': phrase}
                elif self.command.AcceptWaveform(pcm):
                    self.command_endpoints += 1
                    if hasattr(self.command, 'decode'):
                        self.decoding.set()
                        self._clear(self.input)
                        try: text = self.command.decode()
                        finally: self.decoding.clear()
                    else:
                        result = json.loads(self.command.Result())
                        text = accepted_command(result)
                    if text:
                        self.command_accepted += 1
                        event = {'kind': 'command', 'value': text}
                    else: self.command_rejected += 1
                self.max_feed_ms = max(self.max_feed_ms, (time.monotonic()-started)*1000)
                if event and epoch == self.epoch and not self.stopped.is_set():
                    self.output.put_nowait((epoch, event)); latched = True
            except Exception:
                # No exception text, recognizer result, or audio is persisted.
                if mode == 'armed_music':
                    self.echo_errors += 1
                    self.echo_failed = True
                    if self.echo:
                        try: self.echo.close()
                        except (OSError, RuntimeError): pass
                else:
                    self.errors += 1
                active_epoch = -1

    @property
    def echo_ready(self):
        return self.echo is not None and not self.echo_failed

    def health(self):
        return {'queue': self.input.qsize(), 'high_water': self.high_water,
                'dropped': self.dropped, 'errors': self.errors,
                'listening_frames': self.listening_frames, 'command_endpoints': self.command_endpoints,
                'command_accepted': self.command_accepted, 'command_rejected': self.command_rejected,
                'max_feed_ms': round(self.max_feed_ms, 1), 'alive': self.thread.is_alive(), 'decoding': self.decoding.is_set(),
                'echo': 'ready' if self.echo_ready else 'failed' if self.echo_failed else 'unavailable',
                'echo_frames': self.echo_frames, 'echo_errors': self.echo_errors}

    def close(self):
        self.stopped.set(); self.set_mode(None); self.reset()
        self.thread.join(timeout=2)
        if hasattr(self.command, 'close'): self.command.close()
        if self.thread.is_alive(): self.thread.join(timeout=2)
        if self.echo and not self.echo_failed: self.echo.close()
