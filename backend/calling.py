"""Opt-in LiveKit calls. Provider credentials are encrypted; call state is ephemeral."""
import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import time
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class CallSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    enabled: bool = False
    url: str = Field(default='', max_length=240)
    api_key: SecretStr = SecretStr('')
    api_secret: SecretStr = SecretStr('')
    allowed_displays: list[str] = Field(default_factory=list, max_length=32)

    @field_validator('url')
    @classmethod
    def server(cls, value):
        if not value: return value
        u = urlsplit(value)
        if (u.scheme != 'wss' or not u.hostname or u.username is not None or u.password is not None
                or u.path not in {'', '/'} or u.query or u.fragment
                or not re.fullmatch(r'wss://[A-Za-z0-9.\-\[\]:]+/?', value)):
            raise ValueError('Use a WSS server origin without a path or credentials')
        _ = u.port
        return value.rstrip('/')

    @field_validator('api_key', 'api_secret')
    @classmethod
    def credential(cls, value):
        raw = value.get_secret_value()
        if len(raw) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in raw):
            raise ValueError('Invalid provider credential')
        return value

    @field_validator('allowed_displays')
    @classmethod
    def displays(cls, value):
        if len(set(value)) != len(value) or any(not re.fullmatch('[a-f0-9]{32}', x) for x in value):
            raise ValueError('Select paired displays')
        return value

    @model_validator(mode='after')
    def configured(self):
        if self.enabled and (not self.url or not self.api_key.get_secret_value() or len(self.api_secret.get_secret_value()) < 32):
            raise ValueError('Configure the provider before enabling calls')
        return self


class CallSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    enabled: bool
    url: str = Field(max_length=240)
    api_key: SecretStr = SecretStr('')
    api_secret: SecretStr = SecretStr('')
    allowed_displays: list[str] = Field(max_length=32)
    clear_credentials: bool = False


def raw_settings(settings):
    values = settings.model_dump()
    for key in ('api_key', 'api_secret'): values[key] = getattr(settings, key).get_secret_value()
    return values


class CallStore:
    def __init__(self, root, protector):
        self.path = Path(root) / 'local/echo-calling.json' if root else None
        self.protector, self.lock = protector, RLock()
        self.state, self.error = CallSettings(revision=0), False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size > 100_000: raise ValueError()
                envelope = json.loads(self.path.read_text())
                if envelope['version'] != 1: raise ValueError()
                self.state = CallSettings.model_validate_json(protector.decrypt(base64.b64decode(envelope['protected'], validate=True)))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError): self.error = True

    def require(self):
        if self.error: raise HTTPException(503, 'Call settings are unreadable. Existing storage is preserved.')
        return self.state

    def snapshot(self):
        with self.lock:
            s = self.require()
            return {'revision': s.revision, 'enabled': s.enabled, 'url': s.url,
                    'credentials_saved': bool(s.api_key.get_secret_value() and s.api_secret.get_secret_value()),
                    'allowed_displays': list(s.allowed_displays)}

    def save(self, update):
        with self.lock:
            s = self.require()
            if s.revision != update.revision: raise HTTPException(409, 'Call settings changed. Reload before saving.')
            draft = update.model_dump(exclude={'clear_credentials'})
            for key in ('api_key', 'api_secret'):
                supplied = getattr(update, key).get_secret_value()
                if s.url != update.url.rstrip('/') and not supplied and not update.clear_credentials:
                    raise HTTPException(422, 'Enter both credentials when changing the provider.')
                draft[key] = supplied or ('' if update.clear_credentials else getattr(s, key).get_secret_value())
            draft['revision'] += 1
            try: checked = CallSettings.model_validate(draft)
            except ValueError: raise HTTPException(422, 'Check the WSS server, credentials and selected displays.') from None
            if self.path:
                try:
                    protected = self.protector.encrypt(json.dumps(raw_settings(checked)).encode())
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.path.with_suffix('.tmp')
                    temporary.write_text(json.dumps({'version': 1, 'protected': base64.b64encode(protected).decode()}))
                    temporary.replace(self.path)
                except (OSError, RuntimeError): raise HTTPException(503, 'Call settings could not be saved.') from None
            self.state = checked
            return self.snapshot()


def jwt(settings, identity, grants, now, ttl=60):
    def part(value): return base64.urlsafe_b64encode(value).rstrip(b'=')
    body = {'iss': settings.api_key.get_secret_value(), 'sub': identity, 'nbf': int(now)-5,
            'exp': int(now)+ttl, 'video': grants}
    content = b'.'.join(part(json.dumps(v, separators=(',', ':')).encode()) for v in ({'alg': 'HS256', 'typ': 'JWT'}, body))
    signature = hmac.new(settings.api_secret.get_secret_value().encode(), content, hashlib.sha256).digest()
    return (content+b'.'+part(signature)).decode()


