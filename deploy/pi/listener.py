"""Native, opt-in Pi voice endpoint. Wake detection stays on this Pi."""
from array import array
from concurrent.futures import Future
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import selectors
import secrets
import stat
import subprocess
import sys
import threading
import time
import wave

from audio_once import wav, scaled_reply
from alerts import chime
from spotify import Unavailable, outputs

PHRASES = ('hey echo', 'okay echo')


def inputs():
    try: lines = subprocess.check_output(['arecord','-L'], timeout=4, stderr=subprocess.DEVNULL, text=True).splitlines()
    except (OSError, subprocess.SubprocessError): return []
    return [{'id':s,'name':s} for s in lines if re.fullmatch(r'[A-Za-z0-9_.,:=+-]{1,120}',s) and s != 'null'][:100]


def validate(value):
    if not isinstance(value, dict) or set(value) != {'enabled','muted','input','output','volume','echo_cancelled_input','allow_home'}: raise ValueError('Invalid Pi voice settings')
    for key in ('enabled','muted','echo_cancelled_input','allow_home'):
        if type(value[key]) is not bool: raise ValueError('Invalid Pi voice option')
    if type(value['volume']) is not int or not 0 <= value['volume'] <= 30: raise ValueError('Choose 0–30% output volume')
    for key in ('input','output'):
        if not isinstance(value[key], str) or value[key] and not re.fullmatch(r'[A-Za-z0-9_.,:=+-]{1,120}', value[key]): raise ValueError('Choose named ALSA devices')
    if value['enabled'] and not (value['input'] and value['output']): raise ValueError('Choose the attached microphone and speaker')
    return dict(value)


class Detector:
    def __init__(self, path):
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        self.model = Model(str(path))
        self.recognizer = KaldiRecognizer(self.model,16000,json.dumps([*PHRASES,'[unk]']))
        self.recognizer.SetWords(True)

    def reset(self): self.recognizer.Reset()

    def feed(self, pcm):
        if not self.recognizer.AcceptWaveform(pcm): return False
        result = json.loads(self.recognizer.Result()); words = result.get('result', [])
        phrase = result.get('text','').strip().lower()
        return (phrase in PHRASES and len(words)==2 and ' '.join(w.get('word','') for w in words)==phrase
                and all(type(w.get('conf')) in (float,int) and .8 <= w['conf'] <= 1 for w in words))


class Segment:
    """Bounded command capture after the cue, with a trailing-silence endpoint."""
    def __init__(self):
        self.chunks=[]; self.samples=0; self.voiced=0; self.silence=0; self.noise=60.

    def feed(self, pcm):
        if len(pcm)%2: raise ValueError('Invalid microphone samples')
        values=array('h');values.frombytes(pcm)
        if sys.byteorder!='little':values.byteswap()
        self.samples += len(values)
        if self.samples > 128000: return True
        self.chunks.append(pcm)
        rms=math.sqrt(sum(x*x for x in values)/max(1,len(values)))
        if rms > max(180, self.noise*2.5): self.voiced+=len(values);self.silence=0
        else:
            self.silence+=len(values)
            if not self.voiced:self.noise=.95*self.noise+.05*min(rms,300)
        return self.samples>=128000 or self.voiced>=3200 and self.silence>=14400

    def result(self): return b''.join(self.chunks) if self.voiced>=1600 else b''


