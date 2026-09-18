import hashlib
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import firmware_bundle as bundle
from tools import flash_device as flash


class FirmwareBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packages = self.root/'packages'
        self.build = self.root/'.pio/build/round_voice'; self.build.mkdir(parents=True)
        header = bytearray(24); header[0] = 0xe9; struct.pack_into('<H', header, 12, 9)
        self.header = bytes(header)
        (self.build/'bootloader.bin').write_bytes(self.header)
        (self.build/'firmware.bin').write_bytes(self.header+b'STATUS product=round-voice version=0.8.2 protocol=1')
        table = bytearray()
        for kind, subtype, offset, size, name in bundle.PARTITIONS:
            table.extend(struct.pack('<HBBII16sI', 0x50aa, kind, subtype, offset, size, name, 0))
        table.extend(b'\xeb\xeb'+b'\xff'*14+hashlib.md5(table).digest())
        table.extend(b'\xff'*(3072-len(table)))
        (self.build/'partitions.bin').write_bytes(table)
        boot_app = self.packages/'framework-arduinoespressif32/tools/partitions/boot_app0.bin'
        boot_app.parent.mkdir(parents=True); boot_app.write_bytes(b'\xff'*8192)

    def create(self): return bundle.create_bundle(self.root, self.packages)

    def test_archive_survives_rebuild_and_is_idempotent(self):
        directory, manifest = self.create()
        original = (directory/'firmware.bin').read_bytes()
        self.assertEqual(self.create(), (directory, manifest))
        (self.build/'firmware.bin').write_bytes(original.replace(b'0.8.2', b'0.8.3'))
        newer, new_manifest = self.create()
        self.assertNotEqual(newer, directory)
        self.assertEqual(new_manifest['version'], '0.8.3')
        self.assertEqual((directory/'firmware.bin').read_bytes(), original)
        self.assertEqual(bundle.load_bundle(directory)[0], manifest)

    def test_modified_or_missing_image_rejected(self):
        directory, _ = self.create()
        image = directory/'firmware.bin'; original = image.read_bytes()
        image.write_bytes(original+b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'): bundle.load_bundle(directory)
        image.unlink()
        with self.assertRaises(FileNotFoundError): bundle.load_bundle(directory)

    def test_manifest_cannot_redirect_flash_paths_offsets_or_board(self):
        directory, original = self.create()
        for change in ('path', 'offset', 'flash', 'mac', 'version'):
            manifest = json.loads(json.dumps(original))
            if change=='path': manifest['images'][0]['file']='../outside.bin'
            if change=='offset': manifest['images'][0]['offset']=0x9000
            if change=='flash': manifest['flash']['mode']='qio'
            if change=='mac': manifest['device_mac']='00:00:00:00:00:00'
            if change=='version': manifest['version']='9.9.9'
            with self.subTest(change=change):
                (directory/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
                with self.assertRaises(ValueError): bundle.load_bundle(directory)

    def test_wrong_chip_and_oversize_are_rejected_before_archive_creation(self):
        image = self.build/'bootloader.bin'
        wrong = bytearray(self.header); struct.pack_into('<H', wrong, 12, 0)
        for data in (bytes(wrong), self.header+b'\0'*0x8000):
            image.write_bytes(data)
            with self.assertRaises(ValueError): self.create()
        self.assertFalse((self.root/'local/firmware').exists())

    def test_partition_relocation_rejected_even_with_correct_checksum(self):
        path = self.build/'partitions.bin'; table = bytearray(path.read_bytes())
        struct.pack_into('<I', table, 4, 0x10000)  # Move NVS into the app write region.
        position = len(bundle.PARTITIONS)*32
        table[position+16:position+32] = hashlib.md5(table[:position]).digest()
        path.write_bytes(table)
        with self.assertRaisesRegex(ValueError, 'layout'): self.create()

    def test_flash_refuses_live_bridge_before_device_access(self):
        (self.root/'local').mkdir(); (self.root/'local/voice-process.json').write_text('{}')
        with patch.object(flash, 'ROOT', self.root), patch('sys.argv', ['flash_device.py', 'COM3','--mac','02:00:00:00:00:01','--backup','unused.bin','--backup-sha256','0'*64]):
            with patch.object(flash.list_ports, 'comports') as ports, patch.object(flash.subprocess, 'run') as run:
                with self.assertRaisesRegex(SystemExit, 'Stop the voice'): flash.main()
                ports.assert_not_called(); run.assert_not_called()

    def test_bad_bundle_and_wrong_mac_never_write_flash(self):
        directory, _ = self.create()
        backup = self.root/'backups/before-round-voice-20260916.bin'; backup.parent.mkdir()
        with backup.open('wb') as output: output.truncate(16*1024*1024)
        with backup.open('rb') as source: digest = hashlib.file_digest(source, 'sha256').hexdigest()
        tool = self.root/'.platformio/packages/tool-esptoolpy/esptool.py'
        tool.parent.mkdir(parents=True); tool.write_text('# test placeholder')
        argv = ['flash_device.py', 'COM3', '--bundle', str(directory), '--mac','02:00:00:00:00:01','--backup',str(backup),'--backup-sha256',digest]
        port = SimpleNamespace(device='COM3', vid=0x303a, pid=0x1001, serial_number='02:00:00:00:00:01')
        with patch.object(flash, 'ROOT', self.root), patch('sys.argv', argv):
            with patch.object(Path, 'home', return_value=self.root), patch.object(flash.list_ports, 'comports', return_value=[port]):
                with patch.object(flash.subprocess, 'run', return_value=SimpleNamespace(stdout='MAC: 00:00:00:00:00:00')) as run:
                    with self.assertRaisesRegex(SystemExit, 'MAC did not match'): flash.main()
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(run.call_args.args[0][-1], 'read_mac')
                (directory/'firmware.bin').write_bytes(b'corrupt')
                with patch.object(flash.subprocess, 'run') as run:
                    with self.assertRaisesRegex(SystemExit, 'no device writes'): flash.main()
                    run.assert_not_called()


if __name__ == '__main__': unittest.main()
