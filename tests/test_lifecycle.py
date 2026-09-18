from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json
import subprocess
import sys
from unittest.mock import patch
from backend.lifecycle import Lifecycle, request_stop


class LifecycleTests(unittest.TestCase):
    def test_crashed_child_record_is_cleaned_without_signalling_a_pid(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            code = "from pathlib import Path; import os,sys; from backend.lifecycle import Lifecycle; owner=Lifecycle(Path(sys.argv[1])); owner.__enter__(); os._exit(23)"
            result = subprocess.run([sys.executable, '-c', code, str(root)],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 23)
            self.assertTrue((root/'local/voice-process.json').exists())
            self.assertFalse(request_stop(root))
            self.assertFalse((root/'local/voice-process.json').exists())
            with Lifecycle(root) as replacement: self.assertFalse(replacement.stopped())

    def test_corrupt_stale_metadata_is_removed_only_when_lock_is_free(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root/'local').mkdir()
            record = root/'local/voice-process.json'; record.write_text('broken')
            self.assertFalse(request_stop(root))
            with Lifecycle(root):
                record.write_text('[]')
                with self.assertRaises(ValueError): request_stop(root)
                self.assertTrue(record.exists())

    def test_failed_record_write_releases_service_lock(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(Path, 'replace', side_effect=PermissionError):
                with self.assertRaises(PermissionError):
                    with Lifecycle(root): pass
            with Lifecycle(root) as replacement: self.assertFalse(replacement.stopped())

    def test_services_have_independent_ownership_and_stop_requests(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with Lifecycle(root) as voice, Lifecycle(root, 'api') as api:
                self.assertTrue(request_stop(root, 'api'))
                self.assertTrue(api.stopped())
                self.assertFalse(voice.stopped())

    def test_exclusive_owner_and_graceful_stop(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with Lifecycle(root) as lifecycle:
                with self.assertRaises(RuntimeError):
                    with Lifecycle(root): pass
                self.assertFalse(lifecycle.stopped())
                self.assertTrue(request_stop(root))
                self.assertTrue(lifecycle.stopped())
            self.assertFalse(request_stop(root))
            with Lifecycle(root) as replacement:
                self.assertFalse(replacement.stopped(), 'A stale stop request must not stop a new run')


if __name__ == '__main__': unittest.main()
