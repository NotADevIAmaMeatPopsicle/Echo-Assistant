"""Private HTTPS access to Echo UIs, restricted to specific Tailscale node IDs.

Runs on the Docker host. Configuration/certificates stay in its private Echo
directory. Neither forwarded headers nor membership in the owner's account
grants access. Existing Tailscale Serve and tailnet ACLs remain unchanged.
"""
import argparse
import asyncio
import base64
import ctypes
import ipaddress
import json
import logging
import os
import re
from pathlib import Path
import ssl
import subprocess
import time
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout, DummyCookieJar, WSMsgType, web

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade'}
HTML_ROUTES = {'/', '/settings', '/devices', '/memory', '/routines', '/tasks', '/display'}
CALLING_SIGNAL = 'http://127.0.0.1:7880'
CALLING_WEBSOCKETS = {'/rtc', '/rtc/v1'}
CALLING_VALIDATION = {'/rtc/validate', '/rtc/v1/validate'}
CALLING_MEDIA_PORT = 7881
CALLING_TOTAL = 16
CALLING_PER_NODE = 4
CALLING_BUFFER = 65536
CALLING_RECHECK = 5
CALLING_IDLE = 60
CALLING_LIFETIME = 15 * 60
CALLING_IO_TIMEOUT = 5


def calling_settings(config):
    """An absent/explicitly disabled block opens no calling routes or listener."""
    if 'calling' not in config:
        return None
    value = config['calling']
    if not isinstance(value, dict):
        raise ValueError('Invalid private calling configuration')
    if value == {'enabled': False} and value['enabled'] is False:
        return None
    if set(value) != {'enabled', 'media_bind_address', 'local_origins'} or value['enabled'] is not True:
        raise ValueError('Invalid private calling configuration')
    try:
        bind = ipaddress.IPv4Address(value['media_bind_address'])
        if (str(bind) != value['media_bind_address'] or bind not in ipaddress.ip_network('100.64.0.0/10')
                or str(bind) not in config['bind_addresses']):
            raise ValueError()
        origins = value['local_origins']
        if not isinstance(origins, list) or len(origins) > 8 or len(set(origins)) != len(origins):
            raise ValueError()
        for origin in origins:
            parsed = urlsplit(origin)
            if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'}
                    or not parsed.port or origin != f'http://{parsed.hostname}:{parsed.port}'):
                raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError('Invalid private calling configuration') from None
    return {'media_bind_address': str(bind), 'local_origins': tuple(origins)}


def normalized_ip(value):
    ip = ipaddress.ip_address(value.split('%', 1)[0])
    return str(ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip)


def allowed_node(config, peer, whois):
    try:
        peer = normalized_ip(peer)
        node = whois['Node']
        match = next(d for d in config['allowed_devices'] if d['id'] == node['StableID'])
        return peer in {normalized_ip(x) for x in match['ips']} and any(
            ipaddress.ip_address(peer) in ipaddress.ip_network(x) for x in node['Addresses'])
    except (KeyError, TypeError, ValueError, StopIteration):
        return False


def origin_allowed(method, origin, expected):
    if origin is not None and origin != expected:
        return False
    return method in {'GET', 'HEAD', 'OPTIONS'} or origin == expected


def peer_role(config,peer):
    try:
        ip=normalized_ip(peer)
        devices=[d for d in config.get('allowed_devices',[]) if ip in {normalized_ip(v) for v in d['ips']}]
        if len(devices)!=1:return 'denied'
        role=devices[0].get('role','owner')
        return role if role in {'owner','display'} else 'denied'
    except (ValueError,KeyError,TypeError,AttributeError):return 'denied'


def forward_headers(headers, target, expected, *, allow_display=False):
    dropped = HOP | {'host', 'authorization', 'forwarded'}
    dropped.update(x.strip().lower() for x in headers.get('Connection', '').split(','))
    result = {k: v for k, v in headers.items() if k.lower() not in dropped
              and not k.lower().startswith(('x-forwarded-', 'tailscale-'))}
    result['Host'] = urlsplit(target).netloc
    if 'Origin' in headers:
        result['Origin'] = target
    if 'Referer' in result:
        # Never forward an arbitrary third-party referer as a trusted one.
        result.pop('Referer')
    credential=headers.get('Authorization','')
    if allow_display and re.fullmatch(r'Display [a-f0-9]{32}\.[A-Za-z0-9_-]{40,64}',credential):
        result={k:v for k,v in result.items() if k.lower()!='cookie'}
        result['Authorization']=credential
    return result


