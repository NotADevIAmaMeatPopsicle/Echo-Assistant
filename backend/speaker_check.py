"""A single cancellable saved-voice sample, owned by the live speaker bridge.

Only bounded health metadata is persisted. The sample text is fixed, and PCM
remains in the existing speech worker and speaker buffers.
"""
from contextlib import contextmanager
import json
import re
import time
from uuid import uuid4
from .lifecycle import _acquire_lock, _release_lock
from .voice_status import voice_status

SAMPLE = 'Hello. I am Echo. Everything sounds better when it actually works.'
ACTIVE = {'queued','generating','playing'}
STATES = ACTIVE | {'complete','cancelled','failed'}


class SpeakerCheck:
    def __init__(self, root):
        self.root = root
        self.path = root/'local/speaker-check.json' if root else None

    @contextmanager
    def locked(self):
        if self.root is None: raise ValueError('The speaker is not connected')
        lock = _acquire_lock(self.root/'local','speaker-check')
        if lock is None: raise ValueError('Speaker check is busy. Try again.')
        try: yield
        finally: _release_lock(lock)

    def _read(self):
        try:
            data=self.path.read_bytes()
            if len(data)>2048: return None
            value=json.loads(data)
            if (not isinstance(value,dict) or value.get('status') not in STATES
                    or not all(isinstance(value.get(k),str) and re.fullmatch('[a-f0-9]{32}',value[k]) for k in ('id','run_id'))
                    or type(value.get('requested_at')) not in (float,int)):
                return None
            return value
        except (OSError,ValueError,TypeError,AttributeError): return None

    def _write(self,value):
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value));temporary.replace(self.path)

    def _owner(self):
        lock=_acquire_lock(self.root/'local','voice')
        if lock is not None: _release_lock(lock);return None
        try: return json.loads((self.root/'local/voice-process.json').read_text()).get('run_id')
        except (OSError,ValueError,TypeError,AttributeError): return None

    @staticmethod
    def ready(status):
        try:
            return (status.get('status')=='armed' and not status.get('muted')
                    and not status.get('speaker',{}).get('active')
                    and status.get('music',{}).get('status')!='playing'
                    and 1<=int(status.get('device',{}).get('volume',99))<=3)
        except (ValueError,TypeError): return False

    def state(self):
        with self.locked():
            value=self._read()
            if value is None: return {'status':'idle'}
            if value['status'] in ACTIVE and (value['run_id']!=self._owner() or not 0<=time.time()-value['requested_at']<60):
                return {'id':value['id'],'status':'failed','reason':'Speaker connection or check expired'}
            return {k:v for k,v in value.items() if k not in {'run_id','requested_at'}}

    def request(self):
        with self.locked():
            value=self._read()
            owner=self._owner()
            if not owner or not self.ready(voice_status(self.root)):
                raise ValueError('Wait for Echo to be idle and unmuted, with speaker volume at 1–3%.')
            if value and value['status'] in ACTIVE and value['run_id']==owner and 0<=time.time()-value['requested_at']<60:
                raise ValueError('A speaker check is already running')
            value={'id':uuid4().hex,'run_id':owner,'status':'queued','requested_at':time.time()}
            self._write(value)
            return {'id':value['id'],'status':'queued'}

    def cancel(self,identifier):
        with self.locked():
            value=self._read()
            if not value or value['id']!=identifier: raise ValueError('Speaker check was not found')
            if value['status'] in ACTIVE:
                value['cancel_requested']=True;self._write(value)
            return {'id':identifier,'status':value['status'],'cancel_requested':bool(value.get('cancel_requested'))}

    def claim(self,owner,status):
        with self.locked():
            value=self._read()
            if not value or value['status']!='queued': return None
            if value['run_id']!=owner or not 0<=time.time()-value['requested_at']<15:
                value['status']='failed';value['reason']='Speaker connection or check expired'
            elif value.get('cancel_requested'):
                value['status']='cancelled'
            elif not self.ready(status):
                value['status']='failed';value['reason']='Echo became busy or the volume changed'
            else:
                value['status']='generating';self._write(value);return value['id']
            self._write(value);return None

    def cancelled(self,identifier,owner):
        with self.locked():
            value=self._read()
            return (not value or value['id']!=identifier or value['run_id']!=owner
                    or value.get('cancel_requested') or not 0<=time.time()-value['requested_at']<55)

    def update(self,identifier,state,*,frames=0,underruns=0,reason=''):
        if state not in STATES: raise ValueError('Invalid speaker check status')
        with self.locked():
            value=self._read()
            if not value or value['id']!=identifier or value['status'] not in ACTIVE:return
            value.update(status=state,frames=int(frames),underruns=int(underruns))
            if reason:value['reason']=reason[:160]
            self._write(value)
