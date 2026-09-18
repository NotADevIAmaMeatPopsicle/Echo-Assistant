"""Bounded, resident speech worker client; neural dependencies stay out of the bridge."""
import atexit
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import threading
import time
from contextlib import contextmanager
from .tts_catalog import DEFAULT_VOICES
from .speech_jobs import check_cancel
from .runtime_paths import worker_python, tts_environment

ROOT = Path(__file__).resolve().parents[1]
MAX_PCM = 48000*2*90


class NeuralSpeech:
    def __init__(self, engine, root=ROOT, *, cancel=None):
        if engine not in {'kokoro','pocket'}: raise ValueError('Unsupported speech engine')
        check_cancel(cancel)
        self.engine = engine
        environment = {k:v for k,v in os.environ.items() if k.upper() in {
            'SYSTEMROOT','WINDIR','PATH','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','COMSPEC','PATHEXT'}}
        environment.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
                           DO_NOT_TRACK='1',PYTHONNOUSERSITE='1',TOKENIZERS_PARALLELISM='false')
        environment.update(tts_environment())
        self.process = subprocess.Popen([str(worker_python(root,'tts')),'-u','-m','backend.tts_worker',engine],
            cwd=root,env=environment,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.replies = queue.Queue(maxsize=2)
        self.thread = threading.Thread(target=self._read,name='local-tts-output',daemon=True); self.thread.start()
        try:
            metadata,_ = self._get(60,cancel)
            if not metadata.get('ready'): raise RuntimeError('Local speech worker failed to initialize')
        except Exception:
            self.close(); raise

    def _read(self):
        def exact(size):
            value = bytearray()
            while len(value)<size:
                part = self.process.stdout.read(size-len(value))
                if not part: raise EOFError()
                value.extend(part)
            return value
        try:
            while True:
                metadata_size,pcm_size = struct.unpack('<II',exact(8))
                if not 1<=metadata_size<=4096 or pcm_size>MAX_PCM or pcm_size%2: break
                metadata = json.loads(exact(metadata_size)); pcm = bytes(exact(pcm_size))
                self.replies.put((metadata,pcm),timeout=.2)
        except (OSError,EOFError,ValueError,queue.Full): pass
        finally:
            try: self.replies.put_nowait(None)
            except queue.Full: pass

    def _get(self, timeout, cancel=None):
        deadline = time.monotonic()+timeout
        while True:
            check_cancel(cancel)
            remaining = deadline-time.monotonic()
            if remaining<=0: raise RuntimeError('Local speech generation timed out')
            try:
                result = self.replies.get(timeout=min(.05,remaining))
                check_cancel(cancel)
                break
            except queue.Empty: pass
        if result is None: raise RuntimeError('Local speech worker stopped')
        metadata,pcm = result
        if not isinstance(metadata,dict) or metadata.get('ok') is not True or metadata.get('engine')!=self.engine:
            raise RuntimeError('Local '+self.engine+' speech unavailable')
        if metadata.get('network_attempts',0): raise RuntimeError('Speech worker attempted a blocked network request')
        return metadata,pcm

    def synthesize(self,text,voice='',rate=0, *, cancel=None):
        if not isinstance(text,str) or not 1<=len(text.strip())<=1200: raise ValueError('Invalid spoken text')
        request = json.dumps({'text':text,'voice':voice or DEFAULT_VOICES[self.engine],'rate':rate}).encode('utf-8')
        packet = memoryview(struct.pack('<I',len(request))+request)
        try:
            check_cancel(cancel)
            while packet:
                written = self.process.stdin.write(packet)
                if not written: raise OSError()
                packet = packet[written:]
            metadata,pcm = self._get(60,cancel)
            if not pcm or len(pcm)>MAX_PCM or len(pcm)%2 or metadata.get('sample_rate')!=48000:
                raise RuntimeError('Invalid speech PCM')
            return pcm,metadata
        except (RuntimeError,OSError): self.close(); raise

    def close(self):
        if self.process.poll() is None:
            self.process.kill(); self.process.wait(timeout=3)
        self.thread.join(timeout=1)
        for stream in (self.process.stdin,self.process.stdout):
            if not stream.closed: stream.close()


_lock = threading.Lock()
_worker = None


@contextmanager
def ownership(cancel=None):
    while not _lock.acquire(timeout=.05): check_cancel(cancel)
    try:
        check_cancel(cancel)
        yield
    finally: _lock.release()


def ensure_worker(settings, cancel=None):
    """Called only while holding ownership; loading is cancellable too."""
    global _worker
    if _worker is None or _worker.engine!=settings.tts_engine or _worker.process.poll() is not None:
        if _worker: _worker.close()
        _worker = None
        _worker = NeuralSpeech(settings.tts_engine,cancel=cancel)
        return True
    return False


def prepare(settings, *, cancel=None):
    with ownership(cancel):
        ensure_worker(settings,cancel)
        return {'engine':settings.tts_engine,'status':'ready'}


def synthesize(text, settings, *, cancel=None):
    with ownership(cancel):
        started = time.monotonic()
        loaded = ensure_worker(settings,cancel)
        load_ms = round((time.monotonic()-started)*1000) if loaded else 0
        pcm, metrics = _worker.synthesize(text,settings.tts_voice,settings.tts_rate,cancel=cancel)
        return pcm, {**metrics,'load_ms':load_ms,'request_ms':round((time.monotonic()-started)*1000)}


def close():
    global _worker
    with _lock:
        if _worker: _worker.close(); _worker=None


atexit.register(close)
