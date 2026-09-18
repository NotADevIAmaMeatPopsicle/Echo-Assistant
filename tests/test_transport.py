from backend import deployment
import json
from pathlib import Path
import socket
import ssl
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from backend.transport import IDENTITY, MAC, WifiTransport, load_wifi, server_context, bind_address


class Stop:
    def __init__(self): self.event = Event()
    def stopped(self): return self.event.is_set()


class PairingTests(unittest.TestCase):
    def test_container_bind_keeps_external_pairing_address_and_authentication(self):
        config = {'host':'192.168.1.50'}
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(bind_address(config), config['host'])
        with patch.dict('os.environ', {'ECHO_CONTAINER':'1','ECHO_WIFI_BIND':'0.0.0.0'}):
            self.assertEqual(bind_address(config), '0.0.0.0')
            self.assertEqual(config['host'], '192.168.1.50')
        with patch.dict('os.environ', {'ECHO_WIFI_BIND':'0.0.0.0','ECHO_CONTAINER':'0'}):
            with self.assertRaises(ValueError): bind_address(config)

    def test_pairing_validates_origin_identity_and_secret(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root/'local').mkdir(); path = root/'local/wifi.json'
            self.assertIsNone(load_wifi(root))
            config = {'enabled': True, 'host': '192.168.1.2', 'key': 'ab'*32, 'mac': MAC}
            path.write_text(json.dumps(config), encoding='utf-8')
            self.assertEqual(load_wifi(root), config)
            for field, value in [('host', '8.8.8.8'), ('host', 'example.com'), ('key', 'abc'), ('mac', 'different'), ('enabled', 'true')]:
                path.write_text(json.dumps({**config, field: value}), encoding='utf-8')
                with self.assertRaises(ValueError): load_wifi(root)

    @unittest.skipUnless(getattr(ssl, 'HAS_PSK', False), 'OpenSSL TLS PSK required for wireless')
    def test_tls_rejects_wrong_key_and_identity_then_carries_exact_bytes(self):
        lifecycle = Stop()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); number = probe.getsockname()[1]
        updates = []
        transport = WifiTransport({'host': '127.0.0.1', 'key': 'ab'*32}, lifecycle, number,
                                  on_wait=lambda: updates.append(time.monotonic()))
        errors = []
        def run():
            try: transport.open()
            except Exception as error: errors.append(error)
        thread = Thread(target=run); thread.start()
        def connect(key, identity):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            # TLS PSK authenticates with the key; no certificate participates.
            context.check_hostname = False; context.verify_mode = ssl.CERT_NONE
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
            context.set_ciphers('PSK-AES128-GCM-SHA256')
            context.set_psk_client_callback(lambda hint: (identity, bytes.fromhex(key)))
            deadline = time.monotonic()+3
            while True:
                try: raw = socket.create_connection(('127.0.0.1', number), timeout=2); break
                except ConnectionRefusedError:
                    if time.monotonic()>deadline: raise
                    time.sleep(.01)
            try: return context.wrap_socket(raw, server_hostname=None)
            except Exception: raw.close(); raise
        try:
            # Stay absent beyond the API's five-second freshness window, then
            # connect without restarting the listener or relaxing authentication.
            deadline = time.monotonic()+8
            while len(updates) < 7 and time.monotonic() < deadline: time.sleep(.02)
            self.assertGreaterEqual(len(updates), 7)
            self.assertTrue(thread.is_alive())
            self.assertFalse(transport.is_open)
            # Windows may surface the rejected handshake as a TCP reset before
            # OpenSSL delivers its alert; both must reject the connection.
            with self.assertRaises((ssl.SSLError, ConnectionResetError)): connect('cd'*32, IDENTITY)
            with self.assertRaises((ssl.SSLError, ConnectionResetError)): connect('ab'*32, 'another-device')
            with connect('ab'*32, IDENTITY) as client:
                thread.join(3); self.assertFalse(thread.is_alive()); self.assertFalse(errors)
                self.assertEqual(client.version(), 'TLSv1.2')
                self.assertEqual(client.cipher()[0], 'PSK-AES128-GCM-SHA256')
                count = len(updates)
                payload = bytes(range(256))*48
                client.sendall(payload)
                received = b''
                while len(received)<len(payload): received += transport.read(4096)
                self.assertEqual(received, payload)
                self.assertEqual(len(updates), count)
                transport.write(payload)
                received = b''
                while len(received)<len(payload): received += client.recv(4096)
                self.assertEqual(received, payload)
            with self.assertRaises(OSError): transport.read(4096)
        finally:
            lifecycle.event.set(); transport.close(); thread.join(4)
        self.assertFalse(thread.is_alive())


if __name__ == '__main__': unittest.main()
