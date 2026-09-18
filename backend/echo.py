"""Bounded local echo-cancellation client, isolated from the transport and voice runtime."""
from pathlib import Path
import queue
import struct
import subprocess
import threading
from .runtime_paths import worker_python

ROOT = Path(__file__).resolve().parents[1]


class EchoCleaner:
    def __init__(self, root=ROOT):
        executable = worker_python(root,'aec')
        if not executable.exists(): raise RuntimeError('Local echo cancellation runtime missing')
        self.process = subprocess.Popen([str(executable), '-u', str(root/'backend/aec_worker.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.replies = queue.Queue(maxsize=2)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._read, name='local-echo-output', daemon=True)
        self.thread.start()
        try: self._exchange(b'', 5)
        except Exception:
            self.close(); raise

    def _read_exact(self, size):
        data = bytearray()
        while len(data) < size:
            part = self.process.stdout.read(size-len(data))
            if not part: return None
            data.extend(part)
        return bytes(data)

    def _read(self):
        try:
            while not self.stopped.is_set():
                header = self._read_exact(4)
                if header is None: break
                size, = struct.unpack('<I', header)
                if size not in {0, 320, 640}: break
                data = self._read_exact(size)
                if data is None: break
                self.replies.put(data, timeout=.2)
        except (OSError, ValueError, queue.Full): pass
        finally:
            try: self.replies.put_nowait(None)
            except queue.Full: pass

    def _exchange(self, payload, timeout=1):
        if self.process.poll() is not None: raise RuntimeError('Local echo worker stopped')
        try:
            packet = struct.pack('<I', len(payload))+payload
            if self.process.stdin.write(packet) != len(packet): raise RuntimeError('Echo pipe short write')
            result = self.replies.get(timeout=timeout)
        except (OSError, queue.Empty) as error:
            raise RuntimeError('Local echo processing unavailable') from error
        if result is None: raise RuntimeError('Local echo worker stopped')
        return result

    def reset(self): self._exchange(b'')

    def process_frame(self, microphone, reference):
        if len(microphone) != 512 or len(reference) != 512:
            raise ValueError('Echo cancellation requires paired 256-sample frames')
        return self._exchange(microphone+reference)

    def close(self):
        self.stopped.set()
        if self.process.poll() is None:
            self.process.stdin.close()
            try: self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=2)
        self.thread.join(timeout=1)
        self.process.stdout.close()
        if not self.process.stdin.closed: self.process.stdin.close()
        while True:
            try: self.replies.get_nowait()
            except queue.Empty: break
