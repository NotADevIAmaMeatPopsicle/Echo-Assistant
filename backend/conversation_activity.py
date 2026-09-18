"""Bounded, volatile conversation progress. Never stores prompts or replies."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Event, RLock
import time
from uuid import uuid4

CAPTIONS = {
    'starting': 'Connecting to Echo', 'thinking': 'Preparing your answer',
    'checking': 'Checking your home', 'acting': 'Controlling your home',
    'searching': 'Requesting a sourced answer', 'completed': 'Reply ready',
    'failed': 'Echo could not finish this request', 'cancelled': 'Request stopped',
    'stopping': 'Stopping the request', 'unconfirmed': 'Agent stop not confirmed',
}


class ConversationBusy(ValueError):
    pass


@dataclass
class ConversationActivity:
    id: str = field(default_factory=lambda: uuid4().hex)
    cancel: Event = field(default_factory=Event)
    state: str = 'starting'
    started: float = field(default_factory=time.time)
    finished: float | None = None
    events: list = field(default_factory=list)
    receipts: list = field(default_factory=list)
    stop_unconfirmed: bool = False
    lock: RLock = field(default_factory=RLock)

    def progress(self, state):
        if state not in CAPTIONS: return
        with self.lock:
            if self.finished is not None: return
            if state == 'unconfirmed': self.stop_unconfirmed = True
            # A runtime completion is not yet a validated Echo result.
            if state in {'completed', 'failed', 'cancelled'}: return
            if self.cancel.is_set() and state != 'unconfirmed': state = 'stopping'
            if self.events and self.events[-1]['state'] == state: return
            self.state = state
            self.events = [*self.events[-15:], {'state': state, 'caption': CAPTIONS[state], 'time': time.time()}]

    def request_stop(self):
        with self.lock:
            if self.finished is None:
                self.cancel.set()
                self.progress('stopping')
            return self.snapshot()

    def finish(self, result):
        with self.lock:
            if self.finished is not None: return
            result = result if isinstance(result, dict) else {}
            self.state = 'unconfirmed' if self.stop_unconfirmed else 'cancelled' if self.cancel.is_set() else (
                'completed' if result.get('status') == 'complete' else 'failed')
            # Retain action receipts for reconciliation after a cancelled tab; no text history.
            self.receipts = deepcopy(result.get('home_actions', []))[:12]
            self.finished = time.time()
            self.events = [*self.events[-15:], {'state': self.state, 'caption': CAPTIONS[self.state], 'time': self.finished}]

    def snapshot(self):
        with self.lock:
            return {'id': self.id, 'state': self.state, 'caption': CAPTIONS[self.state],
                    'active': self.finished is None, 'cancel_requested': self.cancel.is_set(),
                    'started': self.started, 'finished': self.finished,
                    'events': deepcopy(self.events), 'home_actions': deepcopy(self.receipts)}


class Conversations:
    def __init__(self):
        self.lock = RLock()
        self.sessions = OrderedDict()

    def _prune(self):
        for session, job in list(self.sessions.items()):
            if job.finished is not None and time.time() - job.finished > 1800:
                self.sessions.pop(session)

    def begin(self, session):
        with self.lock:
            self._prune()
            previous = self.sessions.get(session)
            if previous and previous.finished is None:
                raise ConversationBusy('A request is already running in this chat. Stop it or wait for its reply.')
            if session not in self.sessions and len(self.sessions) >= 16:
                expired = next((key for key, job in self.sessions.items() if job.finished is not None), None)
                if expired is None: raise ConversationBusy('Echo has too many active requests. Try again shortly.')
                self.sessions.pop(expired)
            job = ConversationActivity()
            job.progress('starting')
            self.sessions[session] = job
            self.sessions.move_to_end(session)
            return job

    def snapshot(self, session):
        with self.lock:
            self._prune()
            job = self.sessions.get(session)
            return job.snapshot() if job else {'state': 'idle', 'active': False, 'events': []}

    def stop(self, session, identifier):
        with self.lock:
            self._prune()
            job = self.sessions.get(session)
            if not job or job.id != identifier: raise KeyError('Conversation not found')
            return job.request_stop()

    def clear(self, session):
        with self.lock:
            job = self.sessions.get(session)
            if job and job.finished is None: job.request_stop()
            else: self.sessions.pop(session, None)
