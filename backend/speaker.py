"""Bounded credit-based PCM sender. The firmware owns the final gain limit."""
import re
import secrets
import time
from .cable import encode_pcm


class Speaker:
    def __init__(self, write, clock=time.monotonic):
        self.write, self.clock = write, clock
        self.pcm = b""
        self.session = self.sent = self.received = self.consumed = self.capacity = 0
        self.active = self.ended = False
        self.updated = 0.
        self.underruns = 0
        self.source = None
        self.kind = 'V'

    def start(self, pcm, kind='V'):
        if not pcm or len(pcm) % 2 or len(pcm) > 48000*2*90:
            raise ValueError("Invalid speaker PCM")
        if self.active: self.stop()
        self.pcm = pcm + b"\0" * (-len(pcm) % 512)
        self.source = None
        if kind not in {'V', 'A'}: raise ValueError('Invalid audio priority')
        self.kind = kind
        self._begin()

    def start_stream(self, source, kind='M'):
        if kind not in {'M','I'}: raise ValueError('Invalid streaming audio priority')
        if self.active: self.stop()
        self.pcm = b""
        self.source = source
        self.kind = kind
        self._begin()

    def _begin(self):
        self.session = secrets.randbelow(0xfffffffe)+1
        self.sent = self.received = self.consumed = self.capacity = self.underruns = 0
        self.active, self.ended = True, False
        self.updated = self.clock()
        self.write(f"AUDIO_BEGIN {self.session} {self.kind}\n".encode())

    def stop(self):
        self.write(b"AUDIO_STOP\n")
        self.pcm = b""; self.active = False; self.source = None

    def receive(self, line):
        if not self.active: return
        if line.startswith("ERROR audio_"):
            self.stop(); raise RuntimeError("Device rejected speaker audio: " + line[:120])
        if not line.startswith("EVENT audio_"): return
        fields = dict(re.findall(r"(\w+)=(\d+)", line))
        if int(fields.get("audio_ready", 0)) == self.session:
            capacity = int(fields.get("capacity", 0))
            if not 16 <= capacity <= 256: raise RuntimeError("Invalid speaker capacity")
            self.capacity = capacity
        elif int(fields.get("audio_session", 0)) == self.session:
            consumed = int(fields.get("consumed", 0))
            received = int(fields.get("received", 0))
            if not self.consumed <= consumed <= received <= self.sent or received < self.received:
                self.stop(); raise RuntimeError("Invalid speaker credits")
            self.consumed = consumed
            self.received = received
            self.underruns = int(fields.get("underruns", 0))
            if fields.get("active") == "0":
                complete = self.source is None and self.ended and consumed == len(self.pcm)//512
                self.active = False; self.pcm = b""
                if not complete: raise RuntimeError("Speaker playback was interrupted")
        else: return
        self.updated = self.clock()

    def pump(self):
        if not self.active: return
        if self.clock()-self.updated > 2:
            self.stop(); raise RuntimeError("Speaker connection timed out")
        total = len(self.pcm)//512
        # 128 blocks cover ~683 ms of Wi-Fi jitter. Stop and volume commands
        # remain immediate; the separate 96-frame transport credit still keeps
        # bursts inside the USB receive queue.
        capacity = min(self.capacity, 24 if self.kind=='I' else 128) if self.source else self.capacity
        # Audio-buffer credits alone allow a burst larger than the USB RX queue.
        # Also cap unacknowledged transport frames to fit the 64 KiB receive queue.
        batch = bytearray()
        count = 0
        for _ in range(min(16, 96-(self.sent-self.received), capacity-(self.sent-self.consumed), 16 if self.source else total-self.sent)):
            pcm = self.source() if self.source else self.pcm[(self.sent+count)*512:(self.sent+count+1)*512]
            if pcm is None: break
            if len(pcm) != 512: self.stop(); raise RuntimeError("Invalid streaming PCM block")
            batch.extend(encode_pcm(pcm, self.sent+count, kind=2))
            count += 1
        if batch:
            self.write(bytes(batch)); self.sent += count
        if not self.source and self.sent == total and not self.ended:
            self.write(b"AUDIO_END\n"); self.ended = True
