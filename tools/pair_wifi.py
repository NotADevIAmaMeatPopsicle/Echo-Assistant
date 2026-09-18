"""Pair the verified round board over USB. Never prints Wi-Fi or TLS secrets."""
import argparse
import base64
import getpass
import json
from pathlib import Path
import secrets
import sys
import time
import serial
from serial.tools import list_ports

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.transport import MAC, local_address, server_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='This computer\'s home LAN IPv4 address')
    parser.add_argument('--wifi-secrets', type=Path, help='Optional existing ESPHome secrets.yaml; read only')
    parser.add_argument('--port', required=True)
    args = parser.parse_args()
    if not local_address(args.host) or args.host.startswith('127.'):
        raise SystemExit('A home LAN IPv4 host address is required')
    if (ROOT/'local/voice-process.json').exists():
        raise SystemExit('Stop the voice bridge before pairing; it owns the shared transport')
    matches = [p for p in list_ports.comports() if p.device == args.port and (p.vid, p.pid) == (0x303A, 0x1001)
               and (p.serial_number or '').lower() == MAC]
    if len(matches) != 1: raise SystemExit('Expected round board not found; nothing was changed')
    if args.wifi_secrets:
        import yaml  # Optional ESPHome import; ordinary interactive pairing needs no PyYAML.
        data = yaml.safe_load(args.wifi_secrets.read_text(encoding='utf-8'))
        ssid, password = data['wifi_ssid'], data['wifi_password']
    else:
        ssid, password = input('Wi-Fi name: '), getpass.getpass('Wi-Fi password: ')
    if not all(isinstance(v, str) and '\0' not in v for v in (ssid, password)) or not 1 <= len(ssid.encode()) <= 32 or not 8 <= len(password.encode()) <= 63:
        raise SystemExit('A WPA2/WPA3 network name and 8–63 byte password are required')
    path = ROOT/'local/wifi.json'
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    key = previous.get('key') or secrets.token_hex(32)
    server_context(key)  # Check host support before persisting anything on the board.
    port = serial.Serial(port=None, baudrate=115200, timeout=.2, write_timeout=1)
    port.dtr = port.rts = False; port.port = args.port
    with port:
        def command(value, expected):
            port.write(value.encode('ascii')+b'\n')
            end = time.monotonic()+4
            while time.monotonic()<end:
                line = port.readline().decode('ascii', errors='replace').strip()
                if line == expected: return
                if line.startswith('PAIR_ERROR'): raise RuntimeError('Device rejected a pairing field; no secrets printed')
            raise RuntimeError('Pairing acknowledgement missing; reconnect USB and retry')
        command('PAIR_BEGIN', 'PAIR_OK BEGIN')
        command('PAIR_SSID '+base64.b64encode(ssid.encode()).decode(), 'PAIR_OK FIELD')
        command('PAIR_WIFI '+base64.b64encode(password.encode()).decode(), 'PAIR_OK FIELD')
        command('PAIR_HOST '+args.host, 'PAIR_OK FIELD')
        command('PAIR_KEY '+key, 'PAIR_OK FIELD')
        # Persist the matching host key before the board commits/reboots; retries reuse it.
        path.parent.mkdir(exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'enabled': True, 'host': args.host, 'mac': MAC, 'key': key}, indent=2), encoding='utf-8')
        temporary.replace(path)
        command('PAIR_SAVE', 'PAIR_OK SAVED')
    print('USB pairing saved. Wi-Fi credentials remain on the device. Start tools/run.ps1 to connect securely.')


if __name__ == '__main__': main()
