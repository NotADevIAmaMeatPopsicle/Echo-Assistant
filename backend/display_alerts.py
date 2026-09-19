"""Endpoint-owned alarm delivery; receipts are tied to a particular occurrence."""
from hmac import compare_digest
import secrets
from threading import RLock
import time

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class Claim(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    occurrence: str = Field(min_length=1, max_length=80)


class Receipt(Claim):
    token: str = Field(pattern=r'^[a-f0-9]{64}$')
    outcome: Literal['played', 'interrupted', 'failed']


class DisplayAlerts:
    def __init__(self, assistant, schedules, clock=time.monotonic):
        self.assistant, self.schedules, self.clock = assistant, schedules, clock
        self.lock = RLock()
        self.claims = {}

    def timers(self):
        return self.assistant.timer_states()+self.schedules.timer_states()

    def eligible(self, item):
        quiet = self.schedules.snapshot()
        quiet_blocks = quiet['quiet_active'] and not (
            item.get('kind', 'alarm') == 'alarm' and quiet['quiet']['alarms_override'])
        return item['finished'] and not item['notified'] and item['late_seconds'] <= 900 and not quiet_blocks

    def item(self, endpoint, identifier, occurrence=None):
        return next((i for i in self.timers() if i['id'] == identifier and
                     i['destination'] == endpoint and (occurrence is None or i['occurrence'] == occurrence)), None)

    def inbox(self, endpoint):
        with self.lock:
            self.claims = {k: v for k, v in self.claims.items() if self.clock()-v['created'] < 120}
            items = [i for i in self.timers() if i['destination'] == endpoint]
            return {'destination': endpoint, 'items': [{**i, 'audible': self.eligible(i)} for i in items]}

    def claim(self, endpoint, identifier, occurrence):
        with self.lock:
            item = self.item(endpoint, identifier, occurrence)
            if not item or not self.eligible(item): raise HTTPException(409, 'Alert is no longer due for this display')
            self.inbox(endpoint)  # Prune expired claims before allocating.
            previous = self.claims.get(identifier)
            if previous and previous['occurrence'] == occurrence and self.clock() < previous['until']:
                raise HTTPException(409, 'This alert is already being delivered')
            token = secrets.token_hex(32)
            self.claims[identifier] = {'endpoint': endpoint, 'occurrence': occurrence, 'token': token,
                                      'created': self.clock(), 'until': self.clock()+30, 'played': False}
            return {'token': token, 'occurrence': occurrence, 'expires_in': 30}

    def valid(self, endpoint, identifier, occurrence, token):
        with self.lock:
            claim = self.claims.get(identifier)
            item = self.item(endpoint, identifier, occurrence)
            return bool(claim and claim['endpoint'] == endpoint and claim['occurrence'] == occurrence
                        and compare_digest(claim['token'], token) and claim['until'] > self.clock()
                        and item and self.eligible(item))

    def receipt(self, endpoint, identifier, body):
        with self.lock:
            claim = self.claims.get(identifier)
            if not claim or claim['endpoint'] != endpoint or claim['occurrence'] != body.occurrence or not compare_digest(claim['token'], body.token):
                raise HTTPException(409, 'Alert delivery has expired')
            if claim['played']: return {'accepted': True}  # Safe retry after a lost response.
            if not self.valid(endpoint, identifier, body.occurrence, body.token):
                raise HTTPException(409, 'Alert was dismissed, snoozed or expired')
            if body.outcome == 'played':
                # Check the occurrence again under the storage lock: a snooze may
                # race the player finishing. Never acknowledge its future alarm.
                ok = self.assistant.acknowledge_timer(identifier, occurrence=body.occurrence, destination=endpoint)
                if not ok: ok = self.schedules.event_action(identifier, 'ack', occurrence=body.occurrence, destination=endpoint)
                if not ok: raise HTTPException(409, 'Alert changed before delivery completed')
                claim['played'] = True
            else:
                claim['until'] = self.clock()+15  # Bounded retry backoff, no tight sound loop.
            return {'accepted': True}


def install(app, alerts, authorize):
    def endpoint(session=Depends(authorize)):
        if not session.startswith('display:'): raise HTTPException(403, 'Use a paired display for its alerts')
        return session

    @app.get('/v1/display/alert-settings', dependencies=[Depends(authorize)])
    def settings():
        return {'supported': False, 'status': 'Pi alert setup requires the local Pi bridge'}

    @app.get('/v1/display/alerts')
    def inbox(session=Depends(endpoint)): return alerts.inbox(session)

    @app.post('/v1/display/alerts/{identifier}/claim')
    def claim(identifier: str, body: Claim, session=Depends(endpoint)):
        return alerts.claim(session, identifier, body.occurrence)

    @app.post('/v1/display/alerts/{identifier}/check')
    def check(identifier: str, body: Receipt, session=Depends(endpoint)):
        return {'valid': alerts.valid(session, identifier, body.occurrence, body.token)}

    @app.post('/v1/display/alerts/{identifier}/receipt')
    def receipt(identifier: str, body: Receipt, session=Depends(endpoint)):
        return alerts.receipt(session, identifier, body)

    @app.post('/v1/timers/{identifier}/snooze')
    def snooze(identifier: str, session=Depends(authorize)):
        if not alerts.assistant.snooze_timer(identifier): raise HTTPException(404, 'Finished timer not found')
        return {'snoozed': True}