class Listener:
    def __init__(self, request, music, home=None, *, captures=inputs, speakers=outputs, detector_factory=Detector, popen=subprocess.Popen):
        self.request,self.music,self.captures,self.speakers,self.detector_factory,self.popen=request,music,captures,speakers,detector_factory,popen
        self.home=Path(home or Path.home());self.path=self.home/'.config/echo-display/voice.json'
        self.model=self.home/'.local/share/echo-display/runtime/voice-model'
        self.config={'enabled':False,'muted':True,'input':'','output':'','volume':2,'echo_cancelled_input':False,'allow_home':False}
        self.lock=threading.RLock();self.stop=threading.Event();self.cancel=threading.Event();self.talk=threading.Event();self.end_capture=threading.Event()
        self.thread=None;self.capture=None;self.player=None;self.detector=None;self.frames=None
        self.phase='disabled';self.error=None;self.config_error=False;self.request_id=None;self.cancel_sent=None;self.pending_http=None;self.talk_options=None
        self.result=None;self.result_at=0.;self.client=secrets.token_hex(16);self.last_focus=0.;self.last_host=0.;self.host_ready=False;self.health_thread=None
        self.devices_at=0.;self.devices_in=[];self.devices_out=[]
        if self.path.exists():
            try:
                info=self.path.stat()
                if self.path.is_symlink() or os.name=='posix' and (info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o077):raise ValueError()
                self.config=validate(json.loads(self.path.read_text(encoding='utf-8')))
            except (OSError,ValueError,TypeError):self.config_error=True;self.error='Saved Pi voice settings are unreadable; the file was preserved'

    def ready(self):
        return importlib.util.find_spec('vosk') is not None and (self.model/'am/final.mdl').is_file()

    def settings(self):
        with self.lock:
            if time.monotonic()-self.devices_at>15:
                self.devices_in,self.devices_out=self.captures(),self.speakers();self.devices_at=time.monotonic()
            if self.result and time.monotonic()-self.result_at>120:self.result=None
            return {'supported':True,'settings':dict(self.config),'inputs':self.devices_in,'outputs':self.devices_out,
                    'runtime_installed':self.ready(),'phase':self.phase,'error':self.error,'result':self.result,
                    'phrases':list(PHRASES),'software_mute':True}

    def configure(self,value):
        if self.config_error:raise Unavailable('Repair the saved Pi voice settings first')
        value=validate(value)
        if value['enabled']:
            if not self.ready():raise Unavailable('Install the Pi wake runtime first')
            if value['input'] not in {d['id'] for d in self.captures()} or value['output'] not in {d['id'] for d in self.speakers()}:raise ValueError('The selected microphone or speaker is unavailable')
        with self.lock:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.path.is_symlink():raise ValueError('Use a regular settings file')
            temp=self.path.with_suffix('.new');fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
                temp.replace(self.path)
            finally:temp.unlink(missing_ok=True)
            self.config=value;self.error=None;self.talk.clear();self.talk_options=None;self.interrupt()
        return self.settings()

    @staticmethod
    def terminate(process):
        if process and process.poll() is None:
            try:process.terminate();process.wait(timeout=.7)
            except (OSError,subprocess.TimeoutExpired):
                try:process.kill();process.wait(timeout=.7)
                except (OSError,subprocess.TimeoutExpired):pass

    def stop_remote(self,identifier):
        try:self.request('/v1/display/voice/'+identifier+'/stop',{})
        except Exception:pass  # Status still says stop was requested, never that an action was undone.

    def interrupt(self):
        with self.lock:
            self.cancel.set();self.terminate(self.player);self.terminate(self.capture)
            if self.request_id and self.request_id!=self.cancel_sent:
                self.cancel_sent=self.request_id
                threading.Thread(target=self.stop_remote,args=(self.request_id,),daemon=True).start()

    def control(self,action,allow_home=None,reply_audio=None):
        if any(value is not None and type(value) is not bool for value in (allow_home,reply_audio)):raise ValueError("Invalid voice permission")
        if action!="talk" and (allow_home is not None or reply_audio is not None):raise ValueError("Voice permissions belong to a talk request")
        if action=='stop':self.talk.clear();self.talk_options=None;self.interrupt()
        elif action=='talk':
            if not self.config['enabled'] or self.config['muted']:raise Unavailable('Enable and unmute this Pi microphone first')
            self.interrupt();self.talk_options={"allow_home":self.config["allow_home"] if allow_home is None else allow_home,"reply_audio":True if reply_audio is None else reply_audio};self.talk.set()
        elif action=='send':self.end_capture.set()
        elif action=='mute':return self.configure({**self.config,'muted':True})
        elif action=='unmute':return self.configure({**self.config,'muted':False})
        else:raise ValueError('Unknown Pi voice action')
        return {'accepted':True}

    def start(self):
        self.thread=threading.Thread(target=self.run,name='pi-wake',daemon=True);self.thread.start()
        self.health_thread=threading.Thread(target=self.health,name='pi-voice-health',daemon=True);self.health_thread.start()

    def close(self):
        self.stop.set();self.interrupt()
        if self.thread:self.thread.join(3)
        if self.health_thread:self.health_thread.join(6)

    def health(self):
        while not self.stop.wait(2):
            if self.pending_http is not None and self.pending_http.done() and self.request_id is None:self.pending_http=None
            if self.result and time.monotonic()-self.result_at>120:self.result=None
            if not self.config['enabled'] or self.config['muted']:
                self.host_ready=False;continue
            try:
                self.host_ready=bool(self.request('/v1/display/voice')['available']);self.last_host=time.monotonic()
            except Exception:self.host_ready=False

    def externally_busy(self):
        with self.music.lock:
            self.music.held()
            return any(key!=self.client for key in self.music.holds)

    def check(self,config):
        if self.stop.is_set() or self.cancel.is_set() or config!=self.config:raise InterruptedError()
        if self.externally_busy():raise InterruptedError()
        if not self.host_ready or time.monotonic()-self.last_host>10:raise Unavailable('Host speech runtime is unavailable')
        if self.phase not in {'armed','playback_guard'} and time.monotonic()-self.last_focus>5:
            self.music.focus(self.client,True);self.last_focus=time.monotonic()

    def microphone(self,config):
        with self.lock:
            self.capture=self.popen(['arecord','-q','-D',config['input'],'-t','raw','-f','S16_LE','-r','16000','-c','1',
                                     '--buffer-time=100000','--period-time=20000'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
        pending=bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(self.capture.stdout,selectors.EVENT_READ)
            last=time.monotonic()
            while True:
                self.check(config)
                if not selector.select(.1):
                    if self.capture.poll() is not None or time.monotonic()-last>3:raise Unavailable('Microphone input stopped')
                    continue
                block=os.read(self.capture.stdout.fileno(),2560)
                if not block:raise Unavailable('Microphone disconnected')
                last=time.monotonic();pending.extend(block)
                while len(pending)>=2560:
                    frame=bytes(pending[:2560]);del pending[:2560];yield frame

    def play(self,pcm,config,*,barge=False):
        with os.fdopen(os.memfd_create('echo-voice',os.MFD_CLOEXEC),'w+b') as source:
            source.write(pcm);source.seek(0)
            with self.lock:
                self.check(config)
                self.player=self.popen(['aplay','-q','-D',config['output'],'-t','raw','-f','S16_LE','-r','48000','-c','1'],
                                       stdin=source,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            started=time.monotonic()
            try:
                while self.player.poll() is None:
                    frame=next(self.frames)  # Drain microphone frames even while recognition is inhibited.
                    if barge and config['echo_cancelled_input'] and self.detector.feed(frame):
                        self.talk.set();raise InterruptedError()
                    if time.monotonic()-started>95:raise Unavailable('Speaker playback timed out')
                if self.player.returncode:raise Unavailable('Attached speaker playback failed')
            finally:self.terminate(self.player);self.player=None

    def command(self,config):
        if self.pending_http is not None and not self.pending_http.done():raise Unavailable('The previous voice request is still stopping')
        options=self.talk_options or {'allow_home':config['allow_home'],'reply_audio':True};self.talk_options=None
        self.talk.clear();self.phase='cue';self.music.focus(self.client,True);self.last_focus=time.monotonic()
        # The first warm note from the same locally generated alert sound.
        with wave.open(io.BytesIO(chime(config['volume'])),'rb') as cue:pcm=cue.readframes(48000)
        self.play(pcm,config)
        self.detector.reset();self.phase='listening';self.end_capture.clear();segment=Segment()
        while not segment.feed(next(self.frames)) and not self.end_capture.is_set():pass
        pcm=segment.result()
        if not pcm:self.error='I did not catch that. Try again after the cue.';return
        self.phase='thinking';self.request_id=secrets.token_hex(16);identifier=self.request_id
        result=Future();self.pending_http=result
        def ask():
            try:result.set_result(self.request('/v1/display/voice?allow_home='+str(options['allow_home']).lower()+'&reply_audio='+str(options['reply_audio']).lower()+'&capture_id='+identifier,wav(pcm),'audio/wav',120))
            except Exception as error:result.set_exception(error)
        threading.Thread(target=ask,name='pi-voice-request',daemon=True).start()
        while not result.done():
            frame=next(self.frames)
            if self.detector.feed(frame):self.talk.set();raise InterruptedError()
        self.check(config);reply=result.result();self.request_id=None
        self.result={'id':identifier,'text':str(reply.get('text',''))[:4000],'transcript':str(reply.get('transcript',''))[:1200],'status':reply.get('status','unavailable'),'home_actions':reply.get('home_actions',[])[:12]};self.result_at=time.monotonic()
        if reply.get('audio'):
            self.phase='speaking';self.detector.reset()
            self.play(scaled_reply(reply['audio']['data'],config['volume']),config,barge=True)
        elif reply.get('audio_error'):self.error=reply['audio_error']

    def run(self):
        while not self.stop.wait(.3):
            config=dict(self.config)
            if self.config_error or not config['enabled'] or config['muted']:
                self.phase='muted' if config['enabled'] and config['muted'] else 'disabled';continue
            if self.externally_busy():self.phase='busy';continue
            try:
                self.cancel.clear();self.phase='armed';self.check(config)
                if config['input'] not in {d['id'] for d in self.captures()} or config['output'] not in {d['id'] for d in self.speakers()}:raise Unavailable('Attached microphone or speaker is unavailable')
                if self.detector is None:self.detector=self.detector_factory(self.model)
                self.detector.reset();self.frames=self.microphone(config);self.phase='armed';self.error=None
                while True:
                    self.phase='armed'
                    frame=next(self.frames)
                    # Hardware/OS AEC must be explicitly selected before recognizing speaker playback.
                    playing=self.music.snapshot().get('status')=='playing'
                    if playing and not config['echo_cancelled_input'] and not self.talk.is_set():
                        self.phase='playback_guard';self.detector.reset();continue
                    self.phase='armed'
                    if self.talk.is_set() or self.detector.feed(frame):
                        try:self.command(config)
                        finally:self.music.focus(self.client,False)
                        self.detector.reset()
            except InterruptedError:
                self.phase='muted' if self.config['muted'] else 'stopping';self.interrupt()
            except Exception:
                if self.cancel.is_set() or config!=self.config:
                    self.phase='muted' if self.config['muted'] else 'stopping'
                else:
                    self.phase='unavailable';self.error='Pi voice is waiting for its microphone, speaker, wake runtime or private host connection.'
                    self.interrupt();self.stop.wait(2)
            finally:
                self.terminate(self.capture)
                if self.frames:
                    self.frames.close();self.frames=None
                if self.capture and self.capture.stdout:self.capture.stdout.close()
                self.capture=None;self.request_id=None;self.music.focus(self.client,False)
