import unittest
from unittest.mock import patch
from backend.cable import encode_pcm
from tools.check_device import fresh_status, check_hardware


class DeviceStatusTests(unittest.TestCase):
    def test_old_boot_report_and_microphone_bytes_cannot_satisfy_fresh_query(self):
        class Port:
            def write(self, data):
                query = data.decode().split()[1]
                self.data = (b'STATUS product=round-voice query=0 volume=0\n'
                             + encode_pcm(b'\0' * 512, 1)
                             + f'STATUS product=round-voice query={query} volume=1\n'.encode())
            def read(self, size):
                result, self.data = self.data[:7], self.data[7:]
                return result
        self.assertEqual(fresh_status(Port())['volume'], '1')

    def test_stale_status_only_times_out_without_claiming_a_pass(self):
        class Port:
            def write(self, data): pass
            def read(self, size): return b'STATUS product=round-voice query=0 volume=0\n'
        with patch('tools.check_device.time.monotonic', side_effect=[0, .1, .2, 9]):
            with self.assertRaisesRegex(RuntimeError, 'No fresh Round Voice status'):
                fresh_status(Port())

    def test_fresh_query_checks_firmware_identity_and_hardware_failure(self):
        class Port:
            def write(self, data): self.query = data.decode().split()[1]
            def read(self, size): return f'STATUS product=other query={self.query}\n'.encode()
        with self.assertRaisesRegex(RuntimeError, 'Unexpected firmware identity'):
            fresh_status(Port())
        with self.assertRaisesRegex(RuntimeError, 'speaker not initialized'):
            check_hardware(dict(display='1', touch='1', mic='1', speaker='0'))

    def test_required_muted_volume_rejects_loud_or_missing_readback(self):
        status=dict(display='1',touch='1',mic='1',speaker='1',audio_errors='0',psram=str(8*1024*1024))
        for volume in ('1', '20', None):
            with self.subTest(volume=volume), self.assertRaisesRegex(RuntimeError, 'Expected volume 0%'):
                check_hardware(dict(status,volume=volume),expected_volume=0)
        check_hardware(dict(status,volume='0'),expected_volume=0)


if __name__ == '__main__': unittest.main()
