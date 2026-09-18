"""Focused access-boundary checks; runnable with unittest in the proxy venv."""
import unittest
try:
    from aiohttp import ClientSession, DummyCookieJar, web
    from aiohttp.test_utils import TestClient, TestServer
except ModuleNotFoundError as error:
    if error.name == 'aiohttp':
        raise unittest.SkipTest('Run in the isolated tailnet proxy environment') from None
    raise
from tools.tailnet_gateway import Gateway, allowed_node, forward_headers, origin_allowed


class AccessTests(unittest.TestCase):
    def test_exact_node_and_address_required(self):
        config = {'allowed_devices': [{'id': 'chosen-node', 'ips': ['100.64.0.2']}]}
        whois = {'Node': {'StableID': 'chosen-node', 'Addresses': ['100.64.0.2/32']}}
        self.assertTrue(allowed_node(config, '100.64.0.2', whois))
        self.assertFalse(allowed_node(config, '100.64.0.3', whois))
        self.assertFalse(allowed_node(config, '100.64.0.2', {'Node': {**whois['Node'], 'StableID': 'other-node'}}))
        self.assertFalse(allowed_node(config, '100.64.0.2', {}))

    def test_unsafe_requests_require_exact_origin(self):
        origin = 'https://echo.example:18469'
        self.assertTrue(origin_allowed('GET', None, origin))
        self.assertTrue(origin_allowed('POST', origin, origin))
        for method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            self.assertFalse(origin_allowed(method, None, origin))
            self.assertFalse(origin_allowed(method, 'https://attacker.example', origin))

    def test_no_forwarded_identity_or_client_bearer(self):
        headers = {'Authorization': 'Bearer untrusted', 'X-Forwarded-For': '100.64.0.2',
                   'Tailscale-User-Login': 'owner', 'Forwarded': 'for=trusted',
                   'Connection': 'keep-alive, X-Extra', 'X-Extra': 'drop',
                   'Cookie': 'echo_session=browser-session', 'Origin': 'https://echo.example:18469'}
        result = forward_headers(headers, 'http://127.0.0.1:18668', 'https://echo.example:18469')
        self.assertEqual(result, {'Host': '127.0.0.1:18668', 'Cookie': 'echo_session=browser-session',
                                  'Origin': 'http://127.0.0.1:18668'})


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_peer_cannot_impersonate_allowed_device(self):
        gateway = Gateway({'hostname': 'echo.example', 'allowed_devices': []})
        app = web.Application()
        app['service'] = {'port': 18469, 'kind': 'echo', 'target': 'http://127.0.0.1:1'}
        app.router.add_route('*', '/{path:.*}', gateway.proxy)
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/', headers={'Host': 'echo.example:18469',
                'X-Forwarded-For': '100.64.0.2', 'Tailscale-User-Login': 'owner'})
            self.assertEqual(response.status, 403)
            self.assertNotIn('Set-Cookie', response.headers)

    async def test_permitted_proxy_preserves_cookie_and_rejects_csrf(self):
        received = []
        async def upstream(request):
            received.append(dict(request.headers))
            return web.Response(text='upstream')
        upstream_app = web.Application()
        upstream_app.router.add_route('*', '/{path:.*}', upstream)
        async with TestServer(upstream_app) as server:
            gateway = Gateway({'hostname': 'echo.example'})
            async def authorized(peer): return True
            gateway.authorized = authorized
            app = web.Application()
            app['service'] = {'port': 18469, 'kind': 'echo', 'target': str(server.make_url('')).rstrip('/')}
            app.router.add_route('*', '/{path:.*}', gateway.proxy)
            async with ClientSession(cookie_jar=DummyCookieJar()) as connection, TestClient(TestServer(app)) as client:
                gateway.client = connection
                denied = await client.post('/v1/chat', headers={'Host': 'echo.example:18469', 'Origin': 'https://attacker.example'})
                self.assertEqual(denied.status, 403)
                self.assertEqual(received, [])
                response = await client.post('/v1/chat', data=b'{}', headers={'Host': 'echo.example:18469',
                    'Origin': 'https://echo.example:18469', 'Cookie': 'echo_session=private', 'X-Echo-Request': '1'})
                self.assertEqual(await response.text(), 'upstream')
                self.assertEqual(received[0]['Cookie'], 'echo_session=private')
                self.assertNotIn('Authorization', received[0])


if __name__ == '__main__': unittest.main()
