"""Archive or verify this board's compiled firmware. No device access or downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
BOARD = 'Waveshare ESP32-S3-Touch-AMOLED-1.75'
MAC = None  # Release bundles target a board model, not a private device identity.
FLASH = {'chip':'esp32s3', 'mode':'dio', 'frequency':'80m', 'size':'16MB'}
IMAGES = (('bootloader.bin', 0, 0x8000), ('partitions.bin', 0x8000, 0x1000),
          ('boot_app0.bin', 0xe000, 0x2000), ('firmware.bin', 0x10000, 0x640000))
PARTITIONS = [(1, 2, 0x9000, 0x5000, b'nvs'), (1, 0, 0xe000, 0x2000, b'otadata'),
              (0, 0x10, 0x10000, 0x640000, b'app0'), (0, 0x11, 0x650000, 0x640000, b'app1'),
              (1, 0x82, 0xc90000, 0x360000, b'spiffs'), (1, 3, 0xff0000, 0x10000, b'coredump')]


def sha256(data): return hashlib.sha256(data).hexdigest()


def validate_payloads(payloads):
    if set(payloads) != {name for name, _, _ in IMAGES}:
        raise ValueError('Bundle must contain exactly the four expected firmware images')
    for name, _, limit in IMAGES:
        if not 0 < len(payloads[name]) <= limit:
            raise ValueError('Image does not fit its flash region: '+name)
    for name in ('bootloader.bin', 'firmware.bin'):
        data = payloads[name]
        if len(data) < 24 or data[0] != 0xe9 or struct.unpack_from('<H', data, 12)[0] != 9:
            raise ValueError('Expected an ESP32-S3 image: '+name)
    table = payloads['partitions.bin']
    if len(table) != 3072: raise ValueError('Unexpected partition table size')
    for index, expected in enumerate(PARTITIONS):
        magic, kind, subtype, offset, size, name, flags = struct.unpack_from('<HBBII16sI', table, index*32)
        if magic != 0x50aa or flags or (kind, subtype, offset, size, name.rstrip(b'\0')) != expected:
            raise ValueError('Partition layout differs from the verified 16 MiB board layout')
    checksum_at = len(PARTITIONS)*32
    if (table[checksum_at:checksum_at+16] != b'\xeb\xeb'+b'\xff'*14
            or table[checksum_at+16:checksum_at+32] != hashlib.md5(table[:checksum_at]).digest()
            or table[checksum_at+32:] != b'\xff'*(len(table)-checksum_at-32)):
        raise ValueError('Invalid partition table checksum or extra partition')
    versions = set(re.findall(rb'STATUS product=round-voice version=(\d+\.\d+\.\d+) protocol=1', payloads['firmware.bin']))
    if len(versions) != 1: raise ValueError('Firmware does not identify one Round Voice version')
    return versions.pop().decode('ascii')


def manifest_for(payloads):
    return {'schema':1, 'product':'round-voice', 'board':BOARD, 'device_mac':MAC,
            'version':validate_payloads(payloads), 'flash':FLASH.copy(),
            'images':[{'file':name, 'offset':offset, 'size':len(payloads[name]), 'sha256':sha256(payloads[name])}
                      for name, offset, _ in IMAGES]}


def encoded_manifest(manifest):
    return (json.dumps(manifest, indent=2, sort_keys=True)+'\n').encode('utf-8')


def load_bundle(directory):
    directory = Path(directory).resolve(strict=True)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    # Never turn manifest-supplied filenames/offsets into filesystem access or
    # flash writes. Only the fixed board layout below can be loaded.
    payloads = {}
    for name, _, _ in IMAGES:
        path = (directory/name).resolve(strict=True)
        if path.parent != directory: raise ValueError('Image points outside its bundle')
        payloads[name] = path.read_bytes()
    expected = manifest_for(payloads)
    if manifest != expected: raise ValueError('Bundle manifest, image checksum or board settings mismatch')
    return expected, [(hex(offset), directory/name) for name, offset, _ in IMAGES]


def build_payloads(root=ROOT, packages=None):
    packages = packages or Path(__import__('os').environ.get('PLATFORMIO_CORE_DIR', str(Path.home()/'.platformio')))/'packages'
    build = root/'.pio/build/round_voice'
    paths = {name:build/name for name, _, _ in IMAGES}
    paths['boot_app0.bin'] = packages/'framework-arduinoespressif32/tools/partitions/boot_app0.bin'
    return {name:path.read_bytes() for name,path in paths.items()}


def create_bundle(root=ROOT, packages=None):
    # Read a snapshot first. Later builds cannot change the bytes being archived.
    payloads = build_payloads(root, packages)
    manifest = manifest_for(payloads)
    encoded = encoded_manifest(manifest)
    directory = root/'local/firmware'/f"round-voice-{manifest['version']}-{sha256(encoded)[:12]}"
    if directory.exists():
        existing, _ = load_bundle(directory)
        if existing != manifest: raise ValueError('Existing archive differs; refusing to overwrite it')
        return directory, manifest
    directory.mkdir(parents=True)
    for name, data in payloads.items():
        with (directory/name).open('xb') as output: output.write(data)
    # A partial archive has no manifest and cannot pass verification.
    with (directory/'manifest.json').open('xb') as output: output.write(encoded)
    load_bundle(directory)
    return directory, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', type=Path, help='Verify an existing bundle without creating or flashing anything')
    args = parser.parse_args()
    try:
        if args.verify: directory, manifest = args.verify.resolve(), load_bundle(args.verify)[0]
        else: directory, manifest = create_bundle()
    except (OSError, ValueError, struct.error) as error:
        raise SystemExit('Firmware bundle refused: '+str(error)) from None
    print(json.dumps({'result':'PASS', 'bundle':str(directory), 'version':manifest['version'],
                      'manifest_sha256':sha256(encoded_manifest(manifest)), 'device_accessed':False}))


if __name__ == '__main__': main()
