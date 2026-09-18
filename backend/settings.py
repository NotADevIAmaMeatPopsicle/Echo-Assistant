"""Echo configuration; provider credentials are encrypted and never returned."""
import base64
import ctypes
from ctypes import wintypes
import ipaddress
import json
import os
import re
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

PERSONALITY = (
    "You are Echo, a dedicated personal assistant. Be brainy, calm, and casually conversational: "
    "a relaxed Jarvis with a little dry wit. Be helpful first; occasional light snark is welcome "
    "when the moment fits, never mean or condescending. Avoid theatrical roleplay, corporate "
    "filler, and constant jokes. Be honest about uncertainty. For spoken answers, lead with the "
    "useful part and keep it brief unless asked to explain."
)


class EchoSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_default=True)
    provider: Literal['disabled', 'local', 'openai', 'anthropic', 'azure'] = 'disabled'
    agent_runtime: Literal['direct', 'hermes'] = 'direct'
    model: str = Field(default='', max_length=160, pattern=r'^[a-zA-Z0-9_./:@+\-]*$')
    local_url: str = 'http://127.0.0.1:11434/v1'
    azure_url: str = ''
    personality: str = Field(default=PERSONALITY, min_length=1, max_length=6000)
    max_output_tokens: int = Field(default=1024, strict=True, ge=256, le=4096)
    stt_engine: Literal['vosk', 'whisper'] = 'vosk'
    tts_engine: Literal['sapi', 'kokoro', 'pocket'] = 'sapi'
    tts_voice: str = Field(default='', max_length=160)
    tts_rate: int = Field(default=0, strict=True, ge=-5, le=5)
    web_lookup: Literal['off','auto'] = 'off'
    memory_enabled: bool = True

    @field_validator('azure_url')
    @classmethod
    def azure_endpoint(cls, value):
        if not value.strip(): return ''
        try:
            url = urlsplit(value.strip())
            if (url.scheme != 'https' or url.username or url.password or url.query or url.fragment
                    or url.port not in (None,443) or url.path.rstrip('/') not in ('','/openai/v1')
                    or not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.(?:openai\.azure\.com|services\.ai\.azure\.com)',url.hostname or '')):
                raise ValueError()
        except ValueError:
            raise ValueError('Use your HTTPS Azure resource URL, optionally ending in /openai/v1') from None
        return 'https://' + url.hostname + '/openai/v1'

    @model_validator(mode='after')
    def azure_configured(self):
        if self.agent_runtime == 'hermes' and self.provider == 'disabled':
            raise ValueError('Choose a provider for Hermes, or use Direct for offline tools')
        if self.provider == 'azure' and not self.azure_url:
            raise ValueError('Enter the Azure resource endpoint')
        return self

    @field_validator('local_url')
    @classmethod
    def local_only(cls, value):
        try:
            url = urlsplit(value)
            host = url.hostname or ''
            if host != 'localhost':
                address = ipaddress.ip_address(host)
                if not (address.is_private or address.is_loopback) or address.is_unspecified or address.is_multicast:
                    raise ValueError()
            if (url.scheme not in {'http', 'https'} or url.username or url.password or url.query or url.fragment
                    or url.path.rstrip('/') != '/v1' or not url.port):
                raise ValueError()
        except ValueError:
            raise ValueError('Use a localhost or private IP endpoint with a port and /v1 path') from None
        return value.rstrip('/')


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    settings: EchoSettings
    api_key: SecretStr | None = Field(default=None, max_length=1024)
    clear_key: bool = False


class SettingsUnavailable(RuntimeError):
    pass


class WindowsProtector:
    """DPAPI is bound to this Windows user. No plaintext fallback."""
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    def _crypt(self, data, encrypt):
        if os.name != 'nt':
            raise SettingsUnavailable('Credential storage requires Windows DPAPI')
        buffer = ctypes.create_string_buffer(data)
        source = self.Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        result = self.Blob()
        crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        function = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
        function.restype = wintypes.BOOL
        function.argtypes = [ctypes.POINTER(self.Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(self.Blob)]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
            raise SettingsUnavailable('Windows could not unlock the saved credentials')
        try: return ctypes.string_at(result.data, result.size)
        finally: kernel32.LocalFree(result.data)

    def encrypt(self, data): return self._crypt(data, True)
    def decrypt(self, data): return self._crypt(data, False)


class SettingsStore:
    def __init__(self, root: Path | None = None, protector=None):
        self.path = root/'local/echo-settings.json' if root else None
        self.protector = protector or default_protector()
        self.lock = RLock()
        self.settings = EchoSettings()
        self.keys = {}
        self.revision = 0
        if self.path and self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                self.settings = EchoSettings.model_validate(saved['settings'])
                if saved.get('credentials'):
                    self.keys = json.loads(self.protector.decrypt(base64.b64decode(saved['credentials'], validate=True)))
                if not isinstance(self.keys, dict) or any(k not in {'openai', 'anthropic', 'local', 'azure'} or
                        not isinstance(v, str) or not 1 <= len(v) <= 1024 for k, v in self.keys.items()):
                    raise ValueError()
            except (OSError, ValueError, KeyError, TypeError):
                raise SettingsUnavailable('Echo settings could not be read; the saved file was preserved') from None

    def snapshot(self):
        with self.lock:
            return self.settings.model_copy(), dict(self.keys), self.revision

    def public(self):
        settings, keys, _ = self.snapshot()
        return {'settings': settings.model_dump(), 'credentials': {p: bool(keys.get(p)) for p in ('local', 'openai', 'anthropic', 'azure')}}

    def save(self, update: SettingsUpdate):
        with self.lock:
            keys = dict(self.keys)
            provider = update.settings.provider
            if update.clear_key: keys.pop(provider, None)
            if update.api_key is not None and update.api_key.get_secret_value().strip():
                key = update.api_key.get_secret_value().strip()
                if provider == 'disabled' or any(ord(c) < 33 or ord(c) > 126 for c in key):
                    raise ValueError('Select a provider and supply a valid API key')
                keys[provider] = key
            payload = {'settings': update.settings.model_dump(), 'credentials': None}
            if keys:
                payload['credentials'] = base64.b64encode(self.protector.encrypt(json.dumps(keys).encode())).decode('ascii')
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix('.tmp')
                try:
                    temporary.write_text(json.dumps(payload, indent=2), encoding='utf-8')
                    temporary.replace(self.path)
                except OSError:
                    raise SettingsUnavailable('Echo settings could not be saved') from None
            self.settings = update.settings.model_copy()
            self.keys = keys
            self.revision += 1
            return self.public()


def default_protector():
    if os.name == 'nt': return WindowsProtector()
    from .linux_protection import LinuxProtector
    return LinuxProtector()


def speech_settings(root=None):
    # Reads only nonsecret speech options; the separate bridge never needs provider keys.
    path = (root or Path(__file__).resolve().parents[1])/'local/echo-settings.json'
    if not path.exists(): return EchoSettings()
    try: return EchoSettings.model_validate(json.loads(path.read_text(encoding='utf-8'))['settings'])
    except (OSError, ValueError, KeyError, TypeError):
        raise SettingsUnavailable('Speech settings unavailable') from None
