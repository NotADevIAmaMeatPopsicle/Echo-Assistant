import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.runtime_paths import worker_python
from backend.whisper import available


class WhisperRuntimeTests(unittest.TestCase):
    def test_platform_default_and_explicit_container_interpreter(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            expected = root/'local/stt-python'/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            self.assertEqual(worker_python(root, 'stt'), expected)
            interpreter = root/'container-python'
            with patch.dict(os.environ, {'ECHO_STT_PYTHON': str(interpreter)}):
                self.assertEqual(worker_python(root, 'stt'), interpreter)
            with patch.dict(os.environ, {'ECHO_STT_PYTHON': 'relative/python'}):
                with self.assertRaises(ValueError): worker_python(root, 'stt')

    def test_available_requires_interpreter_and_complete_local_model(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            interpreter = root/'python'
            model = root/'local/models/faster-whisper-base.en'
            model.mkdir(parents=True)
            with patch.dict(os.environ, {'ECHO_STT_PYTHON': str(interpreter)}):
                self.assertFalse(available(None))
                self.assertFalse(available(root))
                interpreter.touch()
                for name in ('model.bin', 'config.json', 'tokenizer.json'):
                    (model/name).touch()
                self.assertFalse(available(root))
                (model/'vocabulary.txt').touch()
                self.assertTrue(available(root))
