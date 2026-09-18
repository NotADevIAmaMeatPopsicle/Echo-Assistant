"""Explicitly apply a saved recognition engine using the existing local launcher."""
import os
from pathlib import Path
import subprocess
from threading import Lock, Thread
import time
from .lifecycle import request_stop
from .voice_status import voice_status


class SpeechRestart:
    def __init__(self, root):
        self.root = root
        self.lock = Lock()
        self.state = 'idle'

    def start(self):
        if not self.root or (os.name != 'nt' and os.environ.get('ECHO_CONTAINER') != '1'):
            raise ValueError('Bridge restart requires the local host or managed container')
        voice = voice_status(self.root)
        if voice.get('status') in {'activation', 'listening', 'thinking', 'speaking', 'music', 'alarm'} or voice.get('music', {}).get('status') == 'playing':
            raise ValueError('Wait until Echo and music are idle before applying recognition settings')
        if not self.lock.acquire(blocking=False): return {'status': 'restarting'}
        self.state = 'restarting'
        Thread(target=self._run, name='apply-speech-settings', daemon=True).start()
        return {'status': self.state}

    def _run(self):
        try:
            if os.name != 'nt':
                from .container_host import request_voice_restart
                previous = self.root/'local/voice-process.json'
                old = previous.read_text() if previous.exists() else None
                request_voice_restart(self.root)
                deadline = time.monotonic()+45
                while time.monotonic() < deadline:
                    if previous.exists() and previous.read_text() != old:
                        voice = voice_status(self.root)
                        if voice.get('status') not in {'disconnected','connecting'}:
                            self.state = 'ready'; return
                    time.sleep(.2)
                self.state = 'failed'; return
            request_stop(self.root, 'voice')
            deadline = time.monotonic()+35
            while (self.root/'local/voice-process.json').exists():
                if time.monotonic() >= deadline: raise RuntimeError('Bridge did not stop')
                time.sleep(.1)
            powershell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-File', str(self.root/'tools/run.ps1'), 'start'],
                cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=35,
                creationflags=subprocess.CREATE_NO_WINDOW)
            voice = voice_status(self.root)
            self.state = 'ready' if result.returncode == 0 and voice.get('status') not in {'disconnected', 'connecting'} else 'failed'
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired): self.state = 'failed'
        finally: self.lock.release()
