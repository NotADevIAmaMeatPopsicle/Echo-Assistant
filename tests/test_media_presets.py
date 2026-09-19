import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from backend.media_presets import MediaPresets,Station
from backend.experiences import ExperienceConflict
from backend.linux_protection import LinuxProtector


class PresetTests(unittest.TestCase):
    def test_explicit_https_streams_and_encrypted_persistence(self):
        for url in ('javascript:alert(1)','http://radio.example/music','https://user:secret@radio.example/stream',
                    'https://127.0.0.1/stream','https://[::1]/stream','https://host.local/stream'):
            with self.assertRaises(ValueError):Station(name='Demo',url=url)
        with TemporaryDirectory() as temp:
            root=Path(temp);key=root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
            protector=LinuxProtector(key);store=MediaPresets(root,protector)
            state=store.save({'revision':0,'stations':[{'name':'Demo radio','url':'https://radio.example/music.mp3'}]})
            self.assertNotIn(b'radio.example',store.path.read_bytes())
            self.assertEqual(MediaPresets(root,protector).snapshot(),state)
            with self.assertRaises(ExperienceConflict):store.save({'revision':0,'stations':[]})
