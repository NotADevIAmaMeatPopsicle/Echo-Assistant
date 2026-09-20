"""Timestamped 48 kHz mono transport for the Mini's negotiated group player.

No sockets, threads or sound devices are opened here. The owning bridge supplies
its existing authenticated wire and passes already-decoded Sendspin PCM.
"""
from collections import deque
import re
import secrets
import struct
from threading import RLock
import time
import zlib

from .cable import HEADER, MAGIC


def raw_clock():
    """Match Sendspin's hardware clock domain on Linux, without NTP slew."""
    if hasattr(time,'CLOCK_MONOTONIC_RAW'):
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)/1_000_000_000
    return time.monotonic_ns()/1_000_000_000


class DeviceClock:
    def __init__(self, clock=raw_clock):
        self.clock=clock;self.pending={};self.samples=deque(maxlen=12)
        self.next_probe=0.;self.offset=0;self.updated=0.;self.quality_us=None

    def probe(self):
        now=self.clock()
        if now<self.next_probe:return None
        self.next_probe=now+(.25 if len(self.samples)<3 else 1)
        self.pending={k:v for k,v in self.pending.items() if now-v<2}
        nonce=secrets.randbelow(0xfffffffe)+1
        self.pending[nonce]=now
        return f'GROUP_CLOCK {nonce}\n'.encode()

    def receive(self,line):
        match=re.fullmatch(r'EVENT group_clock=(\d+) device_us=(\d+)',line)
        if not match:return
        now=self.clock();nonce,device=map(int,match.groups());sent=self.pending.pop(nonce,None)
        if sent is None or not 0<device<10**16:return
        elapsed=(now-sent)*1_000_000
        if not 0<=elapsed<=20000:return
        self.samples.append((now,elapsed,device-round((sent+now)*500000)))
        recent=[v for v in self.samples if now-v[0]<10]
        if len(recent)<3:return
        best=min(recent,key=lambda v:v[1])
        self.quality_us=round(best[1]/2);self.offset=best[2];self.updated=now

    @property
    def ready(self):
        return self.quality_us is not None and self.clock()-self.updated<5

    def device_time(self,host_us):
        if not self.ready:raise RuntimeError('Mini presentation clock is not synchronized')
        return host_us+self.offset


def encode_timed(pcm,sequence,session,presentation_us):
    if len(pcm)!=512 or not 0<=sequence<=0xffffffff or not 1<=session<=0xffffffff or not 0<presentation_us<10**16:
        raise ValueError('Invalid timestamped audio frame')
    payload=struct.pack('<IQ',session,presentation_us)+pcm
    frame=HEADER.pack(MAGIC,4,len(payload),sequence)+payload
    return frame+struct.pack('<I',zlib.crc32(frame))


