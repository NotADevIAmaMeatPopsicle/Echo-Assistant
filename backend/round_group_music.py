"""Optional Mini Sendspin receiver. The voice loop remains the only wire writer.

The network thread keeps PCM and metadata in bounded memory. It cannot open a
speaker, record a microphone, or send firmware commands. Missing dependencies,
old firmware and revoked owner settings leave the existing voice path usable.
"""
import asyncio
from collections import deque
import hashlib
from importlib.metadata import PackageNotFoundError, version
import re
from threading import Event, RLock, Thread
import time
from fastapi import HTTPException

from .group_music import GroupMusic, GroupMusicUnavailable
from .settings import default_protector
from .round_profile import RoundProfile,RoundProfileUnavailable
from .timed_speaker import TimedSpeaker, raw_clock


def player_identity(mac):
    value=re.sub('[:-]','',mac.lower())
    if not re.fullmatch(r'[0-9a-f]{12}',value):raise ValueError('A verified Mini identity is required')
    return 'echo-mini-'+hashlib.sha256(('echo-sendspin:'+value).encode()).hexdigest()[:24]


def canonical_player(rows,identity):
    """Resolve MA's universal player from its reported protocol, never its name."""
    matches=[]
    for key,row in rows.items():
        protocols=row.get('output_protocols') or []
        if not isinstance(protocols,list):continue
        if any(isinstance(p,dict) and p.get('protocol_domain')=='sendspin' and
               p.get('output_protocol_id')==identity for p in protocols):matches.append(key)
    if len(matches)!=1:raise GroupMusicUnavailable('The Mini is not uniquely registered in Music Assistant')
    return matches[0]


class ForegroundWire:
    """Stop scheduled music before a command can seize the codec or microphone."""
    COMMANDS={b'WAKE',b'AUDIO_BEGIN',b'VOICE_THINKING',b'VOICE_REPLY',b'VOICE_OFF',
              b'CHIME',b'PLAY',b'RECORD',b'CALL_BEGIN',b'CALL_START',b'CALL_ACCEPT'}

    def __init__(self,port,group):self.port,self.group=port,group
    def __getattr__(self,key):return getattr(self.port,key)
    def write(self,data):
        lines=data.splitlines() if not data.startswith(b'RV1!') else []
        call_focus=any(len(line.split())>=3 and line.split()[0]==b'CALL_STATE' and line.split()[2]!=b'idle' for line in lines)
        if call_focus or any(line.split(b' ',1)[0] in self.COMMANDS for line in lines):
            self.group.hold()
        return self.port.write(data)


