"""Pi-owned Spotify receiver. Audio, credentials and track state are transient.

The bridge owns this object. Its default is disabled; a named ALSA output is
required. The receiver has no microphone input and no route to another Echo.
"""
from array import array
from collections import deque
import hashlib
from hmac import compare_digest
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request


class Unavailable(RuntimeError):pass


def outputs():
    """Enumerate ALSA names without opening a playback device."""
    if not shutil.which('aplay'):return []
    try:lines=subprocess.check_output(['aplay','-L'],timeout=4,stderr=subprocess.DEVNULL,text=True).splitlines()
    except (OSError,subprocess.SubprocessError):return []
    result=[]
    for line in lines:
        if line and not line[0].isspace() and re.fullmatch(r'[A-Za-z0-9_.,:=+-]{1,120}',line) and line!='null':
            result.append({'id':line,'name':line})
        elif result and line.startswith('    ') and result[-1]['name']==result[-1]['id']:
            result[-1]['name']=line.strip()[:120]
    return result[:100]


def scaled_pcm(pcm,volume):
    if len(pcm)%4:raise ValueError('Expected stereo s16 PCM')
    samples=array('h');samples.frombytes(pcm)
    if sys.byteorder!='little':samples.byteswap()
    gain=max(0,min(30,volume))/100
    for i,value in enumerate(samples):samples[i]=round(value*gain)
    if sys.byteorder!='little':samples.byteswap()
    return samples.tobytes()


def validate_config(value):
    if not isinstance(value,dict) or set(value)!={'enabled','name','output','volume'}:raise ValueError('Invalid receiver settings')
    if type(value['enabled']) is not bool or type(value['volume']) is not int or not 0<=value['volume']<=30:raise ValueError('Output level must be 0–30%')
    if not isinstance(value['name'],str) or not 1<=len(value['name'].strip())<=60 or any(ord(c)<32 for c in value['name']):raise ValueError('Choose a short receiver name')
    if not isinstance(value['output'],str) or value['output'] and not re.fullmatch(r'[A-Za-z0-9_.,:=+-]{1,120}',value['output']):raise ValueError('Choose an ALSA output')
    if value['enabled'] and not value['output']:raise ValueError('Choose the speaker attached to this Pi')
    return {**value,'name':value['name'].strip()}


