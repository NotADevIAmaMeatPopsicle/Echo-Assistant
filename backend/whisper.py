"""Whisper command transcription behind the existing Vosk end-of-utterance detector."""
import json
from pathlib import Path
import queue
import struct
import subprocess
import threading
from .transcription import accepted_transcription


class WhisperClient:
    def __init__(self, root: Path):
        executable = root/'local/stt-python/Scripts/python.exe'
        if not executable.is_file() or not (root/'local/models/faster-whisper-base.en/model.bin').is_file():
            raise RuntimeError('Selected local Whisper runtime is missing')
        self.process = subprocess.Popen([str(executable), '-u', str(root/'backend/whisper_worker.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.replies = queue.Queue(maxsize=2)
        self.thread = threading.Thread(target=self._read, name='whisper-output', daemon=True)
        self.thread.start()
        try:
            if self.replies.get(timeout=25) != {'ready': True}: raise RuntimeError('Local Whisper failed to load')
        except (queue.Empty, RuntimeError):
            self.close(); raise RuntimeError('Local Whisper failed to load') from None

    def _read(self):
        def exact(size):
            data = bytearray()
            while len(data) < size:
                part = self.process.stdout.read(size-len(data))
                if not part: raise EOFError()
                data.extend(part)
            return data
        try:
            while True:
                size, = struct.unpack('<I', exact(4))
                if not 1 <= size <= 20000: break
                self.replies.put(json.loads(exact(size)), timeout=.2)
        except (OSError, EOFError, ValueError, queue.Full): pass
        finally:
            try: self.replies.put_nowait(None)
            except queue.Full: pass

    def transcribe(self, pcm):
        if not 0 < len(pcm) <= 16000*2*8 or len(pcm) % 2: return None
        if self.process.poll() is not None: raise RuntimeError('Local Whisper worker stopped')
        try:
            packet = struct.pack('<I', len(pcm))+pcm
            view = memoryview(packet)
            while view:
                written = self.process.stdin.write(view)
                if not written: raise OSError()
                view = view[written:]
            response = self.replies.get(timeout=12)
            if not isinstance(response, dict): raise RuntimeError('Local Whisper worker stopped')
            return accepted_transcription(response.get('segments'))
        except (OSError, queue.Empty):
            self.close()
            raise RuntimeError('Local Whisper transcription unavailable') from None

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=3)
        self.thread.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            if not stream.closed: stream.close()


class WhisperCommand:
    def __init__(self, endpoint, client):
        self.endpoint, self.client = endpoint, client
        self.Reset()

    def Reset(self):
        self.endpoint.Reset()
        self.pcm = bytearray()
        self.overflow = False

    def AcceptWaveform(self, pcm):
        if len(self.pcm)+len(pcm) > 16000*2*8:
            self.overflow = True; self.pcm.clear()
        if not self.overflow: self.pcm.extend(pcm)
        return self.endpoint.AcceptWaveform(pcm)

    def decode(self):
        try: return self.client.transcribe(bytes(self.pcm)) if not self.overflow else None
        finally: self.Reset()

    def close(self):
        self.pcm.clear(); self.client.close()
