"""Match microphone readiness to this cue, instead of guessing when its sound ends."""
import secrets
import time


class Activation:
    def __init__(self, confirmed=False, clock=time.monotonic):
        self.confirmed, self.clock = confirmed, clock
        self.request = 0
        self.ready = False
        self.deadline = 0.

    def begin(self):
        self.request = secrets.randbelow(0xfffffffe)+1
        self.ready = False
        self.deadline = self.clock() + (2 if self.confirmed else .85)
        return f'WAKE {self.request}\n'.encode() if self.confirmed else b'WAKE\n'

    def receive(self, line):
        if self.confirmed and self.request and line == f'EVENT listening_ready={self.request}':
            self.ready = True

    def poll(self):
        if self.ready: return 'listening'
        if self.clock() >= self.deadline:
            return 'timeout' if self.confirmed else 'listening'
        return None
