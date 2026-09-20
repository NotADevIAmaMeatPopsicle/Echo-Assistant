"""Manual, silent LiveKit ICE/TCP check using only cached Docker/browser resources.

Creates only label-owned disposable containers/bridge, loopback port publications,
and (for SSH Docker contexts) an owned SSH forward. No production configuration,
device capture, playback, external STUN, or package/image downloads are used.
The disposable bridge matches production; this is not network-layer egress isolation.
Secrets enter the container and browser helper through stdin, never arguments.
Requires Node, Playwright (for example through NODE_PATH), and installed Chrome.
"""
import argparse
import base64
import hashlib
import hmac
import io
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import secrets

ROOT = Path(__file__).resolve().parents[1]
SERVER = 'livekit/livekit-server@sha256:6fd3b7088874c4d119160dd688798dfec852bc014786d392caad15f6f63912a3'
CLIENT_SHA256 = '7fa17e37af5e996d8a25f15a637dcc0620215bc01b394e5d209f726afe7dc04d'
LABEL = 'echo.rehearsal.calling-tcp'
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def token(key, secret, identity, grants):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=')
    now = int(time.time())
    body = {'iss': key, 'sub': identity, 'nbf': now-5, 'exp': now+180, 'video': grants}
    content = part({'alg': 'HS256', 'typ': 'JWT'}) + b'.' + part(body)
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), content, hashlib.sha256).digest()).rstrip(b'=')
    return (content + b'.' + signature).decode()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--node', default=shutil.which('node'))
    parser.add_argument('--http-port', type=int, help='Unused loopback port on client and Docker host')
    parser.add_argument('--tcp-port', type=int, help='Unused matching client/host ICE TCP port')
    args = parser.parse_args()
    if not args.node:
        raise SystemExit('Node is required; nothing was installed.')
    http_port = args.http_port or free_port()
    tcp_port = args.tcp_port or free_port()
    if not (20000 <= http_port <= 65535 and 20000 <= tcp_port <= 65535 and http_port != tcp_port):
        raise SystemExit('Choose two distinct unused ports between 20000 and 65535.')
    sdk = ROOT/'web/vendor/livekit-client-2.22.3.umd.js'
    if hashlib.sha256(sdk.read_bytes()).hexdigest() != CLIENT_SHA256:
        raise SystemExit('Bundled client checksum mismatch; nothing was started.')
    helper = ROOT/'tools/check_calling_tcp.cjs'
    subprocess.run([args.node, str(helper), '--preflight'], cwd=ROOT, check=True,
                   capture_output=True, timeout=15, creationflags=FLAGS)
    prefix = ['docker', '--context', args.context]

    def docker(*argv, data=None, timeout=35):
        try:
            return subprocess.run(prefix+list(argv), input=data, check=True, capture_output=True,
                                  timeout=timeout, creationflags=FLAGS).stdout.decode().strip()
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode(errors='replace').lower()
            category = next((word for word in ('read-only', 'permission denied', 'port is already allocated',
                'address already in use', 'not found', 'invalid', 'unknown flag') if word in detail), 'command rejected')
            raise RuntimeError('Docker '+str(argv[0])+' failed ('+category+').') from None

    # Inspect never pulls. Fail before creating anything when the exact image is absent.
    docker('image', 'inspect', SERVER, '--format', '{{.Id}}')
    endpoint = json.loads(docker('context', 'inspect', args.context))[0]['Endpoints']['docker']['Host']
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme not in {'ssh', 'npipe', 'unix'}:
        raise SystemExit('Only local or SSH Docker contexts are supported.')
    if parsed.scheme == 'ssh' and (parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
        raise SystemExit('Unsupported SSH context endpoint.')
    nonce = uuid.uuid4().hex
    name = 'echo-call-tcp-check-'+nonce[:12]
    network_id = container_id = None
    tunnel = None
    passed = None
    cleanup_errors = []
    key, secret = 'check-'+secrets.token_hex(12), secrets.token_hex(32)
    room = name
    base = f'http://127.0.0.1:{http_port}'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    admin = token(key, secret, 'synthetic-admin', {'roomCreate': True})

    def rpc(method, body):
        req = urllib.request.Request(base+'/twirp/livekit.RoomService/'+method,
                data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
                'Authorization': 'Bearer '+admin}, method='POST')
        with opener.open(req, timeout=3) as response:
            return json.load(response)

    def remove_owned(kind, identifier):
        if not identifier:
            return
        label = docker(kind, 'inspect', identifier, '--format', '{{index .Labels "'+LABEL+'"}}') if kind == 'network' else docker(
                'container', 'inspect', identifier, '--format', '{{index .Config.Labels "'+LABEL+'"}}')
        if label != nonce:
            raise RuntimeError('Resource ownership did not match; cleanup refused.')
        docker(kind, 'rm', *(['--force'] if kind == 'container' else []), identifier)

    try:
        network_id = docker('network', 'create', '--label', LABEL+'='+nonce, name)
        if not re.fullmatch('[a-f0-9]{64}', network_id):
            raise RuntimeError('Unexpected network identifier.')
        container_id = docker('container', 'create', '--pull=never', '--name', name,
                '--label', LABEL+'='+nonce, '--network', network_id, '--log-driver', 'none',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '512m',
                '--cpus', '1', '--pids-limit', '128',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=16777216',
                '-p', f'127.0.0.1:{http_port}:7880/tcp',
                '-p', f'127.0.0.1:{tcp_port}:{tcp_port}/tcp',
                SERVER, '--config', '/etc/echo-calling-tcp.yaml')
        if not re.fullmatch('[a-f0-9]{64}', container_id):
            raise RuntimeError('Unexpected container identifier.')
        configuration = json.dumps({'port': 7880, 'bind_addresses': ['0.0.0.0'],
            'rtc': {'tcp_port': tcp_port, 'force_tcp': True, 'node_ip': '127.0.0.1',
                    'use_external_ip': False, 'advertise_internal_ip': False,
                    'enable_loopback_candidate': True},
            'keys': {key: secret}, 'logging': {'level': 'error', 'pion_level': 'error'}}).encode()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as tar:
            entry = tarfile.TarInfo('echo-calling-tcp.yaml')
            entry.size, entry.mode = len(configuration), 0o600
            tar.addfile(entry, io.BytesIO(configuration))
        docker('cp', '-', container_id+':/etc/', data=archive.getvalue())
        docker('start', container_id)
        if parsed.scheme == 'ssh':
            target = (parsed.username+'@' if parsed.username else '') + parsed.hostname
            command = ['ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                       '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=10',
                       '-o', 'ServerAliveCountMax=2', '-L', f'127.0.0.1:{http_port}:127.0.0.1:{http_port}',
                       '-L', f'127.0.0.1:{tcp_port}:127.0.0.1:{tcp_port}']
            if parsed.port:
                command += ['-p', str(parsed.port)]
            tunnel = subprocess.Popen(command+[target], stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=FLAGS)
        deadline = time.monotonic()+25
        readiness_error = 'none'
        while True:
            if tunnel is not None and tunnel.poll() is not None:
                raise RuntimeError('Owned SSH loopback forwarding failed.')
            try:
                result = rpc('CreateRoom', {'name': room, 'max_participants': 2,
                                          'empty_timeout': 120, 'departure_timeout': 5})
                if result.get('name') == room:
                    break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                readiness_error = type(error).__name__
            if time.monotonic() >= deadline:
                state = docker('inspect', container_id, '--format', '{{.State.Status}}:{{.State.ExitCode}}')
                raise RuntimeError('Isolated provider did not become ready ('+state+', '+readiness_error+').')
            time.sleep(.25)
        grants = {'roomJoin': True, 'room': room, 'canSubscribe': True, 'canPublish': False,
                  'canPublishData': False, 'canPublishSources': []}
        payload = {'url': f'ws://127.0.0.1:{http_port}', 'expectedTcpPort': tcp_port,
                   'tokens': [token(key, secret, 'synthetic-'+str(i), grants) for i in range(2)]}
        result = subprocess.run([args.node, str(helper)], cwd=ROOT, input=json.dumps(payload).encode(),
                capture_output=True, timeout=85, creationflags=FLAGS)
        # Only parse the helper's intentionally sanitized result; never echo stderr/SDK errors.
        try:
            report = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise RuntimeError('Browser checker returned no sanitized result.') from None
        if result.returncode or not report.get('ice_tcp_connected'):
            listeners = set()
            for proc in ('/proc/net/tcp', '/proc/net/tcp6'):
                try:
                    rows = docker('exec', container_id, 'cat', proc).splitlines()[1:]
                    listeners.update(int(row.split()[1].split(':')[1], 16) for row in rows if row.split()[3] == '0A')
                except (RuntimeError, ValueError, IndexError):
                    pass
            report['server_listening_ports'] = sorted(listeners)
            report['expected_tcp_port'] = tcp_port
            report['container_state'] = docker('inspect', container_id, '--format', '{{.State.Status}}')
            raise RuntimeError('Browser ICE/TCP check failed: '+json.dumps(report))
        rpc('DeleteRoom', {'room': room})
        passed = {**report, 'server': '1.13.7', 'server_image': SERVER,
                  'client_sha256': CLIENT_SHA256, 'container_id': container_id,
                  'network_id': network_id, 'loopback_only': True, 'network_internal': False}
    finally:
        if tunnel is not None and tunnel.poll() is None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait(timeout=5)
        for kind, identifier in [('container', container_id), ('network', network_id)]:
            try:
                remove_owned(kind, identifier)
            except (RuntimeError, subprocess.SubprocessError):
                cleanup_errors.append(kind)
        if cleanup_errors:
            raise RuntimeError('Owned cleanup requires attention: '+', '.join(cleanup_errors))
    print(json.dumps({**passed, 'owned_resources_removed': True}))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        # subprocess exceptions can contain credentials, paths or signalling URLs.
        detail = str(error) if type(error) is RuntimeError else type(error).__name__
        raise SystemExit('Calling TCP rehearsal failed: '+detail) from None
