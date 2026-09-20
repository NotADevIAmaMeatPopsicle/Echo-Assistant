"""Portable archives use generated fixtures; no real credentials or host access."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch,Mock
import zipfile

from tools.recovery_archive import write_archive,read_archive,read_photo,protection_kind,ENVELOPE,PORTABLE_ENVELOPE
from tools.recovery_passphrase import PassphraseProtector,PassphraseError,MAGIC
from tools.backup_remote import portable_copy,passphrase_protector,restore
from backend.linux_protection import LinuxProtector


class PortableRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.phrase='Synthetic only recovery passphrase 2026'
        self.protector=PassphraseProtector(self.phrase)
        key=self.root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
        self.local=LinuxProtector(key)
        self.photo_name='display-photos/'+'a'*32+'.photo'
        self.photo=self.local.encrypt(b'private synthetic photo')
        self.payload={'kind':'echo-remote','version':2,'created_at':1,
            'files':{'echo-memory.json':{'data':base64.b64encode(b'{"synthetic":"private memory"}').decode(),
                'sha256':hashlib.sha256(b'{"synthetic":"private memory"}').hexdigest()}},
            'photos':{self.photo_name:{'size':len(self.photo),'sha256':hashlib.sha256(self.photo).hexdigest()}},
            'bootstrap':{'api':{'storage_key':base64.b64encode(key.read_bytes()).decode()},'agent':{}}}
        self.archive=self.root/'portable.echo-backup'

    def write(self):write_archive(self.archive,self.payload,self.protector,lambda _:self.photo)

    def test_independent_unlock_and_encrypted_photos(self):
        self.write();self.assertEqual(protection_kind(self.archive),'passphrase')
        self.assertEqual(read_archive(self.archive,PassphraseProtector(self.phrase)),self.payload)
        data=self.archive.read_bytes()
        for private in [self.phrase.encode(),b'private memory',b'private synthetic photo',b'storage_key']:
            self.assertNotIn(private,data)
        self.assertEqual(read_photo(self.archive,self.photo_name,self.payload['photos'][self.photo_name]),self.photo)
        with self.assertRaises(FileExistsError):self.write()

    def test_wrong_passphrase_tampering_and_protection_mixup(self):
        self.write()
        with self.assertRaises(PassphraseError):read_archive(self.archive,PassphraseProtector('Wrong synthetic recovery phrase'))
        with patch('tools.backup_remote.install') as install,patch('tools.backup_remote.docker') as docker:
            with self.assertRaises(PassphraseError):restore(self.archive,PassphraseProtector('Wrong synthetic recovery phrase'))
            install.assert_not_called();docker.assert_not_called()
        with self.assertRaises(ValueError):read_archive(self.archive,self.local)
        with zipfile.ZipFile(self.archive) as source:envelope=source.read(PORTABLE_ENVELOPE)
        damaged=envelope[:-1]+bytes([envelope[-1]^1])
        with self.assertRaises(PassphraseError):self.protector.decrypt(damaged)
        with zipfile.ZipFile(self.archive,'a') as source:source.writestr(ENVELOPE,b'not a second valid envelope')
        with self.assertRaises(ValueError):protection_kind(self.archive)
        with self.assertRaises(ValueError):read_archive(self.archive,self.protector)

    def test_new_salt_nonce_bounds_and_exact_unicode_passphrase(self):
        a=self.protector.encrypt(b'synthetic');b=self.protector.encrypt(b'synthetic')
        self.assertNotEqual(a,b);self.assertEqual(self.protector.decrypt(a),b'synthetic')
        for value in ['short','a'*1025,None]:
            with self.assertRaises(PassphraseError):PassphraseProtector(value)
        for value in [b'',MAGIC+b'x'*20,b'unsupported'+a]:
            with self.assertRaises(PassphraseError):self.protector.decrypt(value)
        unicode_phrase='Un café pour une sauvegarde sûre'
        data=PassphraseProtector(unicode_phrase).encrypt(b'unicode')
        self.assertEqual(PassphraseProtector(unicode_phrase).decrypt(data),b'unicode')

    def test_local_conversion_preserves_original_and_never_contacts_host(self):
        original=self.root/'original.echo-backup'
        write_archive(original,self.payload,self.local,lambda _:self.photo)
        before=original.read_bytes()
        with patch('tools.backup_remote.ROOT',self.root),patch('tools.backup_remote.docker',side_effect=AssertionError('Host access')):
            result=portable_copy(original,self.local,self.protector)
        self.assertEqual(original.read_bytes(),before)
        self.assertEqual(read_archive(result,PassphraseProtector(self.phrase)),self.payload)
        self.assertEqual(read_photo(result,self.photo_name,self.payload['photos'][self.photo_name]),self.photo)

    def test_private_terminal_required_and_confirmation(self):
        with patch('tools.backup_remote.sys.stdin.isatty',return_value=False),patch('tools.backup_remote.getpass.getpass') as prompt:
            with self.assertRaises(PassphraseError):passphrase_protector(confirm=True)
            prompt.assert_not_called()
        with patch('tools.backup_remote.sys.stdin.isatty',return_value=True),patch('tools.backup_remote.getpass.getpass',side_effect=[self.phrase,'not the same']):
            with self.assertRaises(PassphraseError):passphrase_protector(confirm=True)
        with patch('tools.backup_remote.sys.stdin.isatty',return_value=True),patch('tools.backup_remote.getpass.getpass',side_effect=[self.phrase,self.phrase]):
            self.assertIsInstance(passphrase_protector(confirm=True),PassphraseProtector)


if __name__=='__main__':unittest.main()
