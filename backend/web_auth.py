"""Loopback browser sessions, bootstrapped with single-use short-lived tickets."""
from hmac import compare_digest
import secrets
from threading import RLock
import time
from fastapi import HTTPException, Request


class BrowserAuth:
    def __init__(self, token):
        self.token = token
        self.tickets = {}
        self.sessions = {}
        self.lock = RLock()

    def _prune(self):
        now = time.monotonic()
        for collection in (self.tickets, self.sessions):
            for key in list(collection):
                if collection[key] < now: collection.pop(key)

    def bearer(self, request: Request):
        if not compare_digest(request.headers.get('authorization', ''), 'Bearer '+self.token):
            raise HTTPException(401, 'Open Echo using tools/open_ui.py on this computer')

    def authorize(self, request: Request):
        if compare_digest(request.headers.get('authorization', ''), 'Bearer '+self.token): return 'device'
        session = request.cookies.get('echo_session', '')
        with self.lock:
            self._prune()
            if session not in self.sessions: raise HTTPException(401, 'Open Echo using tools/open_ui.py on this computer')
        if request.method not in {'GET', 'HEAD'}:
            self.same_origin(request)
        return session

    @staticmethod
    def same_origin(request):
        expected = str(request.base_url).rstrip('/')
        if request.headers.get('origin') not in {None, expected} or request.headers.get('x-echo-request') != '1':
            raise HTTPException(403, 'Use the Echo app on this computer')

    def ticket(self):
        with self.lock:
            self._prune()
            if len(self.tickets) >= 16: self.tickets.pop(next(iter(self.tickets)))
            ticket = secrets.token_urlsafe(32)
            self.tickets[ticket] = time.monotonic()+60
            return ticket

    def exchange(self, ticket):
        with self.lock:
            self._prune()
            if self.tickets.pop(ticket, None) is None: raise HTTPException(401, 'This launch link expired or was already used. Run tools/open_ui.py again.')
            if len(self.sessions) >= 16: self.sessions.pop(next(iter(self.sessions)))
            session = secrets.token_urlsafe(32)
            self.sessions[session] = time.monotonic()+8*3600
            return session

    def logout(self, session):
        with self.lock: self.sessions.pop(session, None)