class LiveKit:
    def __init__(self, private_origin='', *, transport=None):
        # This binding comes from deployment, never the owner settings/API.
        # A noncanonical alias must not broaden the private transport boundary.
        if not isinstance(private_origin, str):
            raise ValueError('Use an empty or canonical WSS private calling origin')
        if private_origin:
            try:
                parsed = urlsplit(private_origin)
                if (len(private_origin) > 240 or not re.fullmatch(r'wss://[A-Za-z0-9.\-\[\]:]+', private_origin)
                        or parsed.scheme != 'wss' or not parsed.hostname
                        or parsed.username is not None or parsed.password is not None
                        or parsed.path or parsed.query or parsed.fragment):
                    raise ValueError()
                hostname = parsed.hostname
                try:
                    address = ipaddress.ip_address(hostname)
                    host = '['+address.compressed+']' if address.version == 6 else str(address)
                except ValueError:
                    if (len(hostname) > 253 or re.fullmatch(r'[0-9.]+', hostname)
                            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                                       for label in hostname.split('.'))):
                        raise ValueError() from None
                    host = hostname
                port = parsed.port
                if port is not None and not 1 <= port <= 65535:
                    raise ValueError()
                canonical = 'wss://'+host+(':'+str(port) if port not in (None,443) else '')
                if private_origin != canonical:
                    raise ValueError()
            except ValueError:
                raise ValueError('Use an empty or canonical WSS private calling origin') from None
        self.private_origin, self.transport = private_origin, transport

    def private_transport(self, settings):
        return bool(self.private_origin and settings.url == self.private_origin)

    def request(self, settings, method, body):
        token = jwt(settings, 'echo-server', {'roomCreate': True}, time.time())
        origin = 'http://echo-calling:7880' if self.private_transport(settings) else 'https://'+urlsplit(settings.url).netloc
        try:
            with httpx.Client(timeout=5, trust_env=False, follow_redirects=False, transport=self.transport) as client:
                response = client.post(origin+'/twirp/livekit.RoomService/'+method,
                                       headers={'Authorization': 'Bearer '+token}, json=body)
            if method == 'DeleteRoom' and response.status_code == 404: return
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502, 'The calling server did not accept the request. Check its URL, credentials and availability.') from None


