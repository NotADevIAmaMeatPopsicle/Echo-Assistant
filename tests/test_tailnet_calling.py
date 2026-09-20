"""Synthetic calling gateway checks; only ephemeral loopback test listeners."""
import asyncio
from contextlib import AsyncExitStack
import copy
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

try:
    from aiohttp import ClientSession, DummyCookieJar, WSMsgType, web
    from aiohttp.test_utils import TestClient, TestServer
except ModuleNotFoundError as error:
    if error.name == 'aiohttp':
        raise unittest.SkipTest('Run in the isolated tailnet proxy environment') from None
    raise

from tools.tailnet_gateway import Gateway, calling_settings


HOST = 'echo.example:18469'
ORIGIN = 'https://' + HOST
OWN = {'ID': 'synthetic-host', 'TailscaleIPs': ['100.64.0.10']}


def configuration():
    return {'hostname': 'echo.example', 'host_id': OWN['ID'], 'tailscale': 'synthetic-tailscale',
            'bind_addresses': list(OWN['TailscaleIPs']),
            'allowed_devices': [{'id': 'synthetic-display', 'ips': ['127.0.0.1'], 'role': 'display'}],
            'calling': {'enabled': True, 'media_bind_address': '100.64.0.10',
                        'local_origins': ['http://127.0.0.1:8790', 'http://localhost:18669']}}


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(.005)


