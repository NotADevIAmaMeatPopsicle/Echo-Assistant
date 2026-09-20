"""Private Pi lifecycle and fresh access/focus evidence for optional Bluetooth."""
from pathlib import Path
import threading
import time

from bluetooth_receiver import BluetoothReceiver, DEFAULT_CONFIG, load_private_config


class BluetoothSession:
    def __init__(self, request, music, home=None, *, clock=time.monotonic, receiver_factory=BluetoothReceiver):
        self.request,self.music,self.clock=request,music,clock
        self.lock=threading.RLock();self.stop=threading.Event();self.thread=None
        self.valid=False;self.observed_at=None;self.identity=None;self.generation=0;self.music_generation=None
        self.error=None
        path=Path(home or Path.home())/'.config/echo-display/bluetooth.json'
        try:self.config=load_private_config(path) if path.exists() else dict(DEFAULT_CONFIG)
        except (OSError,ValueError,RuntimeError):
            self.config=dict(DEFAULT_CONFIG);self.error='Bluetooth settings are unreadable; the saved file was preserved.'
        self.receiver=receiver_factory(self.config,self.focus_snapshot)
        if not self.error and self.config['enabled']:self.music.register_auxiliary(self.receiver)

    def focus_snapshot(self):
        now=self.clock()
        with self.lock:
            valid=self.valid and self.observed_at is not None and 0<=now-self.observed_at<=1.0
            with self.music.lock:
                if self.music_generation!=self.music.generation:
                    self.music_generation=self.music.generation;self.generation+=1
                spotify_active=bool(self.music.player and self.music.player.poll() is None) or (
                    self.music.status=='playing' and not self.music.silenced)
                return {'held':self.music.held(),'ducked':self.music.ducked(),
                        'spotify_active':spotify_active,'access_valid':valid,
                        'generation':self.generation,'observed_at':now}

    def refresh_access(self):
        valid=False;identity=None
        try:
            session=self.request('/v1/display/session',timeout=2)
            profile=session.get('profile',{})
            valid=(session.get('role')=='display' and profile.get('mode')=='household'
                   and not profile.get('personal') and not session.get('member'))
            identity=(session.get('receiver_id'),session.get('profile_revision')) if valid else None
        except Exception:
            valid=False
        with self.lock:
            if self.stop.is_set():valid=False;identity=None
            changed=(valid,identity)!=(self.valid,self.identity)
            if changed:self.generation+=1
            self.valid,self.identity,self.observed_at=valid,identity,self.clock()
        if changed or not valid:self.receiver.hard_stop('access')

    def start(self):
        if self.error or not self.config['enabled'] or self.thread:return
        def watch():
            next_start=0.
            while not self.stop.is_set():
                self.refresh_access()
                if not self.stop.is_set() and self.focus_snapshot()['access_valid'] and self.clock()>=next_start:
                    self.receiver.start();next_start=self.clock()+10
                if self.stop.wait(.5):break
        self.thread=threading.Thread(target=watch,name='pi-bluetooth-access',daemon=True);self.thread.start()

    def snapshot(self):
        result=self.receiver.snapshot()
        if self.error:result={**result,'phase':'unavailable','blocked_reason':self.error}
        return result

    def close(self):
        self.stop.set()
        with self.lock:self.valid=False;self.generation+=1
        if self.thread:self.thread.join(3)
        self.receiver.close()
