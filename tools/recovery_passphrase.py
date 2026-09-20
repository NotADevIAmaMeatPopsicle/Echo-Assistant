"""Portable recovery-envelope protection with fixed-cost scrypt and AES-256-GCM."""
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC=b'ECHOPBK1'
AAD=b'Echo portable recovery envelope, version 1'
LIMIT=40_000_000


class PassphraseError(ValueError):
    pass


class PassphraseProtector:
    archive_envelope='recovery.passphrase'

    def __init__(self,passphrase):
        if not isinstance(passphrase,str) or len(passphrase)<16 or len(passphrase.encode('utf-8'))>1024:
            raise PassphraseError('Use a recovery passphrase of at least 16 characters and at most 1024 UTF-8 bytes.')
        self._phrase=passphrase.encode('utf-8')

    def _cipher(self,salt):
        # Fixed parameters cannot be inflated by an untrusted archive header.
        key=Scrypt(salt=salt,length=32,n=2**17,r=8,p=1).derive(self._phrase)
        return AESGCM(key)

    def encrypt(self,data):
        if not isinstance(data,bytes) or len(data)>LIMIT-52:raise ValueError('Recovery envelope is too large')
        salt=os.urandom(16);nonce=os.urandom(12);header=MAGIC+salt+nonce
        return header+self._cipher(salt).encrypt(nonce,data,AAD+header)

    def decrypt(self,data):
        if not isinstance(data,bytes) or not data.startswith(MAGIC) or not 52<=len(data)<=LIMIT:
            raise PassphraseError('This is not a supported portable recovery envelope.')
        try:return self._cipher(data[8:24]).decrypt(data[24:36],data[36:],AAD+data[:36])
        except InvalidTag:
            raise PassphraseError('The recovery passphrase was not accepted, or the archive was damaged.') from None