class ConfigurationTests(unittest.TestCase):
    def test_absent_or_explicitly_disabled_is_inert(self):
        self.assertIsNone(calling_settings({}))
        self.assertIsNone(calling_settings({'calling': {'enabled': False}}))
        gateway = Gateway({'calling': {'enabled': False}})
        self.assertIsNone(gateway._media_server)
        self.assertEqual(gateway._media_tasks, set())

    def test_enabled_configuration_is_exact_and_loopback_origins_only(self):
        config = configuration()
        self.assertEqual(calling_settings(config)['media_bind_address'], '100.64.0.10')
        for changed in ({'enabled': 1}, {'target': 'http://elsewhere'},
                        {'media_bind_address': '0.0.0.0'}, {'media_bind_address': '127.0.0.1'},
                        {'media_bind_address': '100.64.0.11'}, {'media_bind_address': '::'},
                        {'local_origins': ['*']}, {'local_origins': ['https://attacker.example']},
                        {'local_origins': ['http://localhost:18669/']},
                        {'local_origins': ['http://user@localhost:18669']},
                        {'local_origins': ['http://127.0.0.1:8790?query=1']},
                        {'local_origins': ['http://localhost']}, {'local_origins': [None]}):
            with self.subTest(changed=changed):
                candidate = copy.deepcopy(config)
                candidate['calling'].update(changed)
                with self.assertRaises(ValueError):
                    Gateway(candidate)
        for value in (None, {}, {'enabled': 0}, {'enabled': False, 'target': 'ignored'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Gateway({'calling': value})


class SignalingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        self.addAsyncCleanup(self.stack.aclose)
        self.received = []
        self.gateway = Gateway(configuration())
        self.gateway.authorized = AsyncMock(return_value=True)
        self.addAsyncCleanup(self.gateway.stop_calling)
        async def upstream(request):
            self.received.append((request.raw_path, dict(request.headers)))
            if request.path in {'/rtc', '/rtc/v1'}:
                socket = web.WebSocketResponse()
                await socket.prepare(request)
                async for message in socket:
                    if message.type == WSMsgType.TEXT:
                        await socket.send_str(message.data)
                    elif message.type == WSMsgType.BINARY:
                        await socket.send_bytes(message.data)
                return socket
            return web.Response(text='provider-validation', headers={
                'Set-Cookie': 'provider_session=not-forwarded', 'Authorization': 'not-forwarded'})
        upstream_app = web.Application()
        upstream_app.router.add_route('*', '/{path:.*}', upstream)
        server = await self.stack.enter_async_context(TestServer(upstream_app))
        self.stack.enter_context(patch('tools.tailnet_gateway.CALLING_SIGNAL', str(server.make_url('')).rstrip('/')))
        self.stack.enter_context(patch('tools.tailnet_gateway.CALLING_RECHECK', .01))
        self.gateway.client = await self.stack.enter_async_context(ClientSession(cookie_jar=DummyCookieJar()))
        app = web.Application()
        self.service = {'port': 18469, 'kind': 'echo', 'target': 'http://127.0.0.1:1'}
        app['service'] = self.service
        app.router.add_route('*', '/{path:.*}', self.gateway.proxy)
        self.client = await self.stack.enter_async_context(TestClient(TestServer(app)))
        self.headers = {'Host': HOST, 'Origin': ORIGIN}

    async def test_display_sdk_websocket_needs_no_echo_header_and_forwards_no_credentials(self):
        headers = {**self.headers, 'Authorization': 'Display invalid-on-purpose',
                   'Cookie': 'echo_session=private', 'X-Forwarded-For': '100.64.0.2',
                   'Tailscale-User-Login': 'forged'}
        async with self.client.ws_connect('/rtc?access_token=synthetic.jwt', headers=headers) as socket:
            await socket.send_str('synthetic-signaling')
            self.assertEqual((await socket.receive()).data, 'synthetic-signaling')
            await socket.send_bytes(b'\x00\x01synthetic')
            self.assertEqual((await socket.receive()).data, b'\x00\x01synthetic')
        path, received = self.received[0]
        self.assertEqual(path, '/rtc?access_token=synthetic.jwt')
        self.assertEqual(received['Origin'], ORIGIN)
        self.assertFalse({'Authorization', 'Cookie', 'X-Forwarded-For', 'Tailscale-User-Login'} & received.keys())

    async def test_validate_allows_only_configured_origins_and_strips_provider_cookies(self):
        for origin in (ORIGIN, 'http://127.0.0.1:8790', 'http://localhost:18669'):
            response = await self.client.get('/rtc/validate?access_token=synthetic.jwt',
                headers={**self.headers, 'Origin': origin, 'Cookie': 'echo_session=private',
                         'Authorization': 'Bearer private'})
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.text(), 'provider-validation')
            self.assertNotIn('Set-Cookie', response.headers)
            self.assertNotIn('Authorization', response.headers)
            self.assertNotIn('Cookie', self.received[-1][1])
            self.assertNotIn('Authorization', self.received[-1][1])

    async def test_sdk_v1_websocket_forwards_actual_bytes_and_query_without_echo_credentials(self):
        path = '/rtc/v1?access_token=synthetic.jwt&sdk=js&version=2.22.3'
        headers = {**self.headers, 'Cookie': 'echo_session=private', 'Authorization': 'Display invalid'}
        async with self.client.ws_connect(path, headers=headers) as socket:
            await socket.send_bytes(b'\x00\x01synthetic-v1')
            self.assertEqual((await socket.receive()).data, b'\x00\x01synthetic-v1')
        self.assertEqual(self.received[0][0], path)
        self.assertFalse({'Cookie', 'Authorization'} & self.received[0][1].keys())

    async def test_sdk_v1_validation_preserves_origin_and_same_origin_fetch_policy(self):
        path = '/rtc/v1/validate?access_token=synthetic.jwt'
        for headers in ({**self.headers, 'Origin': 'http://127.0.0.1:8790'},
                        {'Host': HOST, 'Sec-Fetch-Site': 'same-origin'}):
            response = await self.client.get(path, headers=headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.text(), 'provider-validation')
            self.assertEqual(self.received[-1][0], path)
            self.assertNotIn('Set-Cookie', response.headers)
            self.assertNotIn('Authorization', response.headers)
        self.assertEqual(self.received[-1][1]['Origin'], ORIGIN)

    async def test_sdk_v1_does_not_admit_other_paths_methods_origins_or_unauthorized_peers(self):
        for path in ('/rtc/v1/', '/rtc/v1/extra', '/rtc/v1/validate/extra', '/rtc/v2',
                     '/rtc/v2/validate', '/rtc/v1/twirp/livekit.RoomService/ListRooms'):
            self.assertEqual((await self.client.get(path, headers=self.headers)).status, 404)
        for path in ('/rtc/v1', '/rtc/v1/validate'):
            self.assertEqual((await self.client.post(path, headers=self.headers)).status, 405)
            self.assertEqual((await self.client.get(path, headers={'Host': HOST})).status, 403)
            self.assertEqual((await self.client.get(path, headers={
                **self.headers, 'Origin': 'https://attacker.example'})).status, 403)
        self.assertEqual((await self.client.get('/rtc/v1', headers=self.headers)).status, 400)
        self.gateway.authorized.return_value = False
        self.assertEqual((await self.client.get('/rtc/v1/validate', headers=self.headers)).status, 403)
        self.assertEqual(self.received, [])

    async def test_missing_wrong_or_unconfigured_origin_never_reaches_livekit(self):
        for origin in (None, 'null', 'https://attacker.example', ORIGIN + '/', 'http://localhost:8790'):
            headers = {'Host': HOST}
            if origin is not None:
                headers['Origin'] = origin
            response = await self.client.get('/rtc/validate', headers=headers)
            self.assertEqual(response.status, 403)
        self.assertEqual(self.received, [])

    async def test_only_same_origin_validate_fetch_can_omit_origin(self):
        response = await self.client.get('/rtc/validate?access_token=synthetic.jwt',
            headers={'Host': HOST, 'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.received[-1][1]['Origin'], ORIGIN)
        count = len(self.received)
        for site in (None, 'none', 'cross-site', 'same-site'):
            headers = {'Host': HOST}
            if site:
                headers['Sec-Fetch-Site'] = site
            self.assertEqual((await self.client.get('/rtc/validate', headers=headers)).status, 403)
        self.assertEqual((await self.client.get('/rtc/validate', headers={
            'Host': HOST, 'Sec-Fetch-Site': 'same-origin', 'Origin': 'https://attacker.example'})).status, 403)
        self.assertEqual((await self.client.get('/rtc', headers={
            'Host': HOST, 'Sec-Fetch-Site': 'same-origin'})).status, 403)
        self.assertEqual(len(self.received), count)

    async def test_actual_peer_cannot_be_replaced_with_forwarded_ip(self):
        self.gateway.config['allowed_devices'][0]['ips'] = ['100.64.0.2']
        self.gateway.authorized = Gateway.authorized.__get__(self.gateway)
        response = await self.client.get('/rtc/validate', headers={**self.headers,
            'X-Forwarded-For': '100.64.0.2', 'Forwarded': 'for=100.64.0.2', 'Tailscale-User-Login': 'owner'})
        self.assertEqual(response.status, 403)
        self.assertEqual(self.received, [])

    async def test_changed_stable_identity_is_denied(self):
        self.gateway.authorized = Gateway.authorized.__get__(self.gateway)
        reply = {'Node': {'StableID': 'different-node', 'Addresses': ['127.0.0.1/32']}}
        with patch('tools.tailnet_gateway.command', AsyncMock(return_value=json.dumps(reply).encode())) as command:
            response = await self.client.get('/rtc/validate', headers=self.headers)
        self.assertEqual(response.status, 403)
        self.assertEqual(command.await_args.args, ('synthetic-tailscale', 'whois', '--json', '127.0.0.1'))
        self.assertEqual(self.received, [])

    async def test_admin_paths_wrong_method_host_and_non_websocket_are_rejected(self):
        for path in ('/twirp', '/twirp/livekit.RoomService/ListRooms', '/rtc/extra', '/rtc/validate/extra'):
            self.assertEqual((await self.client.get(path, headers=self.headers)).status, 404)
        self.assertEqual((await self.client.post('/rtc/validate', headers=self.headers)).status, 405)
        self.assertEqual((await self.client.get('/rtc', headers=self.headers)).status, 400)
        self.assertEqual((await self.client.get('/rtc/validate', headers={**self.headers, 'Host': 'other.example'})).status, 403)
        self.assertEqual(self.received, [])

    async def test_disabled_or_hermes_service_does_not_gain_calling_route(self):
        self.gateway.calling = None
        self.assertEqual((await self.client.get('/rtc/validate', headers=self.headers)).status, 401)
        self.gateway.calling = calling_settings(self.gateway.config)
        self.service['kind'] = 'hermes'
        self.assertEqual((await self.client.get('/rtc/validate', headers=self.headers)).status, 403)
        self.assertEqual(self.received, [])

    async def test_websocket_closes_on_allowlist_revocation(self):
        socket = await self.client.ws_connect('/rtc?access_token=synthetic.jwt', headers=self.headers)
        self.gateway.config['allowed_devices'].clear()
        message = await asyncio.wait_for(socket.receive(), 2)
        self.assertIn(message.type, {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING})
        await eventually(lambda: not self.gateway._signal_tasks)
        self.assertEqual(self.gateway._signal_nodes, {})

    async def test_websocket_shutdown_cleans_up_owned_tasks(self):
        socket = await self.client.ws_connect('/rtc?access_token=synthetic.jwt', headers=self.headers)
        await self.gateway.stop_calling()
        self.assertIn((await asyncio.wait_for(socket.receive(), 2)).type,
                      {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING})
        self.assertEqual(self.gateway._signal_tasks, set())
        self.assertEqual(self.gateway._signal_nodes, {})


class MediaRelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        self.addAsyncCleanup(self.stack.aclose)
        self.gateway = Gateway(configuration())
        self.gateway.authorized = AsyncMock(return_value=True)
        self.real_open = asyncio.open_connection
        self.targets, self.upstream_tasks = [], set()
        self.clients = []
        async def echo(reader, writer):
            task = asyncio.current_task()
            self.upstream_tasks.add(task)
            try:
                while chunk := await reader.read(65536):
                    writer.write(chunk)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
                self.upstream_tasks.discard(task)
        self.upstream = await asyncio.start_server(echo, '127.0.0.1', 0)
        port = self.upstream.sockets[0].getsockname()[1]
        async def upstream_only(host, target_port, **kwargs):
            self.targets.append((host, target_port, kwargs))
            self.assertEqual((host, target_port), ('127.0.0.1', 7881))
            return await self.real_open('127.0.0.1', port, **kwargs)
        self.stack.enter_context(patch('tools.tailnet_gateway.asyncio.open_connection', upstream_only))
        self.stack.enter_context(patch('tools.tailnet_gateway.CALLING_RECHECK', .01))
        self.gateway._media_server = await asyncio.start_server(self.gateway.calling_relay, '127.0.0.1', 0)
        self.port = self.gateway._media_server.sockets[0].getsockname()[1]
        self.addAsyncCleanup(self.cleanup)

    async def cleanup(self):
        await self.gateway.stop_calling()
        for writer in self.clients:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
        self.upstream.close()
        await self.upstream.wait_closed()
        await eventually(lambda: not self.upstream_tasks)

    async def connect(self):
        reader, writer = await self.real_open('127.0.0.1', self.port)
        self.clients.append(writer)
        return reader, writer

    async def assert_closed(self, reader):
        try:
            self.assertEqual(await asyncio.wait_for(reader.read(1), 2), b'')
        except ConnectionResetError:
            pass

    async def test_authorized_relay_copies_only_synthetic_bytes_and_cleans_up(self):
        reader, writer = await self.connect()
        payload = b'\x00synthetic-encrypted-transport\xff'
        writer.write(payload)
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(len(payload)), 2), payload)
        self.assertEqual(self.targets, [('127.0.0.1', 7881, {'limit': 65536})])
        writer.close()
        await writer.wait_closed()
        await eventually(lambda: not self.gateway._media_tasks)
        self.assertEqual(self.gateway._media_nodes, {})

    async def test_unauthorized_or_wrong_role_never_connects_upstream(self):
        self.gateway.authorized.return_value = False
        reader, _ = await self.connect()
        await self.assert_closed(reader)
        self.gateway.authorized.return_value = True
        self.gateway.config['allowed_devices'][0]['role'] = 'guest'
        reader, _ = await self.connect()
        await self.assert_closed(reader)
        self.assertEqual(self.targets, [])

    async def test_revocation_closes_both_directions(self):
        reader, writer = await self.connect()
        writer.write(b'test')
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(4), 2), b'test')
        self.gateway.config['allowed_devices'].clear()
        await self.assert_closed(reader)
        await eventually(lambda: not self.gateway._media_tasks and not self.upstream_tasks)
        self.assertEqual(self.gateway._media_nodes, {})

    async def test_pending_identity_checks_consume_slots_and_shutdown_cancels_them(self):
        waiting = asyncio.Event()
        async def pending(peer):
            await waiting.wait()
            return True
        self.gateway.authorized.side_effect = pending
        with patch('tools.tailnet_gateway.CALLING_TOTAL', 2):
            first, _ = await self.connect()
            second, _ = await self.connect()
            await eventually(lambda: len(self.gateway._media_tasks) == 2)
            extra, _ = await self.connect()
            await self.assert_closed(extra)
            self.assertEqual(self.gateway.authorized.await_count, 2)
            self.assertEqual(self.targets, [])
            await self.gateway.stop_calling()
            await self.assert_closed(first)
            await self.assert_closed(second)
        self.assertEqual(self.gateway._media_tasks, set())
        self.assertEqual(self.gateway._media_nodes, {})

    async def test_per_node_limit_does_not_open_extra_upstream(self):
        with patch('tools.tailnet_gateway.CALLING_PER_NODE', 1):
            reader, writer = await self.connect()
            writer.write(b'one')
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(3), 2), b'one')
            extra, _ = await self.connect()
            await self.assert_closed(extra)
            self.assertEqual(len(self.targets), 1)
            self.assertEqual(self.gateway._media_nodes, {'synthetic-display': 1})

    async def test_idle_and_absolute_lifetime_close_connections(self):
        for setting in ('CALLING_IDLE', 'CALLING_LIFETIME'):
            with self.subTest(setting=setting), patch('tools.tailnet_gateway.' + setting, .03):
                reader, writer = await self.connect()
                writer.write(b'time')
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.readexactly(4), 2), b'time')
                await self.assert_closed(reader)
                await eventually(lambda: not self.gateway._media_tasks)

    async def test_disabled_callback_does_not_check_identity_or_connect(self):
        self.gateway.calling = None
        reader, _ = await self.connect()
        await self.assert_closed(reader)
        self.gateway.authorized.assert_not_awaited()
        self.assertEqual(self.targets, [])


class ListenerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stalled_drain_is_bounded_and_releases_media_slot(self):
        gateway = Gateway(configuration())
        gateway.authorized = AsyncMock(return_value=True)
        blocked = asyncio.Event()
        async def stall(*args):
            await blocked.wait()
        reader, incoming = Mock(), Mock()
        reader.read = AsyncMock(return_value=b'synthetic')
        incoming.read = AsyncMock(side_effect=stall)
        writer, upstream = Mock(), Mock()
        writer.get_extra_info.return_value = ('127.0.0.1', 12345)
        for output in (writer, upstream):
            output.wait_closed = AsyncMock()
            output.drain = AsyncMock()
        upstream.drain.side_effect = stall
        with patch('tools.tailnet_gateway.asyncio.open_connection', AsyncMock(return_value=(incoming, upstream))), \
             patch('tools.tailnet_gateway.CALLING_IO_TIMEOUT', .02):
            await asyncio.wait_for(gateway.calling_relay(reader, writer), 1)
        reader.read.assert_awaited_once_with(65536)
        upstream.write.assert_called_once_with(b'synthetic')
        for output in (writer, upstream):
            output.close.assert_called_once()
            output.transport.set_write_buffer_limits.assert_called_once_with(high=65536, low=16384)
        self.assertEqual(gateway._media_tasks, set())
        self.assertEqual(gateway._media_nodes, {})

    async def test_listener_binds_only_verified_tailscale_ipv4(self):
        gateway = Gateway(configuration())
        server = Mock()
        server.wait_closed = AsyncMock()
        with patch('tools.tailnet_gateway.asyncio.start_server', AsyncMock(return_value=server)) as start:
            await gateway.start_calling(OWN)
            start.assert_awaited_once_with(gateway.calling_relay, '100.64.0.10', 7881, limit=65536, backlog=16)
            await gateway.stop_calling()
        server.close.assert_called_once()
        server.wait_closed.assert_awaited_once()

    async def test_wrong_host_or_address_and_disabled_block_never_bind(self):
        with patch('tools.tailnet_gateway.asyncio.start_server', AsyncMock()) as start:
            for own in ({**OWN, 'ID': 'wrong-host'}, {**OWN, 'TailscaleIPs': ['100.64.0.11']}):
                with self.assertRaises(RuntimeError):
                    await Gateway(configuration()).start_calling(own)
            await Gateway({}).start_calling({})
            start.assert_not_awaited()

    async def test_listener_startup_failure_cleans_existing_hermes_relay(self):
        config = configuration()
        config['relay_port'] = 18787
        gateway = Gateway(config)
        gateway.certificate = AsyncMock()
        relay = Mock()
        relay.wait_closed = AsyncMock()
        with patch('tools.tailnet_gateway.command', AsyncMock(return_value=json.dumps({'Self': OWN}).encode())), \
             patch('tools.tailnet_gateway.asyncio.start_server', AsyncMock(side_effect=[relay, OSError('synthetic')])):
            with self.assertRaises(OSError):
                await gateway.run()
        relay.close.assert_called_once()
        relay.wait_closed.assert_awaited_once()
        self.assertEqual(gateway._media_tasks, set())

    async def test_https_startup_failure_closes_calling_and_hermes_listeners(self):
        config = configuration()
        config.update(relay_port=18787, services=[{'kind': 'echo', 'port': 18469, 'target': 'http://127.0.0.1:1'}])
        gateway = Gateway(config)
        gateway.certificate = AsyncMock()
        servers = [Mock(), Mock()]
        for server in servers:
            server.wait_closed = AsyncMock()
        site = Mock()
        site.start = AsyncMock(side_effect=OSError('synthetic bind failure'))
        with patch('tools.tailnet_gateway.command', AsyncMock(return_value=json.dumps({'Self': OWN}).encode())), \
             patch('tools.tailnet_gateway.asyncio.start_server', AsyncMock(side_effect=servers)), \
             patch('tools.tailnet_gateway.web.TCPSite', return_value=site):
            with self.assertRaises(OSError):
                await gateway.run()
        for server in servers:
            server.close.assert_called_once()
            server.wait_closed.assert_awaited_once()
        self.assertIsNone(gateway._media_server)


if __name__ == '__main__':
    unittest.main()
