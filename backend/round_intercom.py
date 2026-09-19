"""Answered round-speaker calls. PCM stays in bounded memory, outside speech recognition."""
from collections import deque
import hashlib
import json
import queue
import re
import struct
import threading
import time

from .echo import EchoCleaner


class CallAudio:
    """One call's duplex pipes. No source is opened until local consent is recorded."""
    def __init__(self,client,identifier,cleaner,clock=time.monotonic):
        self.client,self.identifier,self.cleaner,self.clock=client,identifier,cleaner,clock
        self.lock=threading.RLock();self.stop=threading.Event();self.failed=False
        self.muted=True;self.generation=0;self.input=queue.Queue(6)
        self.output=deque(maxlen=24);self.partial=b'';self.last_sample=0
        self.sequence=0;self.threads=[];self.last_input=self.clock()

    def start(self):
        for target in (self.upload,self.download):
            thread=threading.Thread(target=target,daemon=True,name='round-call-audio')
            self.threads.append(thread);thread.start()

    def request(self,method,path,**kwargs):
        r=self.client.request(method,path,headers={'X-Echo-Audio-Receiver':'round',**kwargs.pop('headers',{})},timeout=3,**kwargs)
        r.raise_for_status();return r

    def mute(self,value):
        with self.lock:
            if self.muted==value:return
            self.muted=value;self.generation+=1
            self.last_input=self.clock()
            while not self.input.empty():
                try:self.input.get_nowait()
                except queue.Empty:break

    def feed(self,pcm,reference):
        with self.lock:
            if self.muted or self.stop.is_set() or reference is None:return
            if len(pcm)!=512 or len(reference)!=512:return
            self.last_input=self.clock()
            try:self.input.put_nowait((self.generation,self.clock(),pcm,reference))
            except queue.Full:
                # Drop a discontinuous segment instead of joining old speech.
                self.generation+=1
                while not self.input.empty():
                    try:self.input.get_nowait()
                    except queue.Empty:break

    def upload(self):
        generation=-1;pending=bytearray()
        try:
            while not self.stop.is_set():
                try:epoch,at,pcm,reference=self.input.get(timeout=.1)
                except queue.Empty:continue
                if epoch!=self.generation or self.clock()-at>.25:pending.clear();continue
                if epoch!=generation:
                    self.cleaner.reset();pending.clear();generation=epoch
                cleaned=self.cleaner.process_frame(pcm,reference)
                with self.lock:
                    if self.muted or epoch!=self.generation or self.stop.is_set():pending.clear();continue
                pending.extend(cleaned)
                if len(pending)<3200:continue
                packet=bytes(pending[:3200]);del pending[:3200]
                self.request('POST',f'/v1/intercom/calls/{self.identifier}/audio?client=round&sequence={self.sequence}',
                             content=packet,headers={'Content-Type':'application/octet-stream'})
                self.sequence+=1
        except Exception:
            if not self.stop.is_set():self.failed=True
            self.stop.set()
        finally:self.cleaner.close()

    def append(self,pcm):
        # Linear interpolation to the existing 48 kHz board transport.
        samples=struct.unpack('<'+'h'*(len(pcm)//2),pcm);out=[]
        for sample in samples:
            previous=self.last_sample
            out.extend((round((2*previous+sample)/3),round((previous+2*sample)/3),sample));self.last_sample=sample
        raw=self.partial+struct.pack('<'+'h'*len(out),*out)
        with self.lock:
            if self.stop.is_set():return
            for at in range(0,len(raw)-511,512):self.output.append((self.clock(),raw[at:at+512]))
            self.partial=raw[len(raw)//512*512:]

    def download(self):
        pending=bytearray();last=-1
        try:
            with self.client.stream('GET',f'/v1/intercom/calls/{self.identifier}/audio?client=round&keepalive=true',
                                    headers={'X-Echo-Audio-Receiver':'round'},timeout=3) as response:
                response.raise_for_status()
                for part in response.iter_bytes():
                    if self.stop.is_set():return
                    pending.extend(part)
                    if len(pending)>200000:raise ValueError('Call buffer exceeded')
                    while len(pending)>=8:
                        sequence,size=struct.unpack('<II',pending[:8])
                        if size==0:del pending[:8];continue
                        if not 640<=size<=6400 or size%2:raise ValueError('Invalid call frame')
                        if len(pending)<size+8:break
                        pcm=bytes(pending[8:8+size]);del pending[:8+size]
                        if sequence<=last:continue
                        if last>=0 and sequence!=last+1:
                            with self.lock:self.output.clear();self.partial=b'';self.last_sample=0
                        last=sequence;self.append(pcm)
                if not self.stop.is_set():self.failed=True
        except Exception:
            if not self.stop.is_set():self.failed=True
        finally:self.stop.set()

    def read(self):
        with self.lock:
            while self.output:
                at,pcm=self.output.popleft()
                if self.clock()-at<.3:return pcm
        return b'\0'*512 if not self.stop.is_set() else None

    def close(self):
        self.stop.set();self.mute(True)
        with self.lock:self.output.clear();self.partial=b''
        # Socket reads have a 3s timeout and 1s server keepalives. Do not block
        # the board heartbeat waiting for a broken network.


class RoundIntercom:
    def __init__(self,client,write,*,cleaner_factory=EchoCleaner,clock=time.monotonic):
        self.client,self.write,self.cleaner_factory,self.clock=client,write,cleaner_factory,clock
        self.lock=threading.RLock();self.actions=queue.Queue(8);self.stopped=threading.Event()
        self.enabled=False;self.capable=False;self.muted=True;self.other_busy=True
        self.state={};self.at=0.;self.binding='0'*16;self.rooms=[];self.consent=None
        self.audio=None;self.capture=None;self.skip_batch=False;self.notice='Calls off';self.last_ui=0.
        self.cleaner=None;self.preparing=False
        self.thread=threading.Thread(target=self.run,daemon=True,name='round-call-control');self.thread.start()

    def request(self,method,path,body):
        r=self.client.request(method,path,headers={'X-Echo-Audio-Receiver':'round'},json=body,timeout=3)
        r.raise_for_status();return r.json()

    @property
    def call(self):return self.state.get('call') or {}

    @property
    def busy(self):
        return self.consent is not None or self.call.get('status') in {'ringing','active'}

    @property
    def active(self):
        return bool(self.audio and not self.audio.stop.is_set() and self.call.get('status')=='active'
                    and self.call.get('id')==self.consent and self.clock()-self.at<4)

    def enqueue(self,action):
        try:self.actions.put_nowait(action)
        except queue.Full:self.disable('Too many requests')

    def disable(self,notice='Calls off'):
        self.enabled=False;self.consent=None;self.capture=None;self.notice=notice
        if self.audio:self.audio.close()

    def receive(self,line):
        if line=='EVENT intercom_enabled=1':self.enabled=self.capable;return True
        if line=='EVENT intercom_enabled=0':self.disable();return True
        match=re.fullmatch(r'EVENT intercom_call=(\d+) binding=([a-f0-9]{16}) id=([a-f0-9]{32})',line)
        if match:
            index=int(match[1])
            with self.lock:
                if self.enabled and not self.busy and match[2]==self.binding and index<len(self.rooms) and self.rooms[index]['ready'] and self.state.get('ready'):
                    self.consent=match[3];self.enqueue(('start',self.consent,self.rooms[index]['id'],self.state['revision']))
            return True
        match=re.fullmatch(r'EVENT intercom_action=(answer|hangup|mute|unmute) id=([a-f0-9]{32})',line)
        if match:
            action,identifier=match.groups()
            if action=='hangup' and identifier in {self.consent,self.call.get('id')}:
                self.consent=None;self.capture=None
                audio=self.audio
                if audio:audio.close()
                self.enqueue((action,identifier))
            elif identifier==self.call.get('id'):
                if action=='answer' and self.enabled and self.call.get('direction')=='incoming' and self.call.get('status')=='ringing':self.consent=identifier;self.enqueue((action,identifier))
                elif action in {'mute','unmute'} and self.active:
                    self.capture=None
                    audio=self.audio
                    if action=='mute' and audio:audio.mute(True)
                    self.enqueue((action,identifier))
            return True
        match=re.fullmatch(r'EVENT intercom_capture=([a-f0-9]{32})',line)
        if match:
            if self.active and match[1]==self.consent:self.capture=match[1];self.skip_batch=True
            return True
        return False

    def feed(self,packets,references):
        if self.skip_batch:self.skip_batch=False;return
        audio=self.audio
        if audio and self.active and self.capture==self.consent:
            for pcm,reference in zip(packets,references):audio.feed(pcm,reference)

    def read(self):
        audio=self.audio
        return audio.read() if audio and self.active else None

    def action(self,item):
        action,identifier,*extra=item
        path=f'/v1/intercom/calls/{identifier}'
        if action!='hangup' and (not self.enabled or identifier!=self.consent):return
        if action=='start':self.request('POST','/v1/intercom/calls',{'client':'round','id':identifier,'target':extra[0],'revision':extra[1]})
        elif action=='answer':self.request('POST',path+'/accept',{'client':'round'})
        elif action=='hangup':self.request('POST',path+'/end',{'client':'round'})
        else:
            self.request('POST',path+'/mute',{'client':'round','muted':action=='mute'})
            if self.audio:self.audio.mute(action=='mute')

    def run(self):
        last=0.
        try:
            while not self.stopped.wait(.05):
                if not self.capable:continue
                try:
                    if self.enabled and not self.cleaner and not self.audio:
                        self.preparing=True
                        try:self.cleaner=self.cleaner_factory()
                        finally:self.preparing=False
                    changed=False
                    try:item=self.actions.get_nowait()
                    except queue.Empty:item=None
                    if item:self.action(item);changed=True
                    if not changed and self.clock()-last<1:continue
                    last=self.clock()
                    state=self.request('POST','/v1/intercom/heartbeat',{'client':'round','enabled':self.enabled and bool(self.cleaner or self.audio),'busy':self.other_busy})
                    call=state.get('call') or {}
                    if self.audio and not self.audio.muted and self.clock()-self.audio.last_input>4:self.audio.close()
                    if call.get('status')=='active' and call.get('id')!=self.consent or not self.enabled and call.get('status') in {'ringing','active'}:
                        self.request('POST',f"/v1/intercom/calls/{call['id']}/end",{'client':'round'});call['status']='ended'
                    if call.get('status')=='active' and self.consent==call['id'] and not self.audio:
                        if not self.cleaner:raise RuntimeError('Echo control unavailable')
                        self.request('POST',f"/v1/intercom/calls/{call['id']}/mute",{'client':'round','muted':False});call['muted']=False
                        audio=CallAudio(self.client,call['id'],self.cleaner,self.clock);self.cleaner=None
                        audio.mute(False);self.audio=audio;audio.start()
                    if self.audio and (call.get('status')!='active' or self.audio.stop.is_set()):
                        if call.get('status')=='active':self.request('POST',f"/v1/intercom/calls/{call['id']}/end",{'client':'round'});call['status']='ended'
                        self.audio.close();self.audio=None;self.consent=None;self.capture=None
                    if call.get('status')=='ended':self.consent=None;self.capture=None
                    with self.lock:
                        self.state=state;self.at=self.clock();self.rooms=state.get('rooms',[])[:32]
                        self.binding=hashlib.sha256(json.dumps([(r['id'],r['ready']) for r in self.rooms]).encode()).hexdigest()[:16]
                        self.notice='Ready' if state.get('ready') else state.get('status','unavailable').replace('_',' ')
                    if not self.enabled and self.cleaner:self.cleaner.close();self.cleaner=None
                except Exception:
                    self.disable('Call service unavailable');self.state={};self.at=0.
        finally:
            if self.audio:self.audio.close()
            if self.cleaner:self.cleaner.close()
            if self.capable:
                try:self.request('POST','/v1/intercom/heartbeat',{'client':'round','enabled':False,'busy':False})
                except Exception:pass

    def tick(self,status,phase):
        self.capable=status.get('device',{}).get('intercom')=='1'
        self.muted=status.get('muted',True);self.other_busy=phase not in {'armed','music','intercom'}
        if self.muted and self.busy:self.disable('Microphone muted')
        if self.at and self.clock()-self.at>=4 and not self.preparing:self.disable('Call connection lost');self.state={}
        if not self.capable or self.clock()-self.last_ui<.5:return
        self.last_ui=self.clock()
        safe=lambda s:re.sub(r'[^ -~]',' ',str(s))[:32].strip() or '-'
        with self.lock:
            state=self.state;call=self.call;rooms=list(self.rooms);binding=self.binding
            lines=[f"CALL_LIST {binding} {len(rooms)} {int(self.enabled)} {int(bool(state.get('ready')))} {safe(self.notice)}"]
            lines.extend(f"CALL_ROOM {binding} {i} {int(r['ready'])} {safe(r['room'])}" for i,r in enumerate(rooms))
            if call.get('status') in {'ringing','active'}:
                phase='active' if call['status']=='active' else call['direction']
                lines.append(f"CALL_STATE {call['id']} {phase} {int(call.get('muted',True))} {call.get('seconds',0)} {safe(call['room'])}")
            elif self.consent:lines.append(f'CALL_STATE {self.consent} outgoing 1 0 Connecting')
            else:lines.append('CALL_STATE - idle 1 0 -')
        self.write(('\n'.join(lines)+'\n').encode())

    def close(self):
        self.disable();self.stopped.set();self.thread.join(timeout=4)