class TimedSpeaker:
    """Single wire owner with bounded in-memory PCM and independent audio credits."""
    def __init__(self,write,*,clock=raw_clock,ceiling=2,latency_us=0):
        if type(ceiling) is not int or not 0<=ceiling<=20:raise ValueError('Invalid Mini output ceiling')
        if type(latency_us) is not int or not -200000<=latency_us<=200000:raise ValueError('Invalid Mini latency calibration')
        self.write,self.clock=write,clock;self.device_clock=DeviceClock(clock);self.lock=RLock()
        self.ceiling=self.gain=ceiling;self.latency_us=latency_us
        self.capable=False;self.allowed=False;self.queue=deque(maxlen=384)
        self.partial=b'';self.partial_tick=0;self.expected_at=None
        self.session=0;self.capacity=self.sent=self.received=self.consumed=0
        self.updated=0.;self.dropped=0;self.late=self.missing=0

    @property
    def active(self):return bool(self.session)

    def clear(self):
        self.queue.clear();self.partial=b'';self.expected_at=None

    def stop(self):
        with self.lock:
            if self.session:self.write(f'GROUP_STOP {self.session}\n'.encode())
            self.session=0;self.capacity=self.sent=self.received=self.consumed=0;self.clear()

    def focus(self,allowed):
        with self.lock:
            self.allowed=bool(allowed and self.capable)
            if not self.allowed:self.stop()

    def volume(self,value):
        with self.lock:
            if type(value) is not int or not 0<=value<=100:raise ValueError('Invalid group volume')
            self.gain=min(value,self.ceiling)
            if self.session:self.write(f'GROUP_GAIN {self.session} {self.gain}\n'.encode())

    def receive(self,line):
        with self.lock:
            if line.startswith('STATUS '):
                self.capable=bool(re.search(r'\btimed_audio=1\b',line))
                if not self.capable:self.focus(False)
            self.device_clock.receive(line)
            if not self.session:return
            if line.startswith(('ERROR group_','ERROR audio_')):
                self.stop();raise RuntimeError('Mini rejected timestamped audio')
            fields=dict(re.findall(r'(\w+)=(\d+)',line))
            if line.startswith('EVENT group_ready=') and int(fields.get('group_ready',0))==self.session:
                capacity=int(fields.get('capacity',0))
                if not 16<=capacity<=256:self.stop();raise RuntimeError('Invalid Mini group capacity')
                self.capacity=capacity;self.updated=self.clock()
                self.write(f'GROUP_GAIN {self.session} {self.gain}\n'.encode())
            elif line.startswith('EVENT group_session=') and int(fields.get('group_session',0))==self.session:
                received=int(fields.get('received',0));consumed=int(fields.get('consumed',0))
                if not self.received<=received<=self.sent or not self.consumed<=consumed<=received or fields.get('active')!='1':
                    self.stop();raise RuntimeError('Mini group playback stopped or returned invalid credits')
                self.received,self.consumed=received,consumed;self.updated=self.clock()
                self.late=int(fields.get('late',0));self.missing=int(fields.get('missing',0))

    def append(self,pcm,presentation_us):
        with self.lock:
            if not self.allowed or not self.device_clock.ready:return
            if not isinstance(pcm,bytes) or not pcm or len(pcm)%2 or len(pcm)>192000 or type(presentation_us) is not int:
                raise ValueError('Invalid decoded group audio')
            now=round(self.clock()*1_000_000)
            if not now-2000000<=presentation_us<=now+2000000:raise ValueError('Group audio is outside the clock window')
            if self.expected_at is not None and abs(presentation_us-self.expected_at)>100:
                self.partial=b''  # A discontinuity must not splice separate chunks.
            start_tick=self.partial_tick if self.partial else presentation_us*48000
            raw=self.partial+pcm;count=len(raw)//512
            for index in range(count):
                if len(self.queue)==self.queue.maxlen:self.dropped+=1
                self.queue.append(((start_tick+index*256*1_000_000+24000)//48000,raw[index*512:(index+1)*512]))
            self.partial=raw[count*512:];self.partial_tick=start_tick+count*256*1_000_000
            self.expected_at=presentation_us+round(len(pcm)//2*1_000_000/48000)

    def pump(self):
        with self.lock:
            if not self.capable:return
            probe=self.device_clock.probe()
            if probe:self.write(probe)
            if not self.allowed or not self.device_clock.ready:
                self.stop();return
            now=self.clock();cutoff=round(now*1_000_000)+70000+self.latency_us
            while self.queue and self.queue[0][0]<cutoff:
                self.queue.popleft();self.dropped+=1
            if not self.session:
                if not self.queue:return
                self.session=secrets.randbelow(0xfffffffe)+1;self.updated=now
                self.write(f'GROUP_BEGIN {self.session} {self.ceiling}\n'.encode())
                return
            if now-self.updated>2:self.stop();raise RuntimeError('Mini group connection timed out')
            count=min(16,96-(self.sent-self.received),min(self.capacity,192)-(self.sent-self.consumed),len(self.queue))
            batch=bytearray()
            for _ in range(max(0,count)):
                at,pcm=self.queue.popleft();device=self.device_clock.device_time(at-self.latency_us)
                batch.extend(encode_timed(pcm,self.sent,self.session,device));self.sent+=1
            if batch:self.write(bytes(batch))

    def health(self):
        with self.lock:
            return {'capable':self.capable,'clock_synchronized':self.device_clock.ready,
                    'clock_uncertainty_us':self.device_clock.quality_us,'active':self.active,
                    'queued_blocks':len(self.queue),'sent':self.sent,'consumed':self.consumed,
                    'dropped':self.dropped,'late_blocks':self.late,'missing_samples':self.missing,
                    'output_ceiling':self.ceiling,'volume':self.gain}
