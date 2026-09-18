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
from pathlib import Path
import ssl
import subprocess
import time
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, DummyCookieJar, WSMsgType, web

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade'}
HTML_ROUTES = {'/', '/settings', '/devices', '/memory', '/routines', '/tasks'}


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


def forward_headers(headers, target, expected):
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
        self.cache = {}
        self.client = None
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.ssl_context.set_alpn_protocols(['http/1.1'])

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
        authority = self.config['hostname'] + ':' + str(service['port'])
        expected = 'https://' + authority
        if request.host != authority or not origin_allowed(request.method, request.headers.get('Origin'), expected):
            raise web.HTTPForbidden(text='Use the private Echo address directly.')
        if service['kind'] == 'echo' and request.path.startswith('/internal/'):
            raise web.HTTPNotFound()
        target = service['target']
        headers = forward_headers(request.headers, target, expected)
        cookies = []
        if service['kind'] == 'echo' and request.method == 'GET' and request.path in HTML_ROUTES:
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
            relay = await asyncio.start_server(self.docker_relay, '127.0.0.1', self.config['relay_port'])
            runners = []
            for service in self.config['services']:
                app = web.Application(client_max_size=32 * 1024 * 1024)
                app['service'] = service
                app.router.add_route('*', '/{path:.*}', self.proxy)
                runner = web.AppRunner(app, access_log=None, handler_cancellation=True)
                await runner.setup()
                runners.append(runner)
                for bind in self.config['bind_addresses']:
                    await web.TCPSite(runner, bind, service['port'], ssl_context=self.ssl_context).start()
            try:
                while True:
                    Path(self.config['status']).write_text(json.dumps({'status': 'ready', 'checked_at': time.time(),
                        'allowed_nodes': [d['id'] for d in self.config['allowed_devices']]}))
                    await asyncio.sleep(12 * 3600)
                    await self.certificate()
            finally:
                relay.close()
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
