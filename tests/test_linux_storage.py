import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.linux_protection import LinuxProtector
from backend.settings import SettingsStore, EchoSettings, SettingsUpdate, SettingsUnavailable
from backend.memory import MemoryStore, MemoryUnavailable
from backend.home_access import HomeAccessStore


class LinuxStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.key = self.root / 'storage.key'
        self.key.write_bytes(os.urandom(32));self.key.chmod(0o600)
        self.protector = LinuxProtector(self.key)

    def test_authenticated_randomized_roundtrip_and_corruption(self):
        # A raw key may contain CR/LF and Ctrl-Z; Windows migration tooling must
        # read all 32 bytes rather than interpreting a text-mode EOF marker.
        self.key.write_bytes(b'\r\n\x1a\x00'*8)
        self.protector=LinuxProtector(self.key)
        secret=b'synthetic private preference'
        one=self.protector.encrypt(secret);two=self.protector.encrypt(secret)
        self.assertNotEqual(one,two);self.assertNotIn(secret,one)
        self.assertEqual(self.protector.decrypt(one),secret)
        self.assertEqual(LinuxProtector(self.key).decrypt(two),secret)
        for blob in (one[:-1],one[:-1]+bytes([one[-1]^1]),b'DPAPI ciphertext',b''):
            with self.assertRaises(SettingsUnavailable):self.protector.decrypt(blob)

    def test_wrong_key_and_missing_invalid_files_have_no_fallback(self):
        blob=self.protector.encrypt(b'synthetic key')
        self.key.write_bytes(os.urandom(32))
        with self.assertRaises(SettingsUnavailable):LinuxProtector(self.key).decrypt(blob)
        for value in (b'',b'x'*31,b'x'*33):
            self.key.write_bytes(value)
            with self.assertRaises(SettingsUnavailable):LinuxProtector(self.key)
        self.key.unlink()
        with self.assertRaises(SettingsUnavailable):LinuxProtector(self.key)
        with self.assertRaises(SettingsUnavailable):LinuxProtector('relative.key')

    @unittest.skipUnless(os.name=='posix','Linux filesystem permissions')
    def test_world_readable_key_and_symlink_are_rejected(self):
        self.key.chmod(0o644)
        with self.assertRaises(SettingsUnavailable):LinuxProtector(self.key)
        self.key.chmod(0o600)
        link=self.root/'link';link.symlink_to(self.key)
        with self.assertRaises(SettingsUnavailable):LinuxProtector(link)

    @unittest.skipUnless(os.name=='posix','Linux default storage selection')
    def test_default_stores_use_the_configured_linux_key(self):
        with patch.dict(os.environ,{'ECHO_STORAGE_KEY_FILE':str(self.key)}):
            settings=SettingsStore(self.root)
            self.assertIsInstance(settings.protector,LinuxProtector)
            settings.save(SettingsUpdate(settings=EchoSettings(provider='openai',model='test'),api_key='synthetic-key'))
            memory=MemoryStore(self.root);memory.save('Synthetic default-store fact')
            home=HomeAccessStore(self.root,synchronizer=lambda policy:None)
            home.update({'default_access':'hidden','devices':{}},home.snapshot()['revision'])
            self.assertEqual(SettingsStore(self.root).snapshot()[1]['openai'],'synthetic-key')
            self.assertEqual(len(MemoryStore(self.root).snapshot()),1)
            self.assertEqual(HomeAccessStore(self.root).snapshot()['policy']['default_access'],'hidden')

    def test_settings_memory_and_home_preferences_survive_reopen(self):
        store=SettingsStore(self.root,self.protector)
        store.save(SettingsUpdate(settings=EchoSettings(provider='openai',model='test'),api_key='synthetic-secret'))
        memory=MemoryStore(self.root,self.protector);memory.save('Synthetic private fact: likes jasmine tea.')
        home=HomeAccessStore(self.root,self.protector,lambda p:None)
        policy={'default_access':'hidden','devices':{'light.desk':{'access':'read','room':'Private study'}}}
        home.update(policy,home.snapshot()['revision'])
        for path in (store.path,memory.path,home.path):
            contents=path.read_text()
            self.assertNotIn('synthetic-secret',contents);self.assertNotIn('jasmine',contents);self.assertNotIn('Private study',contents)
        reopened=LinuxProtector(self.key)
        self.assertEqual(SettingsStore(self.root,reopened).snapshot()[1]['openai'],'synthetic-secret')
        self.assertEqual(MemoryStore(self.root,reopened).snapshot(),memory.snapshot())
        self.assertEqual(HomeAccessStore(self.root,reopened).snapshot()['policy'],policy)

    def test_unreadable_protected_memory_is_preserved(self):
        memory=MemoryStore(self.root,self.protector);memory.save('Synthetic fact')
        saved=memory.path.read_bytes();self.key.write_bytes(os.urandom(32))
        broken=MemoryStore(self.root,LinuxProtector(self.key))
        with self.assertRaises(MemoryUnavailable):broken.save('Replacement')
        self.assertEqual(memory.path.read_bytes(),saved)


if __name__=='__main__':unittest.main()