class Spotify:
    def __init__(self,home=None,*,clock=time.monotonic,devices=outputs,popen=subprocess.Popen):
        self.home=Path(home or Path.home());self.clock=clock;self.devices=devices;self.popen=popen
        self.path=self.home/'.config/echo-display/spotify.json'
        self.binary=self.home/'.local/share/echo-display/runtime/echo-librespot'
        self.config={'enabled':False,'name':'Echo Display','output':'','volume':2}
        self.lock=threading.RLock();self.stop=threading.Event();self.thread=None;self.process=None;self.player=None
        self.status='not_configured';self.error=None;self.commands=deque(maxlen=16);self.holds={};self.silenced=True
        self.ducks={};self.playback_gain=1.
        self.auxiliary_outputs=[]
        self.generation=0;self.key='';self.track={};self.position_at=0.;self.capabilities=[];self.available_outputs=[];self.outputs_at=-100.
        self.art_key=None;self.art_content=None;self.art_lock=threading.Lock()
        self.config_error=False
        if self.path.exists():
            try:
                info=self.path.stat()
                if self.path.is_symlink() or os.name=='posix' and (info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o077):raise ValueError('Private settings required')
                self.config=validate_config(json.loads(self.path.read_text(encoding='utf-8')))
            except (OSError,ValueError,TypeError):
                self.config_error=True;self.error='Saved Spotify settings are unreadable; the original file was preserved'

    def settings(self):
        with self.lock:
            if self.clock()-self.outputs_at>15:self.available_outputs=self.devices();self.outputs_at=self.clock()
            return {'supported':True,'settings':dict(self.config),'outputs':list(self.available_outputs),'runtime_installed':self.binary.is_file(),'status':self.status,'error':self.error}

    def configure(self,value):
        if self.config_error:raise Unavailable('Repair the saved Spotify settings before editing them')
        value=validate_config(value)
        with self.lock:
            if value['enabled'] and value['output'] not in {d['id'] for d in self.devices()}:raise ValueError('That output is not available; no fallback was selected')
            if value['enabled'] and not self.binary.is_file():raise Unavailable('Install the Pi Spotify receiver first')
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.path.is_symlink():raise ValueError('Use a regular settings file')
            temp=self.path.with_suffix('.new')
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
                temp.replace(self.path)
            finally:temp.unlink(missing_ok=True)
            restart=any(value[k]!=self.config[k] for k in ('enabled','name','output'))
            self.config=value
            if restart:self.generation+=1;self.silenced=True;self.commands.clear();self.close_output()
            self.error=None
            return self.settings()

    def held(self):
        now=self.clock();self.holds={k:v for k,v in self.holds.items() if now-v<15}
        return bool(self.holds)

    def focus(self,client,busy):
        if not isinstance(client,str) or not re.fullmatch(r'[a-f0-9]{32}',client) or type(busy) is not bool:raise ValueError('Invalid audio focus request')
        with self.lock:
            if busy:
                if len(self.holds)>=32 and client not in self.holds:raise Unavailable('Too many audio sessions')
                self.holds[client]=self.clock();self.pause()
            else:self.holds.pop(client,None)
            held=self.held()
        if busy:self.stop_auxiliary('focus')
        return {'paused_for_voice':held}

    def register_auxiliary(self,receiver):
        with self.lock:
            if receiver not in self.auxiliary_outputs:self.auxiliary_outputs.append(receiver)

    def claim_idle(self,client):
        if not isinstance(client,str) or not re.fullmatch(r'[a-f0-9]{32}',client):raise ValueError('Invalid audio focus request')
        with self.lock:
            if self.held():return False
            self.holds[client]=self.clock();self.pause()
        try:self.stop_auxiliary('focus')
        except Exception:
            with self.lock:self.holds.pop(client,None)
            raise
        return True

    def stop_auxiliary(self,reason):
        # A receiver's worker reads the music snapshot. Never hold this lock
        # while waiting for its synchronous output-stop acknowledgement.
        with self.lock:receivers=tuple(self.auxiliary_outputs)
        for receiver in receivers:
            if receiver.hard_stop(reason) is not True:
                raise Unavailable('Another local audio output could not be stopped')

    def duck(self,client,active):
        """A renewable voice lease lowers PCM without changing Spotify's volume or transport."""
        if not isinstance(client,str) or not re.fullmatch(r'[a-f0-9]{32}',client) or type(active) is not bool:raise ValueError('Invalid music duck request')
        with self.lock:
            self.ducked()
            if active:
                if len(self.ducks)>=32 and client not in self.ducks:raise Unavailable('Too many audio sessions')
                self.ducks[client]=self.clock()
            else:self.ducks.pop(client,None)

    def ducked(self):
        now=self.clock();self.ducks={k:v for k,v in self.ducks.items() if now-v<15}
        return bool(self.ducks)

    def output_level(self,frames):
        # Roughly 120 ms fades avoid hard gain steps on activation and release.
        target=.2 if self.ducked() else 1.
        step=max(0,frames)/(44100*.12)
        self.playback_gain+=max(-step,min(step,target-self.playback_gain))
        return self.config['volume']*self.playback_gain

    def close_output(self):
        player,self.player=self.player,None
        if player:
            try:player.terminate();player.wait(timeout=1)
            except (OSError,subprocess.TimeoutExpired):
                try:player.kill();player.wait(timeout=1)
                except (OSError,subprocess.TimeoutExpired):pass
            if player.stdin:player.stdin.close()

    def pause(self):
        self.silenced=True;self.close_output()
        if self.process and 'pause' not in self.commands and len(self.commands)<16:self.commands.append('pause')

    def control(self,action,value=None):
        with self.lock:
            if not self.process or self.process.poll() is not None:raise Unavailable('Pi receiver is not running')
            if self.held() and action in {'play','toggle','next','previous'}:raise Unavailable('Finish the voice session before playing music')
            if action in {'play','pause','next','previous','toggle'} and value is None:command=action
            elif action=='shuffle' and type(value) is bool:command='shuffle '+str(value).lower()
            elif action=='repeat' and value in {'off','context','track'}:command='repeat '+value
            elif action in {'seek','volume'} and type(value) is int and 0<=value<=(86400000 if action=='seek' else 100):command=f'{action} {value}'
            else:raise ValueError('Unsupported music control')
            if len(self.commands)>=16:raise Unavailable('Receiver controls are busy')
            if action=='pause' or action=='toggle' and self.status=='playing':self.pause()
            else:self.commands.append(command)
            return {'status':'accepted'}

    def event(self,raw):
        try:
            event=json.loads(raw)
            if not isinstance(event,dict) or not isinstance(event.get('key'),str) or not compare_digest(event['key'],self.key):return
            kind=event.get('event');now=self.clock()
            with self.lock:
                if kind=='receiver_ready':self.capabilities=['seek','shuffle','repeat','volume'] if event.get('ui_version')=='2' else []
                elif kind=='track_changed':
                    cover=next((u for u in str(event.get('covers','')).splitlines() if re.fullmatch(r'https://i\.scdn\.co/image/[a-fA-F0-9]{40}',u)),'')
                    self.track.update(title=str(event.get('name',''))[:200],artist=str(event.get('artists',''))[:400],album=str(event.get('album') or event.get('show_name') or '')[:200],cover=cover,uri=str(event.get('uri',''))[:100],duration_ms=max(0,min(86400000,int(event.get('duration_ms',0)))),position_ms=0,explicit=event.get('is_explicit')=='true');self.position_at=now
                elif kind in {'playing','paused','stopped','seeked','position_correction'}:
                    self.track['position_ms']=max(0,int(event.get('position_ms',0)));self.position_at=now
                    if kind in {'playing','paused','stopped'}:
                        self.status=kind;self.silenced=kind!='playing'
                        if kind!='playing':self.close_output()
                        elif self.held():self.pause()
                elif kind=='volume_changed':self.track['volume']=round(max(0,min(65535,int(event['volume'])))*100/65535)
                elif kind=='shuffle_changed':self.track['shuffle']=event.get('shuffle')=='true'
                elif kind=='repeat_changed':self.track['repeat']='track' if event.get('repeat_track')=='true' else 'context' if event.get('repeat')=='true' else 'off'
                elif kind=='session_connected':self.status='connected'
                elif kind=='session_disconnected':self.status='discoverable';self.track={};self.silenced=True;self.close_output()
        except (ValueError,TypeError,KeyError,OverflowError):pass

    def snapshot(self):
        with self.lock:
            running=bool(self.process and self.process.poll() is None)
            state={k:v for k,v in self.track.items() if k not in {'cover','uri'}}
            cover=self.track.get('cover','');key=hashlib.sha256(cover.encode()).hexdigest() if cover else ''
            match=re.fullmatch(r'spotify:(track|episode):([A-Za-z0-9]{22})',self.track.get('uri',''))
            position=state.get('position_ms',0)+(int((self.clock()-self.position_at)*1000) if self.status=='playing' else 0)
            return {**state,'supported':True,'available':running,'status':self.status,'receiver_name':self.config['name'],
                    'output_volume':self.config['volume'],'ducked':self.ducked(),'output_configured':bool(self.config['output']),'error':self.error,
                    'position_ms':min(position,state.get('duration_ms',0)),'capabilities':self.capabilities,
                    'artwork':f'/v1/display/music/artwork/{key}' if key else None,
                    'open_url':f'https://open.spotify.com/{match[1]}/{match[2]}' if match else ''}

    def artwork(self,key):
        with self.art_lock:
            with self.lock:
                url=self.track.get('cover','')
                if not url or hashlib.sha256(url.encode()).hexdigest()!=key:raise ValueError('Artwork is no longer current')
                if self.art_key==key:return self.art_content
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self,*args,**kwargs):return None
            opener=urllib.request.build_opener(NoRedirect,urllib.request.ProxyHandler({}))
            with opener.open(urllib.request.Request(url,headers={'Accept':'image/jpeg,image/png'}),timeout=6) as response:
                content=response.read(3_000_001);kind=response.headers.get_content_type()
            if len(content)>3_000_000 or not (kind=='image/jpeg' and content.startswith(b'\xff\xd8\xff') or kind=='image/png' and content.startswith(b'\x89PNG\r\n\x1a\n')):raise ValueError('Unsupported cover image')
            with self.lock:
                if self.track.get('cover')!=url:raise ValueError('Track changed')
                self.art_key,self.art_content=key,(content,kind)
                return self.art_content

    def start(self):
        if not self.thread:
            self.thread=threading.Thread(target=self.run,name='pi-spotify',daemon=True);self.thread.start()

    def run(self):
        delay=2
        while not self.stop.is_set():
            if not self.config['enabled']:
                self.status='not_configured';self.stop.wait(.25);continue
            try:
                self.session();delay=2
            except (OSError,ValueError,Unavailable):
                self.status='unavailable';self.error='Receiver or selected audio output unavailable'
            if not self.stop.is_set():self.stop.wait(delay);delay=min(60,delay*2)

    def session(self):
        with self.lock:
            config=dict(self.config);generation=self.generation
            if config['output'] not in {d['id'] for d in self.devices()}:raise Unavailable('Selected output missing')
        runtime=Path('/run/user')/str(os.geteuid())
        with tempfile.TemporaryDirectory(prefix='echo-spotify-',dir=runtime) as cache,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as events,selectors.DefaultSelector() as selector:
            events.bind(('127.0.0.1',0));events.setblocking(False);self.key=secrets.token_urlsafe(32)
            env={**os.environ,'ROUND_VOICE_EVENT_KEY':self.key,'ROUND_VOICE_EVENT_PORT':str(events.getsockname()[1]),'RUST_LOG':'error'}
            command=[str(self.binary),'--name',config['name'],'--device-type','speaker','--backend','pipe','--format','S16','--bitrate','320','--disable-audio-cache','--disable-credential-cache','--system-cache',cache,'--tmp',cache,'--initial-volume','100','--volume-ctrl','linear','--enable-volume-normalisation','--autoplay','off','--onevent','round-voice-events']
            process=self.popen(command,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
            with self.lock:self.process=process;self.status='discoverable';self.error=None;self.silenced=True;self.track={};self.capabilities=[]
            selector.register(events,selectors.EVENT_READ,'event');selector.register(process.stdout,selectors.EVENT_READ,'pcm')
            carry=b''
            try:
                while not self.stop.is_set() and generation==self.generation and process.poll() is None:
                    with self.lock:
                        while self.commands:process.stdin.write((self.commands.popleft()+'\n').encode())
                    for selected,_ in selector.select(.05):
                        if selected.data=='event':self.event(events.recv(16384));continue
                        block=os.read(process.stdout.fileno(),4096)
                        if not block:break
                        carry+=block;end=len(carry)//4*4;pcm,carry=carry[:end],carry[end:]
                        with self.lock:
                            blocked=self.silenced or self.held() or generation!=self.generation
                            opening=not blocked and pcm and not self.player
                        if opening:self.stop_auxiliary('spotify')
                        with self.lock:
                            blocked=self.silenced or self.held() or generation!=self.generation
                            if not blocked and pcm and not self.player:
                                self.player=self.popen(['aplay','--quiet','-D',config['output'],'-t','raw','-f','S16_LE','-c','2','-r','44100','--buffer-time=100000','--period-time=20000'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,bufsize=0)
                            player=self.player;volume=self.output_level(len(pcm)//4)
                        if blocked:self.stop.wait(len(pcm)/176400);continue
                        if player:
                            try:player.stdin.write(scaled_pcm(pcm,volume))
                            except OSError:
                                if player is self.player:raise Unavailable('Selected output failed') from None
                if process.poll() not in {None,0}:raise Unavailable('Receiver exited')
            finally:
                with self.lock:self.process=None;self.silenced=True;self.close_output();self.commands.clear();self.track={};self.capabilities=[];self.art_key=self.art_content=None
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
                process.stdin.close();process.stdout.close()

    def close(self):
        self.stop.set()
        with self.lock:self.generation+=1;self.silenced=True;self.close_output()
        if self.thread:self.thread.join(timeout=5)
