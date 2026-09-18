"""No keys, home actions or audio: real loopback disconnects and provider deadlines."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from threading import Event, Thread
import time
import unittest

import httpx
import uvicorn

from backend.agent import Provider, ProviderUnavailable
from backend.app import create_app
from backend.settings import EchoSettings, SettingsStore, SettingsUpdate


class ProviderDeadlineTests(unittest.TestCase):
    def test_dribbling_response_has_total_deadline_and_closes(self):
        closed = Event()

        class Drip(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    await asyncio.sleep(.02)
                    yield b' '

            async def aclose(self): closed.set()

        provider = Provider(httpx.MockTransport(lambda req: httpx.Response(200, stream=Drip())), timeout=.15)
        started = time.monotonic()
        with self.assertRaisesRegex(ProviderUnavailable, 'too long'):
            provider.complete(EchoSettings(provider='local', model='synthetic'), {}, [{'role':'user', 'content':'Hello'}])
        self.assertLess(time.monotonic()-started, 1)
        self.assertTrue(closed.is_set())

    def test_cancelled_request_does_not_connect(self):
        cancel = Event(); cancel.set(); calls = []
        provider = Provider(httpx.MockTransport(lambda req: calls.append(req)))
        with self.assertRaisesRegex(ProviderUnavailable, 'cancelled'):
            provider.models(EchoSettings(provider='local'), {}, cancel=cancel)
        self.assertEqual(calls, [])


class SlowLocalProvider:
    """First request waits for its TCP peer to close; following requests answer."""
    def __init__(self):
        self.entered = Event(); self.closed = Event(); self.count = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def do_GET(self): self.answer()
            def do_POST(self): self.answer()

            def answer(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                owner.count += 1
                if owner.count == 1:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b' '); self.wfile.flush()
                    owner.entered.set()
                    self.connection.settimeout(3)
                    try:
                        if self.connection.recv(1) == b'': owner.closed.set()
                    except ConnectionResetError: owner.closed.set()
                    except OSError: pass
                    return
                body = json.dumps({'choices':[{'message':{'content':'Synthetic reply.'}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)


class RunningApi:
    def __init__(self, provider):
        store = SettingsStore()
        store.save(SettingsUpdate(settings=EchoSettings(provider='local', model='synthetic',
            local_url=f'http://127.0.0.1:{provider.server.server_port}/v1')))
        self.app = create_app('t'*32, settings_store=store)
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.url = f'http://127.0.0.1:{self.socket.getsockname()[1]}'
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level='critical', access_log=False, ws='none'))
        self.thread = Thread(target=self.server.run, kwargs={'sockets':[self.socket]}, daemon=True)
        self.thread.start()
        until = time.monotonic()+5
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() >= until: raise RuntimeError('Test API did not start')
            time.sleep(.01)

    def close(self):
        self.app.state.speech_stop.set(); self.server.should_exit = True
        self.thread.join(5); self.socket.close()
        if self.thread.is_alive(): raise RuntimeError('Test API did not stop')


class ConversationDisconnectTests(unittest.TestCase):
    auth = {'Authorization':'Bearer '+'t'*32}

    def setUp(self):
        self.provider = SlowLocalProvider()
        self.addCleanup(self.provider.close)
        self.api = RunningApi(self.provider)
        self.addCleanup(self.api.close)

    def disconnect(self, path):
        async def run():
            async with httpx.AsyncClient(base_url=self.api.url, headers=self.auth, trust_env=False) as client:
                pending = asyncio.create_task(client.post(path, json={'text':'Synthetic question'}))
                try:
                    entered = await asyncio.to_thread(self.provider.entered.wait, 2)
                    self.assertTrue(entered, 'Request did not reach local test provider')
                finally:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
        asyncio.run(run())
        self.assertTrue(self.provider.closed.wait(1), 'API left the downstream provider connection open')
        with httpx.Client(base_url=self.api.url, headers=self.auth, trust_env=False) as client:
            self.assertEqual(client.get('/v1/chat').json()['messages'], [])
            reply = client.post('/v1/chat', json={'text':'Next synthetic question'}).json()
            self.assertEqual(reply['text'], 'Synthetic reply.')
            self.assertEqual(reply['status'], 'complete')

    def test_browser_disconnect_releases_provider_and_next_conversation(self):
        self.disconnect('/v1/chat')

    def test_explicit_stop_is_authenticated_scoped_and_closes_provider(self):
        with httpx.Client(base_url=self.api.url, headers=self.auth, trust_env=False) as owner:
            with ThreadPoolExecutor(1) as pool:
                pending = pool.submit(owner.post, '/v1/chat', json={'text':'Synthetic private question'})
                self.assertTrue(self.provider.entered.wait(2))
                activity = owner.get('/v1/chat/activity').json()
                self.assertTrue(activity['active'])
                self.assertNotIn('private', str(activity))
                identifier = activity['id']; stop = '/v1/chat/activity/'+identifier+'/stop'
                self.assertEqual(httpx.post(self.api.url+stop, trust_env=False).status_code, 401)
                with httpx.Client(base_url=self.api.url, trust_env=False) as other:
                    ticket = owner.post('/v1/ui/ticket').json()['ticket']
                    self.assertEqual(other.post('/v1/ui/session', headers={'X-Echo-Request':'1'}, json={'ticket':ticket}).status_code, 200)
                    self.assertEqual(other.get('/v1/chat/activity').json()['state'], 'idle')
                    self.assertEqual(other.post(stop, headers={'X-Echo-Request':'1'}).status_code, 404)
                self.assertEqual(owner.post('/v1/chat', json={'text':'Duplicate request'}).status_code, 409)
                self.assertEqual(owner.post(stop).status_code, 200)
                result = pending.result(timeout=2)
                self.assertEqual(result.json()['status'], 'cancelled')
                self.assertTrue(self.provider.closed.wait(1))
                self.assertEqual(owner.get('/v1/chat').json()['messages'], [])
                self.assertEqual(owner.get('/v1/chat/activity').json()['state'], 'cancelled')
                self.assertEqual(owner.post('/v1/chat',json={'text':'Next question'}).json()['status'], 'complete')
                self.assertEqual(owner.post(stop).status_code, 404)
                self.assertEqual(owner.get('/v1/chat/activity').json()['state'], 'completed')

    def test_device_disconnect_releases_provider_and_next_conversation(self):
        self.disconnect('/v1/text')

    def test_model_discovery_disconnect_closes_provider(self):
        self.disconnect('/v1/settings/models')

    def test_provider_check_disconnect_closes_provider(self):
        self.disconnect('/v1/settings/test')

    def test_api_shutdown_aborts_provider_without_waiting_for_network_timeout(self):
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(httpx.post, self.api.url+'/v1/chat', headers=self.auth,
                json={'text':'Synthetic question'}, trust_env=False, timeout=5)
            self.assertTrue(self.provider.entered.wait(2))
            self.api.app.state.speech_stop.set()
            self.assertEqual(pending.result(timeout=1).status_code, 503)
            self.assertTrue(self.provider.closed.wait(1))
        with httpx.Client(base_url=self.api.url, headers=self.auth, trust_env=False) as client:
            self.assertEqual(client.get('/v1/chat').json()['messages'], [])
            self.assertEqual(client.post('/v1/chat', json={'text':'Not dispatched'}).status_code, 503)
        self.assertEqual(self.provider.count, 1)


if __name__ == '__main__': unittest.main()
