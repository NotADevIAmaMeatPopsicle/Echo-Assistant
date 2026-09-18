"""Read fresh hardware status; optional --chime deliberately plays a test."""
import argparse
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cable import Decoder
from tools.device_transport import make_transport


def fresh_status(port, timeout=8):
    # A newly opened dock connection may contain old boot/status output. Only
    # accept this query's reply, never an unsolicited query=0 boot report.
    query = time.monotonic_ns() % 0xffffffff + 1
    decoder = Decoder()
    deadline = time.monotonic() + timeout
    port.write(f'STATUS {query}\n'.encode())
    while time.monotonic() < deadline:
        _, lines = decoder.feed(port.read(4096))
        for line in lines:
            if not line.startswith('STATUS '): continue
            fields = dict(re.findall(r'(\w+)=([^ ]+)', line))
            if fields.get('query') != str(query): continue
            if fields.get('product') != 'round-voice':
                raise RuntimeError('Unexpected firmware identity in fresh status')
            return fields
    raise RuntimeError('No fresh Round Voice status reply; boot output is not sufficient')


def check_hardware(receipt, expected_volume=None):
    for field in ('display', 'touch', 'mic', 'speaker'):
        if receipt.get(field) != '1': raise RuntimeError(f'{field} not initialized')
    if receipt.get('audio_errors') != '0': raise RuntimeError('Audio driver errors')
    if int(receipt.get('psram', '0')) < 8 * 1024 * 1024: raise RuntimeError('PSRAM missing')
    if expected_volume is not None and receipt.get('volume') != str(expected_volume):
        raise RuntimeError(f"Expected volume {expected_volume}%, got {receipt.get('volume', 'unknown')}%; no sound was requested")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port')
    parser.add_argument('--chime', action='store_true')
    parser.add_argument('--expect-volume', type=int, choices=range(21), help='Fail if the fresh status does not match this required volume')
    args = parser.parse_args(); args.wifi = False
    port = make_transport(args)  # Refuses a live bridge and checks VID/PID/MAC.
    try:
        port.open()
        receipt = fresh_status(port)
        check_hardware(receipt, args.expect_volume)
        # Do not print unrelated serial lines or microphone frame contents.
        print('STATUS ' + ' '.join(f'{key}={receipt.get(key)}' for key in
              ('product', 'version', 'query', 'uptime_ms', 'volume', 'muted', 'audio_errors')), flush=True)
        if args.chime:
            port.write(b'CHIME\n')
            time.sleep(2)
            receipt = fresh_status(port, 3)
            check_hardware(receipt, args.expect_volume)
            if receipt.get('mode') != '0': raise RuntimeError('Chime did not finish cleanly')
    finally:
        port.close()
    print('PASS: fresh hardware status; audible/visual quality needs user confirmation')


if __name__ == '__main__':
    main()
