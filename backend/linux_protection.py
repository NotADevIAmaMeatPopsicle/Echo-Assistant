"""Authenticated Linux storage encryption, using a separately provisioned key file."""
import os
from pathlib import Path
import stat

MAGIC = b'ECHOAES1'
CONTEXT = b'Echo protected local data, version 1'


class LinuxProtector:
    def __init__(self, key_path=None):
        from .settings import SettingsUnavailable
        path = Path(key_path or os.environ.get('ECHO_STORAGE_KEY_FILE', ''))
        if not path.is_absolute():
            raise SettingsUnavailable('Linux storage requires an absolute ECHO_STORAGE_KEY_FILE path')
        descriptor = None
        try:
            # Refuse symlinks and verify the opened object, avoiding a path-check race.
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size != 32:
                raise ValueError()
            if os.name == 'posix' and (stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.geteuid()):
                raise ValueError()
            self._key = os.read(descriptor, 33)
            if len(self._key) != 32: raise ValueError()
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            self._cipher = AESGCM(self._key)
        except (OSError, ValueError, ImportError):
            raise SettingsUnavailable('Linux storage key is missing, unreadable, or not a private 32-byte file owned by this service') from None
        finally:
            if descriptor is not None: os.close(descriptor)

    def encrypt(self, data):
        from .settings import SettingsUnavailable
        if not isinstance(data, bytes): raise SettingsUnavailable('Invalid protected data')
        nonce = os.urandom(12)
        return MAGIC + nonce + self._cipher.encrypt(nonce, data, CONTEXT)

    def decrypt(self, data):
        from .settings import SettingsUnavailable
        from cryptography.exceptions import InvalidTag
        if not isinstance(data, bytes) or not data.startswith(MAGIC) or len(data) < len(MAGIC) + 28:
            raise SettingsUnavailable('Saved data is not in the Linux encrypted storage format')
        try:
            return self._cipher.decrypt(data[8:20], data[20:], CONTEXT)
        except (ValueError, InvalidTag):
            raise SettingsUnavailable('Saved data could not be authenticated with this storage key') from None