def read_api_token(bundle):
    """Unseal the existing current-user bootstrap in memory; return one field."""
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_byte))]
    raw = Path(bundle).read_bytes()
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = Blob()
    decrypt = ctypes.windll.crypt32.CryptUnprotectData
    decrypt.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    decrypt.restype = ctypes.c_int
    if not decrypt(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError('Echo bootstrap is unavailable for this user')
    try:
        token = json.loads(ctypes.string_at(output.data, output.size))['api_token']
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError('Invalid Echo bootstrap')
        return token
    finally:
        ctypes.memset(output.data, 0, output.size)
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(output.data)


async def command(*args, timeout=30):
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, creationflags=FLAGS)
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError('Private host command failed')
    return out


class Gateway:
    def __init__(self, config):
        self.config = config
        self.calling = calling_settings(config)
        self.cache = {}
        self.client = None
        self._media_server = None
        self._media_tasks, self._signal_tasks = set(), set()
        self._media_nodes, self._signal_nodes = {}, {}
        self._calling_stopping = False
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.ssl_context.set_alpn_protocols(['http/1.1'])

    async def _calling_node(self, peer):
        if not self.calling or self._calling_stopping or peer_role(self.config, peer) not in {'owner', 'display'}:
            return None
        if not await self.authorized(peer):
            return None
        ip = normalized_ip(peer)
        devices = [d for d in self.config['allowed_devices'] if ip in {normalized_ip(v) for v in d['ips']}]
        if len(devices) == 1 and isinstance(devices[0].get('id'), str) and devices[0]['id']:
            return devices[0]['id']
        return None

    async def _calling_watchdog(self, peer, node, started, activity=None):
        while True:
            await asyncio.sleep(CALLING_RECHECK)
            now = time.monotonic()
            if (self._calling_stopping or now - started >= CALLING_LIFETIME
                    or activity is not None and now - activity[0] >= CALLING_IDLE):
                return
            # authorized() retains the existing 15-second whois cache. Polling
            # every five seconds does not imply five-second identity revocation.
            if await asyncio.wait_for(self._calling_node(peer), CALLING_IO_TIMEOUT) != node:
                return

    @staticmethod
    async def _calling_pumps(*coroutines):
        tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    async def _close_writer(writer):
        if writer is None:
            return
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 2)
        except (OSError, TimeoutError):
            pass

    async def calling_relay(self, reader, writer):
        """Authorized Tailscale TCP only; fixed loopback media target, no UDP."""
        task, upstream, node = asyncio.current_task(), None, None
        # Reserve before the first await, including pending whois checks.
        if not self.calling or self._calling_stopping or len(self._media_tasks) >= CALLING_TOTAL:
            await self._close_writer(writer)
            return
        self._media_tasks.add(task)
        started = time.monotonic()
        try:
            peername = writer.get_extra_info('peername')
            if not isinstance(peername, tuple) or not peername:
                return
            peer = peername[0]
            selected = await asyncio.wait_for(self._calling_node(peer), CALLING_IO_TIMEOUT)
            if selected is None or self._calling_stopping or self._media_nodes.get(selected, 0) >= CALLING_PER_NODE:
                return
            node = selected
            self._media_nodes[node] = self._media_nodes.get(node, 0) + 1
            incoming, upstream = await asyncio.wait_for(asyncio.open_connection(
                '127.0.0.1', CALLING_MEDIA_PORT, limit=CALLING_BUFFER), CALLING_IO_TIMEOUT)
            activity = [time.monotonic()]
            for output in (writer, upstream):
                output.transport.set_write_buffer_limits(high=CALLING_BUFFER, low=CALLING_BUFFER // 4)
            async def copy(source, destination):
                while chunk := await source.read(CALLING_BUFFER):
                    activity[0] = time.monotonic()
                    destination.write(chunk)
                    await asyncio.wait_for(destination.drain(), CALLING_IO_TIMEOUT)
            await self._calling_pumps(copy(reader, upstream), copy(incoming, writer),
                self._calling_watchdog(peer, node, started, activity))
        except (OSError, ValueError, TimeoutError):
            pass
        finally:
            await self._close_writer(upstream)
            await self._close_writer(writer)
            if node is not None:
                self._media_nodes[node] -= 1
                if not self._media_nodes[node]:
                    self._media_nodes.pop(node)
            self._media_tasks.discard(task)

    async def start_calling(self, own):
        if not self.calling:
            return
        bind = self.calling['media_bind_address']
        if bind not in own['TailscaleIPs'] or own['ID'] != self.config['host_id']:
            raise RuntimeError('Calling requires the verified Tailscale host address')
        self._media_server = await asyncio.start_server(self.calling_relay, bind, CALLING_MEDIA_PORT,
                                                       limit=CALLING_BUFFER, backlog=CALLING_TOTAL)

    async def stop_calling(self):
        self._calling_stopping = True
        if self._media_server:
            self._media_server.close()
            await self._media_server.wait_closed()
            self._media_server = None
        tasks = list(self._media_tasks | self._signal_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def calling_proxy(self, request, expected):
        path = request.raw_path.partition('?')[0]
        if path not in CALLING_WEBSOCKETS | CALLING_VALIDATION:
            raise web.HTTPNotFound()
        if request.method != 'GET':
            raise web.HTTPMethodNotAllowed(request.method, ['GET'])
        origin = request.headers.get('Origin')
        if (path in CALLING_VALIDATION and origin is None
                and request.headers.get('Sec-Fetch-Site') == 'same-origin'):
            # Same-origin SDK fetches can omit Origin. The exact Echo authority
            # and actual peer identity have already been checked by proxy().
            origin = expected
        if origin not in (expected, *self.calling['local_origins']):
            raise web.HTTPForbidden(text='Use an allowed Echo calling origin.')
        # Only the already-validated origin goes upstream. Echo cookies, bearer/
        # Display credentials and identity headers never reach LiveKit.
        headers = {'Origin': origin}
        url = CALLING_SIGNAL + request.raw_path
        if path in CALLING_VALIDATION:
            if request.headers.get('Upgrade'):
                raise web.HTTPBadRequest()
            try:
                async with asyncio.timeout(10):
                    async with self.client.get(url, headers=headers, allow_redirects=False) as upstream:
                        body = bytearray()
                        async for chunk in upstream.content.iter_chunked(CALLING_BUFFER):
                            body.extend(chunk)
                            if len(body) > CALLING_BUFFER:
                                raise web.HTTPBadGateway(text='Calling validation response unavailable.')
                        return web.Response(status=upstream.status, body=bytes(body), headers={
                            'Content-Type': upstream.headers.get('Content-Type', 'text/plain'),
                            'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
            except (ClientError, OSError, TimeoutError):
                raise web.HTTPBadGateway(text='Calling service unavailable.') from None
        if request.headers.get('Upgrade', '').lower() != 'websocket':
            raise web.HTTPBadRequest(text='Calling signaling requires WebSocket.')
        task, node = asyncio.current_task(), None
        if self._calling_stopping or len(self._signal_tasks) >= CALLING_TOTAL:
            raise web.HTTPServiceUnavailable(text='Calling connection limit reached.')
        self._signal_tasks.add(task)
        try:
            node = await asyncio.wait_for(self._calling_node(request.remote), CALLING_IO_TIMEOUT)
            if node is None:
                raise web.HTTPForbidden()
            if self._signal_nodes.get(node, 0) >= CALLING_PER_NODE:
                node = None
                raise web.HTTPServiceUnavailable(text='Calling connection limit reached.')
            self._signal_nodes[node] = self._signal_nodes.get(node, 0) + 1
            connection = await asyncio.wait_for(self.client.ws_connect(url, headers=headers,
                max_msg_size=1024 * 1024, heartbeat=20), CALLING_IO_TIMEOUT)
            async with connection as upstream:
                socket = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=20)
                await socket.prepare(request)
                async def pump(source, destination):
                    async for message in source:
                        if message.type == WSMsgType.TEXT:
                            await asyncio.wait_for(destination.send_str(message.data), CALLING_IO_TIMEOUT)
                        elif message.type == WSMsgType.BINARY:
                            await asyncio.wait_for(destination.send_bytes(message.data), CALLING_IO_TIMEOUT)
                        else:
                            break
                try:
                    await self._calling_pumps(pump(socket, upstream), pump(upstream, socket),
                        self._calling_watchdog(request.remote, node, time.monotonic()))
                finally:
                    try:
                        await asyncio.wait_for(socket.close(), 2)
                    except (OSError, TimeoutError):
                        if request.transport:
                            request.transport.close()
                return socket
        except (ClientError, OSError, TimeoutError):
            raise web.HTTPBadGateway(text='Calling service unavailable.') from None
        finally:
            if node is not None:
                self._signal_nodes[node] -= 1
                if not self._signal_nodes[node]:
                    self._signal_nodes.pop(node)
            self._signal_tasks.discard(task)

    async def authorized(self, peer):
        try:
            ip = normalized_ip(peer)
        except (ValueError, AttributeError):
            return False
        if not any(ip in {normalized_ip(v) for v in d['ips']} for d in self.config['allowed_devices']):
            return False
        previous = self.cache.get(ip)
        if previous and previous[0] > time.monotonic():
            return previous[1]
        try:
            identity = json.loads(await command(self.config['tailscale'], 'whois', '--json', ip, timeout=5))
            ok = allowed_node(self.config, ip, identity)
        except (RuntimeError, OSError, ValueError, TimeoutError):
            ok = False
        self.cache[ip] = (time.monotonic() + 15, ok)
        return ok

    async def certificate(self):
        await command(self.config['tailscale'], 'cert', '--cert-file', self.config['cert'],
                      '--key-file', self.config['key'], '--min-validity', '24h',
                      self.config['hostname'], timeout=60)
        self.ssl_context.load_cert_chain(self.config['cert'], self.config['key'])

    async def echo_cookie(self, target):
        token = await asyncio.to_thread(read_api_token, self.config['echo_bundle'])
        async with self.client.post(target + '/v1/ui/ticket',
                headers={'Authorization': 'Bearer ' + token}) as r:
            r.raise_for_status()
            ticket = (await r.json())['ticket']
        async with self.client.post(target + '/v1/ui/session', json={'ticket': ticket},
                headers={'Origin': target, 'X-Echo-Request': '1'}) as r:
            r.raise_for_status()
            return r.headers.getall('Set-Cookie', [])

    async def proxy(self, request):
        if not await self.authorized(request.remote):
            raise web.HTTPForbidden(text='This device is not allowed to access Echo.')
        service = request.app['service']
        role=peer_role(self.config,request.remote)
        if role=='denied' or role=='display' and service['kind']!='echo':
            raise web.HTTPForbidden(text='This device is not permitted to administer Echo or Hermes.')
        authority = self.config['hostname'] + ':' + str(service['port'])
        expected = 'https://' + authority
        if request.host != authority:
            raise web.HTTPForbidden(text='Use the private Echo address directly.')
        if (self.calling and service['kind'] == 'echo' and (request.path in {'/rtc', '/twirp'}
                or request.path.startswith(('/rtc/', '/twirp/')))):
            return await self.calling_proxy(request, expected)
        if not origin_allowed(request.method, request.headers.get('Origin'), expected):
            raise web.HTTPForbidden(text='Use the private Echo address directly.')
        if service['kind'] == 'echo' and request.path.startswith('/internal/'):
            raise web.HTTPNotFound()
        target = service['target']
        is_display=request.headers.get('Authorization','').startswith('Display ')
        if is_display and not re.fullmatch(r'Display [a-f0-9]{32}\.[A-Za-z0-9_-]{40,64}',request.headers['Authorization']):
            raise web.HTTPUnauthorized(text='Invalid display credential.')
        if role=='display' and not is_display:
            public=(request.method=='GET' and (request.path in {'/display','/health'} or request.path.startswith('/assets/')))
            enroll=request.method=='POST' and request.path=='/v1/displays/enroll'
            if not public and not enroll:raise web.HTTPUnauthorized(text='Pair this device with Echo before using it.')
        headers = forward_headers(request.headers, target, expected,allow_display=service['kind']=='echo')
        if role=='display':headers={k:v for k,v in headers.items() if k.lower()!='cookie'}
        cookies = []
        if role=='owner' and not is_display and service['kind'] == 'echo' and request.method == 'GET' and request.path in HTML_ROUTES:
            async with self.client.get(target + '/v1/settings', headers={'Cookie': request.headers.get('Cookie', '')}) as r:
                if r.status == 401:
                    cookies = await self.echo_cookie(target)
        url = target + request.raw_path
        if request.headers.get('Upgrade', '').lower() == 'websocket':
            if request.headers.get('Origin') != expected:
                raise web.HTTPForbidden()
            protocols = tuple(x.strip() for x in request.headers.get('Sec-WebSocket-Protocol', '').split(',') if x.strip())
            for key in list(headers):
                if key.lower().startswith('sec-websocket-'):
                    headers.pop(key)
            async with self.client.ws_connect(url, headers=headers, protocols=protocols,
                                               max_msg_size=16 * 1024 * 1024) as upstream:
                socket = web.WebSocketResponse(protocols=protocols, max_msg_size=16 * 1024 * 1024)
                await socket.prepare(request)
                async def pump(source, destination):
                    async for message in source:
                        if message.type == WSMsgType.TEXT:
                            await destination.send_str(message.data)
                        elif message.type == WSMsgType.BINARY:
                            await destination.send_bytes(message.data)
                        elif message.type == WSMsgType.ERROR:
                            break
                    await destination.close()
                await asyncio.gather(pump(socket, upstream), pump(upstream, socket))
                return socket
        body = await request.read()
        async with self.client.request(request.method, url, headers=headers, data=body,
                                       allow_redirects=False) as upstream:
            response = web.StreamResponse(status=upstream.status)
            dropped = HOP | {'set-cookie'}
            dropped.update(x.strip().lower() for x in upstream.headers.get('Connection', '').split(','))
            for key, value in upstream.headers.items():
                if key.lower() in dropped:
                    continue
                if key.lower() == 'location' and value.startswith(target + '/'):
                    value = expected + value[len(target):]
                response.headers.add(key, value)
            for cookie in [*upstream.headers.getall('Set-Cookie', []), *cookies]:
                response.headers.add('Set-Cookie', cookie if '; secure' in cookie.lower() else cookie + '; Secure')
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Referrer-Policy'] = 'no-referrer'
            await response.prepare(request)
            async for chunk in upstream.content.iter_any():
                await response.write(chunk)
            await response.write_eof()
            return response

    async def docker_relay(self, reader, writer):
        """Loopback-only bridge to the existing Hermes container listener."""
        code = "import runpy; runpy.run_path('/opt/echo/start_webui.py',run_name='__main__')\n" + r'''
import os,socket,threading
s=socket.create_connection(('127.0.0.1',8787),timeout=10)
s.settimeout(None)
def upload():
 try:
  while True:
   data=os.read(0,65536)
   if not data: break
   s.sendall(data)
 except OSError: pass
 finally:
  try:s.shutdown(socket.SHUT_WR)
  except OSError:pass
threading.Thread(target=upload,daemon=True).start()
try:
 while True:
  data=s.recv(65536)
  if not data:break
  view=memoryview(data)
  while view:view=view[os.write(1,view):]
finally:s.close()
'''
        process = None
        try:
            process = await asyncio.create_subprocess_exec(self.config['docker'], 'exec', '-i',
                'echo-agent', '/opt/hermes/.venv/bin/python', '-u', '-c', code,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, creationflags=FLAGS)
            async def copy(source, destination):
                while chunk := await source.read(65536):
                    destination.write(chunk)
                    await destination.drain()
            tasks = [asyncio.create_task(copy(reader, process.stdin)), asyncio.create_task(copy(process.stdout, writer))]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        except (OSError, ConnectionError):
            pass
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            writer.close()

    async def run(self):
        own = json.loads(await command(self.config['tailscale'], 'status', '--json'))['Self']
        if own['ID'] != self.config['host_id'] or set(self.config['bind_addresses']) != set(own['TailscaleIPs']):
            raise RuntimeError('Tailscale host identity/address changed; review the private allowlist')
        await self.certificate()
        async with ClientSession(cookie_jar=DummyCookieJar(), trust_env=False, auto_decompress=False,
                                 timeout=ClientTimeout(total=None, sock_connect=10, sock_read=900)) as client:
            self.client = client
            relay, runners = None, []
            try:
                relay = await asyncio.start_server(self.docker_relay, '127.0.0.1', self.config['relay_port'])
                await self.start_calling(own)
                for service in self.config['services']:
                    app = web.Application(client_max_size=32 * 1024 * 1024)
                    app['service'] = service
                    app.router.add_route('*', '/{path:.*}', self.proxy)
                    runner = web.AppRunner(app, access_log=None, handler_cancellation=True)
                    runners.append(runner)
                    await runner.setup()
                    for bind in self.config['bind_addresses']:
                        await web.TCPSite(runner, bind, service['port'], ssl_context=self.ssl_context).start()
                while True:
                    Path(self.config['status']).write_text(json.dumps({'status': 'ready', 'checked_at': time.time(),
                        'allowed_nodes': [d['id'] for d in self.config['allowed_devices']]}))
                    await asyncio.sleep(12 * 3600)
                    await self.certificate()
            finally:
                await self.stop_calling()
                if relay:
                    relay.close()
                    await relay.wait_closed()
                for runner in runners:
                    await runner.cleanup()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    # Never log URLs/query strings, credentials, headers or conversation bodies.
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(Gateway(config).run())
    except Exception as error:
        Path(config['status']).write_text(json.dumps({'status': 'failed', 'error': type(error).__name__}))
        raise SystemExit(1)