class Calling:
    def __init__(self, store, displays, provider=None, clock=time.time, enabled=True):
        self.store, self.displays = store, displays
        self.provider, self.clock, self.enabled = provider or LiveKit(), clock, enabled
        self.lock, self.calls = RLock(), {}

    def permitted(self, principal):
        settings = self.store.require()
        profile = self.displays.profile_for(principal)
        if profile['profile']['mode'] != 'household' or principal == 'round': return False
        return not principal.startswith('display:') or principal[8:] in settings.allowed_displays

    def status(self, principal):
        with self.lock:
            s = self.store.require()
            return {'enabled': self.enabled and s.enabled, 'allowed': self.permitted(principal),
                    'provider': 'LiveKit', 'max_minutes': 15, 'invite_seconds': 120}

    def require(self, principal):
        if not self.enabled or not self.store.require().enabled: raise HTTPException(409, 'Calling is not configured or is turned off.')
        if not self.permitted(principal): raise HTTPException(403, 'The owner has not enabled calling for this display.')

    def revision(self, principal): return self.displays.profile_for(principal)['profile_revision']

    def peer(self, principal, client):
        return {'principal': principal, 'client': client, 'revision': self.revision(principal),
                'identity': secrets.token_hex(16), 'seen': self.clock()}

    def credential(self, call, peer):
        # Clients cannot create/manage rooms, send data or publish screen sharing.
        grants = {'roomJoin': True, 'room': call['room'], 'canSubscribe': True, 'canPublish': True,
                  'canPublishData': False, 'canPublishSources': ['microphone', 'camera']}
        result = {'id': call['id'], 'url': call['settings'].url,
                  'token': jwt(call['settings'], peer['identity'], grants, self.clock()),
                  'expires_at': call['expires'], 'invite_expires_at': call['invite_expires']}
        if getattr(self.provider, 'private_transport', lambda settings: False)(call['settings']) is True:
            result['private_transport'] = True
        return result

    def start(self, principal, client):
        with self.lock:
            self.require(principal)
            if len(self.calls) >= 4: raise HTTPException(409, 'Call capacity reached. End a call or wait for cleanup.')
            self.idle(principal, client)
            identifier, code = secrets.token_hex(16), secrets.token_hex(16)
            settings = self.store.state.model_copy(deep=True)
            now = self.clock()
            call = {'id': identifier, 'room': 'echo-'+identifier, 'code_hash': hashlib.sha256(code.encode()).digest(),
                    'settings': settings, 'expires': now+900, 'invite_expires': now+120,
                    'peers': [self.peer(principal, client)], 'ending': False, 'retry_at': 0}
            # Remember even a timed-out CreateRoom so its possibly created room gets cleaned up.
            self.calls[identifier] = call
            try:
                self.provider.request(settings, 'CreateRoom', {'name': call['room'], 'empty_timeout': 120,
                                                             'departure_timeout': 10, 'max_participants': 2})
            except HTTPException:
                call['ending'] = True
                raise
            return {**self.credential(call, call['peers'][0]), 'code': code}

    def idle(self, principal, client):
        if any(any(p['principal'] == principal and (p['client'] == client or principal.startswith('display:'))
                       for p in c['peers']) for c in self.calls.values()):
            raise HTTPException(409, 'This endpoint already has a call. End it first.')

    def join(self, principal, client, code):
        with self.lock:
            self.require(principal)
            self.idle(principal, client)
            digest = hashlib.sha256(code.encode()).digest()
            call = next((c for c in self.calls.values() if hmac.compare_digest(c['code_hash'], digest)), None)
            if not call or call['ending'] or len(call['peers']) != 1 or self.clock() >= call['invite_expires']:
                raise HTTPException(410, 'This invitation expired or was already used. Ask for a new code.')
            host=call['peers'][0]
            if (self.clock()-host['seen']>20 or not self.permitted(host['principal'])
                    or host['revision']!=self.revision(host['principal'])):
                call['ending']=True
                raise HTTPException(410, 'The person who invited you is no longer available.')
            peer = self.peer(principal, client)
            call['peers'].append(peer)
            return self.credential(call, peer)

    def find(self, identifier, principal, client):
        call = self.calls.get(identifier)
        peer = next((p for p in call['peers'] if p['principal'] == principal and p['client'] == client), None) if call else None
        if not peer: raise HTTPException(404, 'Call not found.')
        return call, peer

    def pulse(self, identifier, principal, client):
        with self.lock:
            self.require(principal)
            call, peer = self.find(identifier, principal, client)
            if call['ending'] or self.clock() >= call['expires'] or peer['revision'] != self.revision(principal):
                raise HTTPException(410, 'This call has ended or access changed.')
            peer['seen'] = self.clock()
            return {'active': True, 'joined': len(call['peers']) == 2, 'expires_at': call['expires']}

    def end(self, identifier, principal, client):
        with self.lock:
            call, _ = self.find(identifier, principal, client)
            call['ending'] = True
            self.delete(call)
            return {'ended': True}

    def delete(self, call):
        self.provider.request(call['settings'], 'DeleteRoom', {'room': call['room']})
        self.calls.pop(call['id'], None)

    def tick(self, close=False):
        with self.lock:
            now = self.clock()
            for call in list(self.calls.values()):
                try:
                    invalid = not self.store.require().enabled or any(
                        not self.permitted(p['principal']) or self.revision(p['principal']) != p['revision'] for p in call['peers'])
                except (HTTPException, RuntimeError): invalid = True
                expired = now >= call['expires'] or (len(call['peers']) == 1 and now >= call['invite_expires'])
                stale = any(now-p['seen'] > 20 for p in call['peers'])
                if close or invalid or expired or stale: call['ending'] = True
                if call['ending'] and now >= call['retry_at']:
                    try: self.delete(call)
                    except HTTPException: call['retry_at'] = now+10

    def origins(self):
        try:
            s = self.store.require()
            if not s.enabled or not self.enabled:return []
            origins=[s.url, 'https://'+urlsplit(s.url).netloc]
            # Cloud may hand off/reconnect to its regional endpoints. Self-hosted
            # servers receive only the exact origin selected by the owner.
            if (urlsplit(s.url).hostname or '').endswith('.livekit.cloud'):
                origins+=['wss://*.livekit.cloud','https://*.livekit.cloud']
            return origins
        except HTTPException: return []


class CallClient(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    client: str = Field(pattern=r'^[a-f0-9]{32}$')


class JoinCall(CallClient):
    code: str = Field(pattern=r'^[a-f0-9]{32}$')


def install(app, calling, authorize, owner):
    from fastapi import Depends
    app.state.calling = calling

    @app.get('/v1/calling')
    def status(principal=Depends(authorize)): return calling.status(principal)

    @app.get('/v1/calling/settings', dependencies=[Depends(owner)])
    def settings(): return {**calling.store.snapshot(), 'displays': calling.displays.snapshot()}

    @app.put('/v1/calling/settings', dependencies=[Depends(owner)])
    def save(body: CallSettingsUpdate):
        with calling.lock:
            if calling.calls: raise HTTPException(409, 'End active calls before changing their provider or access.')
            known = {d['id'] for d in calling.displays.snapshot()}
            if not set(body.allowed_displays) <= known: raise HTTPException(422, 'Reload the list of paired displays.')
            return calling.store.save(body)

    @app.post('/v1/calling/start')
    def start(body: CallClient, principal=Depends(authorize)): return calling.start(principal, body.client)

    @app.post('/v1/calling/join')
    def join(body: JoinCall, principal=Depends(authorize)): return calling.join(principal, body.client, body.code)

    @app.post('/v1/calling/{identifier}/pulse')
    def pulse(identifier: str, body: CallClient, principal=Depends(authorize)): return calling.pulse(identifier, principal, body.client)

    @app.post('/v1/calling/{identifier}/end')
    def end(identifier: str, body: CallClient, principal=Depends(authorize)): return calling.end(identifier, principal, body.client)