class RoundGroupMusic:
    def __init__(self,root,mac,write,*,clock=raw_clock,loader=None,autostart=True):
        self.identity=player_identity(mac);self.root=root;self.clock=clock
        self.sender=TimedSpeaker(write,clock=clock)
        self.loader=loader or (lambda:GroupMusic(root,default_protector()))
        self.autostart=autostart;self.thread=None;self.stopped=Event();self.lock=RLock()
        self.pcm=deque();self.buffered=0;self.epoch=0;self.applied_epoch=-1
        self.focus_allowed=False;self.selected_source=False;self.other_music=False
        self.updated=0.;self.retry_at=0.;self.errors=0;self.dropped=0
        self.state={'phase':'firmware_required','connected':False,'server_clock':False,
                    'playing':False,'ceiling':2,'latency_ms':0,'volume':2,'muted':False,'error':None}
        self.title='';self.artist=''
        self.control_pending=None
        self.profile_allowed=True

    def _clear(self):
        self.pcm.clear();self.buffered=0;self.epoch+=1

    def publish(self,**fields):
        with self.lock:
            self.state.update(fields);self.updated=self.clock()

    def stream(self,event):
        with self.lock:
            self._clear()
            if event=='start':self.state['playing']=True;self.selected_source=True
            elif event in {'end','disconnect'}:self.state['playing']=False
            if event=='disconnect':
                self.state.update(connected=False,server_clock=False);self.title=self.artist=''

    def audio(self,pcm,presentation_us):
        with self.lock:
            if not self.focus_allowed or not self.state['server_clock']:return
            if not isinstance(pcm,bytes) or not pcm or len(pcm)%2 or len(pcm)>192000:
                self._clear();self.state['error']='audio_format';return
            while self.pcm and (self.buffered+len(pcm)>196608 or len(self.pcm)>=64):
                self.buffered-=len(self.pcm.popleft()[0]);self.dropped+=1
            self.pcm.append((pcm,presentation_us));self.buffered+=len(pcm)

    def hold(self):
        with self.lock:
            self.focus_allowed=False;self._clear()
        self.sender.focus(False)

    @property
    def active(self):return self.sender.active

    @property
    def selected(self):
        with self.lock:return self.selected_source and not self.other_music and self.state['connected']

    def receive(self,line):
        try:self.sender.receive(line)
        except RuntimeError:self._wire_failure()

    def _wire_failure(self):
        self.hold();self.errors+=1;self.retry_at=self.clock()+2

    def pump(self,phase,*,speaker_busy=False,spotify_busy=False,calls_busy=False):
        if self.autostart and self.thread is None and self.sender.capable and not self.stopped.is_set():
            self.thread=Thread(target=self._worker,name='mini-group-music',daemon=True);self.thread.start()
        with self.lock:
            state=dict(self.state);self.other_music=spotify_busy
            allowed=(self.profile_allowed and phase=='armed' and not speaker_busy and not spotify_busy and not calls_busy and
                     state['connected'] and state['server_clock'] and not state['error'] and
                     self.clock()-self.updated<2 and self.clock()>=self.retry_at and self.sender.capable)
            if self.sender.ceiling!=state['ceiling'] or self.sender.latency_us!=state['latency_ms']*1000:
                self.sender.stop();self.sender.ceiling=state['ceiling'];self.sender.latency_us=state['latency_ms']*1000
            if not allowed or allowed!=self.focus_allowed:self._clear()
            self.focus_allowed=bool(allowed)
            if self.epoch!=self.applied_epoch:self.sender.stop();self.applied_epoch=self.epoch
            self.sender.focus(allowed)
            gain=0 if state['muted'] else min(state['volume'],state['ceiling'])
            if gain!=self.sender.gain:self.sender.volume(gain)
            chunks=list(self.pcm);self.pcm.clear();self.buffered=0
        try:
            for pcm,at in chunks:self.sender.append(pcm,at)
            # A disabled receiver sends no new commands, including clock probes.
            if state['connected']:self.sender.pump()
        except (RuntimeError,ValueError):self._wire_failure()

    def health(self):
        with self.lock:
            return {**{k:v for k,v in self.state.items() if k not in {'ceiling','latency_ms'}},
                    'transport':self.sender.health(),'focus_held':not self.focus_allowed,
                    'buffered_bytes':self.buffered,'discarded_chunks':self.dropped,'wire_errors':self.errors}

    def now_playing(self):
        with self.lock:return ('playing' if self.state['playing'] else 'paused',self.title,self.artist)

    def submit_control(self,worker,action):
        if self.control_pending is None or self.control_pending.done():
            self.control_pending=worker.submit(self.control,action)

    def control(self,intent):
        """Run on a worker, rechecking saved permissions for every home control."""
        try:
            if not self.profile_allowed or RoundProfile(self.root,default_protector()).snapshot()['profile']['mode']=='guest':raise PermissionError()
            music=self.loader();music.settings()
            if not music.config.round_enabled or not music.config.enabled:raise PermissionError()
            rows=music.inventory();identifier=canonical_player(rows,self.identity)
            row=music.allowed(identifier,rows)
            if intent=='now_playing':
                media=row.get('current_media') or {};title=str(media.get('title') or '')[:150];artist=str(media.get('artist') or '')[:150]
                return 'complete',(title+(' by '+artist if artist else '')+'.') if title else 'No song is selected on this speaker.'
            action=intent
            if action=='toggle':action='pause' if row.get('playback_state',row.get('state'))=='playing' else 'play'
            if action=='pause' and 'pause' not in row.get('supported_features',[]):action='stop'
            if action not in {'play','pause','stop','next','previous'}:raise ValueError()
            # control() refreshes inventory and checks all related outputs again.
            music.control(action,identifier,None,music.revision)
            return 'accepted',{'play':'Music requested.','pause':'Music paused.','stop':'Music stopped.',
                               'next':'Next track requested.','previous':'Previous track requested.'}[action]
        except (GroupMusicUnavailable,RoundProfileUnavailable,PermissionError,ValueError,OSError,HTTPException):
            return 'unavailable','Music Assistant could not confirm that control. Check that this Mini and its group are shared in Echo Settings.'

    def close(self):
        self.stopped.set();self.hold()
        if self.thread:self.thread.join(timeout=3)

    def _worker(self):
        try:asyncio.run(self._monitor())
        except Exception:
            # Never put tokens, endpoint identities, SDK payloads or track text in logs.
            self.publish(phase='unavailable',error='receiver_failed',connected=False,server_clock=False)
        finally:self.stream('disconnect')

    async def _monitor(self):
        task=None;binding=None;retry=0.;backoff=1
        try:
            while not self.stopped.is_set():
                try:
                    music=await asyncio.to_thread(self.loader);music.settings()
                    config=music.config
                    wanted=(self.profile_allowed and self.sender.capable and music.actions_enabled and config.enabled and config.round_enabled and bool(music.token))
                    current=(config.model_dump_json(),music.token) if wanted else None
                    if task and (task.done() or current!=binding):
                        task.cancel();await asyncio.gather(task,return_exceptions=True);task=None
                        self.stream('disconnect');retry=time.monotonic()+backoff;backoff=min(30,backoff*2)
                    if not wanted:self.publish(phase='disabled',connected=False,server_clock=False,error=None)
                    elif task is None and time.monotonic()>=retry:
                        try:
                            if version('aiosendspin')!='6.0.1':raise PackageNotFoundError()
                            import aiohttp  # noqa: F401 -- fail before opening a connection
                        except (ImportError,PackageNotFoundError):
                            self.publish(phase='runtime_required',error='install_optional_runtime',connected=False)
                        else:
                            binding=current
                            self.publish(phase='connecting',ceiling=config.round_volume,volume=config.round_volume,
                                         latency_ms=config.round_latency_ms,error=None,muted=False)
                            task=asyncio.create_task(self._connect(config,music.token))
                    if self.state['connected']:backoff=1
                except (OSError,ValueError,RuntimeError):
                    if task:task.cancel();await asyncio.gather(task,return_exceptions=True);task=None
                    self.stream('disconnect');self.publish(phase='configuration_error',error='settings_unavailable')
                await asyncio.sleep(.5)
        finally:
            if task:task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def _connect(self,config,token):
        from .round_sendspin import connect
        try:await connect(self,config,token)
        except asyncio.CancelledError:raise
        except Exception:self.publish(phase='reconnecting',error='connection_unavailable')
        finally:self.stream('disconnect')
