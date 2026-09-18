"""Opt-in LAN transport, mutually authenticated by a USB-paired 256-bit TLS key.

TLS 1.2 PSK/AES-GCM needs Python 3.13+ with OpenSSL PSK support. USB has no
such requirement. No certificates, DNS, public listeners, or cloud services.
"""
from hmac import compare_digest
from ipaddress import ip_address, ip_network
import json
import os
import re
import socket
import ssl
import time

MAC = __import__('os').environ.get('ECHO_DEVICE_MAC', '').lower()
IDENTITY = 'round-voice/' + MAC


def local_address(value):
    try:
        address = ip_address(value)
        return any(address in ip_network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8'))
    except ValueError:
        return False


def load_wifi(root):
    path = root / 'local/wifi.json'
    if not path.exists(): return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('enabled') is False: return None
    if (data.get('enabled') is not True or data.get('mac') != MAC
            or not local_address(data.get('host', ''))
            or not isinstance(data.get('key'), str)
            or not re.fullmatch('[a-f0-9]{64}', data['key'])):
        raise ValueError('Invalid local Wi-Fi pairing; re-run the USB pairing tool')
    return data


def server_context(key):
    if not getattr(ssl, 'HAS_PSK', False):
        raise RuntimeError('Wireless requires Python 3.13+ with TLS PSK support')
    if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('Pairing key must be 256 random bits')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers('PSK-AES128-GCM-SHA256')
    secret = bytes.fromhex(key)
    context.set_psk_server_callback(lambda identity: secret if identity and compare_digest(identity.encode('utf-8'), IDENTITY.encode()) else b'')
    return context


def bind_address(config):
    """Keep the paired destination separate from a container's private socket."""
    override = os.environ.get('ECHO_WIFI_BIND')
    if override is None: return config['host']
    if os.environ.get('ECHO_CONTAINER') != '1' or override != '0.0.0.0':
        raise ValueError('Only the container deployment may override the listener bind')
    return override


class WifiTransport:
    """Serial-like interface, so audio framing, credits and watchdogs stay shared."""
    def __init__(self, config, lifecycle, port=8769, *, on_wait=None):
        self.config, self.lifecycle, self.port = config, lifecycle, port
        self.on_wait = on_wait
        self.socket = None

    @property
    def is_open(self): return self.socket is not None

    def open(self):
        context = server_context(self.config['key'])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((bind_address(self.config), self.port))
            listener.listen(2); listener.settimeout(.5)
            next_update = 0.
            while not self.lifecycle.stopped():
                now = time.monotonic()
                if self.on_wait and now >= next_update:
                    self.on_wait()
                    next_update = time.monotonic()+1
                try: raw, peer = listener.accept()
                except socket.timeout: continue
                try:
                    if not local_address(peer[0]): raw.close(); continue
                    raw.settimeout(3)
                    secured = context.wrap_socket(raw, server_side=True)
                    secured.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    secured.settimeout(.01)
                    self.socket = secured
                    return
                except (ssl.SSLError, OSError):
                    raw.close()  # Authentication errors contain no user data and are not logged.
        raise OSError('Wireless listener stopped')

    def read(self, size):
        try:
            data = self.socket.recv(min(size, 16384))
            if not data: raise OSError('Paired wireless connection closed')
            return data
        except socket.timeout: return b''

    def write(self, data):
        self.socket.settimeout(.5)
        try: self.socket.sendall(data)
        finally: self.socket.settimeout(.01)
        return len(data)

    def close(self):
        if self.socket:
            self.socket.close(); self.socket = None
