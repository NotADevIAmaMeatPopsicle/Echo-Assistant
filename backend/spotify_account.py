"""Owner-only Spotify setup through Music Assistant's persistent provider store.

Spotify's registered Music Assistant redirect remains unchanged. Its hosted bounce
returns to an expiring Echo capability, which forwards the code to the one active
Music Assistant setup flow. PKCE and token storage remain in Music Assistant.
"""
import re
import secrets
from threading import RLock, Thread
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .group_music import GroupMusicUnavailable


class SetupValues(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    step: str = Field(max_length=80)
    values: dict[str, str | bool] = Field(default_factory=dict, max_length=8)


class SpotifyAccount:
    fields = {'playback_backend', 'playback_auth_method', 'playback_callback_url',
              'use_developer_key', 'client_id'}

    def __init__(self, music, clock=time.monotonic):
        self.music, self.clock = music, clock
        self.lock = RLock()
        self.flow = None

    def providers(self):
        values = self.music.request('config/providers', provider_domain='spotify')
        if not isinstance(values, list): raise GroupMusicUnavailable('Spotify account status is unavailable')
        return [v for v in values if isinstance(v, dict) and v.get('domain') == 'spotify']

    def status(self):
        providers = self.providers()
        return {'connected': any(p.get('enabled', True) and not p.get('last_error') for p in providers),
                'configured': bool(providers),
                'message': 'Account saved in Music Assistant.' if providers else 'Connect Spotify once to browse your library on Echo.'}

    def current(self):
        f = self.flow
        if not f or f['expires'] < self.clock() or f['revision'] != self.music.revision:
            raise HTTPException(409, 'Spotify setup expired or the music server changed. Start again.')
        return f

    def job(self, f, command, **args):
        f['busy'] = True
        def run():
            try:
                step = self.music.request(command, _timeout=125, _setup=True, **args)
                if not isinstance(step, dict): raise GroupMusicUnavailable('Spotify setup returned no step')
                with self.lock:
                    if self.flow is f:
                        f['step'] = step
                        f['id'] = step.get('flow_id')
            except GroupMusicUnavailable as error:
                with self.lock: f['error'] = str(error)
            except ValueError:
                with self.lock: f['error'] = 'Spotify setup could not be confirmed. Close setup and try again.'
            finally:
                with self.lock: f['busy'] = False
        Thread(target=run, daemon=True, name='spotify-setup').start()

    def start(self, origin):
        with self.lock:
            if self.flow and self.flow['expires'] > self.clock() and self.flow['busy']:
                raise HTTPException(409, 'Spotify setup is already starting')
            if (self.flow and self.flow.get('id') and self.flow['expires'] > self.clock()
                    and (self.flow.get('step') or {}).get('type') not in {'finish','abort'}):
                raise HTTPException(409, 'Resume or close the current Spotify setup first')
            providers = self.providers()
            if len(providers) > 1: raise ValueError('Manage multiple Spotify accounts in Music Assistant')
            f = dict(origin=origin, revision=self.music.revision, expires=self.clock()+1200,
                     id=None, step=None, nonce=None, callback_step=None, used=False, error=None)
            self.flow = f
            if providers: self.job(f, 'config/providers/reconfigure', instance_id=providers[0]['instance_id'])
            else: self.job(f, 'config/providers/setup', provider_domain='spotify')
            return {'type': 'progress', 'title': 'Opening Spotify sign-in…'}

    def safe_step(self, f):
        if f.get('error'): return {'type': 'abort', 'title': f['error']}
        if f.get('busy') or not f.get('step'): return {'type': 'progress', 'title': 'Connecting to Music Assistant…'}
        step = f['step']
        result = {k: step.get(k) for k in ('type', 'step_id', 'title', 'description', 'progress_text', 'last_step', 'reason')}
        result['entries'] = []
        for entry in step.get('entries', [])[:12]:
            if entry.get('key') not in self.fields: continue
            e = {k: entry.get(k) for k in ('key', 'type', 'label', 'description', 'required', 'default_value')}
            e['value'] = entry.get('value') if entry['key'] in {'playback_backend', 'playback_auth_method', 'use_developer_key'} else ''
            e['options'] = [{k: o.get(k) for k in ('title', 'value')} for o in (entry.get('options') or [])[:16]]
            if entry['key'] == 'playback_backend':
                e['options'] = [o for o in e['options'] if o['value'] == 'librespot']
                e['value'] = 'librespot'
            if entry['key'] == 'playback_auth_method':
                # Docker's private network often cannot advertise the pairing device.
                e['value'] = 'browser'
                e['options'].sort(key=lambda option: option['value'] != 'browser')
                for option in e['options']:
                    option['title'] = ('Use a web browser (recommended for Echo)' if option['value']=='browser'
                                       else 'Use Spotify app discovery on the same network')
                result['description'] = ('Approve playback in a web browser. This works when Music Assistant '
                    'runs inside Docker and its temporary pairing device cannot appear in Spotify. '
                    'App discovery is also available for servers on the same network as your phone.')
            result['entries'].append(e)
        result['error'] = 'Review these details and try again.' if step.get('errors') else ''
        url = step.get('url')
        if not url and step.get('step_id') == 'playback_browser':
            retry = re.search(r'https://accounts\.spotify\.com/authorize\?[^\s)]+', step.get('description') or '')
            if retry:
                url = retry[0]
                result['description'] = ('Choose Continue to Spotify to approve playback. If the final localhost page '
                    'does not load, copy its complete address from the browser and paste it below. '
                    'That address contains the one-time authorization code.')
        if url:
            parts = urlsplit(url)
            if parts.scheme != 'https' or parts.netloc != 'accounts.spotify.com' or parts.path != '/authorize':
                raise ValueError('Spotify returned an unsupported sign-in address')
            pairs = dict(parse_qsl(parts.query))
            callback = urlsplit(pairs.get('state', ''))
            if callback.path == '/setup_flow/callback/'+str(f['id']):
                if not re.fullmatch(r'[a-f0-9]{32}', str(f['id'])): raise ValueError('Invalid setup flow')
                if pairs.get('redirect_uri') != 'https://music-assistant.io/callback': raise ValueError('Unexpected Spotify redirect')
                if f['callback_step'] != url:
                    f.update(nonce=secrets.token_hex(32), callback_step=url, used=False)
                pairs['state'] = f['origin']+'/v1/music/spotify/callback/'+f['nonce']
                url = urlunsplit(parts._replace(query=urlencode(pairs)))
            result['url'] = url
        return result

    def get(self):
        with self.lock:
            f = self.current()
            if not f.get('busy') and f.get('id') and (f.get('step') or {}).get('type') not in {'finish','abort'}:
                f['step'] = self.music.request('config/flows/get', flow_id=f['id'], _setup=True)
            return self.safe_step(f)

    def submit(self, body):
        with self.lock:
            f = self.current()
            step = f.get('step') or {}
            if f.get('busy') or step.get('type') != 'form' or step.get('step_id') != body.step:
                raise HTTPException(409, 'This Spotify setup step changed. Refresh it.')
            fields = {e['key']: e for e in step.get('entries', []) if e.get('key') in self.fields}
            if not set(body.values) <= set(fields): raise ValueError('Unsupported Spotify setup fields')
            for key, value in body.values.items():
                if isinstance(value, str) and (len(value)>4096 or any(ord(c)<32 for c in value)):
                    raise ValueError('Invalid Spotify setup value')
                if fields[key].get('type') == 'boolean' and type(value) is not bool: raise ValueError('Choose yes or no')
                choices = fields[key].get('options')
                if choices and value not in {o.get('value') for o in choices}: raise ValueError('Choose one of the available options')
            if body.values.get('playback_backend', 'librespot') != 'librespot': raise ValueError('Echo uses the librespot playback backend')
            self.job(f, 'config/flows/submit', flow_id=f['id'], values=body.values)
            return {'type': 'progress', 'title': 'Saving this step…'}

    def abort(self):
        with self.lock:
            f = self.flow
            if f and f.get('busy'): raise HTTPException(409, 'Wait for the current setup step to finish')
            self.flow = None
            if (f and f.get('id') and f['revision'] == self.music.revision
                    and (f.get('step') or {}).get('type') not in {'finish','abort'}):
                self.music.request('config/flows/abort', flow_id=f['id'], _setup=True)
            return {'closed': True}

    def callback(self, nonce, params):
        with self.lock:
            f = self.current()
            if not f.get('nonce') or not secrets.compare_digest(nonce, f['nonce']) or f['used']:
                raise HTTPException(410, 'This sign-in link expired or was already used')
            step = self.music.request('config/flows/get', flow_id=f['id'], _setup=True)
            if step.get('type') != 'external' or step.get('url') != f['callback_step']:
                raise HTTPException(409, 'The Spotify sign-in step changed')
            values = {k: params[k] for k in ('code', 'error') if k in params}
            if len(values)!=1 or any(not v or len(v)>4096 for v in values.values()): raise ValueError('Invalid Spotify callback')
            f['used'] = True
            try:
                with httpx.Client(transport=self.music.transport, timeout=8, trust_env=False, follow_redirects=False) as client:
                    response = client.get(self.music.config.url+'/setup_flow/callback/'+f['id'], params=values)
                    response.raise_for_status()
            except httpx.HTTPError: raise GroupMusicUnavailable('Spotify callback could not be confirmed. Restart sign-in.') from None


def install(app, music, authorize, owner, call):
    account = SpotifyAccount(music)
    app.state.spotify_account = account

    @app.get('/v1/music/spotify', dependencies=[Depends(authorize)])
    def status(): return call(account.status)

    @app.post('/v1/music/spotify/setup', dependencies=[Depends(owner)])
    def start(request: Request):
        origin = request.headers.get('origin') or str(request.base_url).rstrip('/')
        parsed = urlsplit(origin)
        if (parsed.scheme not in {'http','https'} or parsed.netloc != request.headers.get('host')
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise HTTPException(400, 'Open Spotify setup from this Echo website')
        return call(lambda: account.start(origin))

    @app.get('/v1/music/spotify/setup', dependencies=[Depends(owner)])
    def get(): return call(account.get)

    @app.post('/v1/music/spotify/setup/step', dependencies=[Depends(owner)])
    def submit(body: SetupValues): return call(lambda: account.submit(body))

    @app.delete('/v1/music/spotify/setup', dependencies=[Depends(owner)])
    def abort(): return call(account.abort)

    @app.get('/v1/music/spotify/callback/{nonce}')
    def callback(nonce: str, request: Request):
        call(lambda: account.callback(nonce, request.query_params))
        return HTMLResponse('<!doctype html><title>Spotify connected</title><h1>Sign-in received.</h1><p>Return to Echo to finish connecting Spotify.</p>',
                            headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
