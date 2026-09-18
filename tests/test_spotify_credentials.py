import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest
from backend.linux_protection import LinuxProtector
from backend.spotify_credentials import SpotifyCredentials


class SpotifyCredentialTests(unittest.TestCase):
    def test_encrypted_refresh_survives_runtime_removal(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'local').mkdir();cache=root/'runtime';cache.mkdir()
            key=root/'storage.key';key.write_bytes(secrets.token_bytes(32));key.chmod(0o600)
            protector=LinuxProtector(key)
            data=json.dumps({'username':'synthetic-account','auth_type':1,'auth_data':'test-credential-not-real'}).encode()
            store=SpotifyCredentials(root,cache,protector)
            store.runtime.write_bytes(data);store.persist()
            sealed=store.path.read_bytes()
            self.assertNotIn(b'synthetic-account',sealed)
            self.assertNotIn(b'test-credential-not-real',sealed)
            store.persist();self.assertEqual(store.path.read_bytes(),sealed)
            store.runtime.unlink()
            reloaded=SpotifyCredentials(root,cache,protector);reloaded.restore()
            self.assertEqual(reloaded.runtime.read_bytes(),data)
            refreshed=data.replace(b'not-real',b'refreshed')
            reloaded.runtime.write_bytes(refreshed);reloaded.persist()
            self.assertNotEqual(reloaded.path.read_bytes(),sealed)

    def test_corrupt_cache_preserves_encrypted_record(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'local').mkdir();cache=root/'runtime';cache.mkdir()
            key=root/'storage.key';key.write_bytes(secrets.token_bytes(32));key.chmod(0o600)
            store=SpotifyCredentials(root,cache,LinuxProtector(key))
            store.runtime.write_text(json.dumps({'username':'synthetic','auth_type':1,'auth_data':'not-real'}));store.persist()
            sealed=store.path.read_bytes();store.runtime.write_bytes(b'{broken')
            with self.assertRaises(ValueError):store.persist()
            self.assertEqual(store.path.read_bytes(),sealed)
            store.runtime.unlink();store.path.write_text('{broken')
            with self.assertRaises(ValueError):store.restore()
            self.assertFalse(store.runtime.exists())


if __name__=='__main__':unittest.main()
