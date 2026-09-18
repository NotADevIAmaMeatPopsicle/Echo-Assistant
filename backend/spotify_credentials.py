"""Encrypt the receiver's credentials at rest; its live copy belongs in tmpfs."""
import base64
import hashlib
import json
import os
from pathlib import Path
from .settings import default_protector


class SpotifyCredentials:
    def __init__(self, root, runtime, protector=None):
        self.path=Path(root)/'local/spotify-credentials.json'
        self.runtime=Path(runtime)/'credentials.json'
        self.protector=protector or default_protector()
        self.digest=None

    @staticmethod
    def validate(data):
        if len(data)>16384: raise ValueError('Spotify credential record is too large')
        value=json.loads(data)
        if (not isinstance(value,dict) or set(value)!={'username','auth_type','auth_data'}
                or not isinstance(value['username'],str) or not 1<=len(value['username'])<=320
                or type(value['auth_type']) is not int or not 0<=value['auth_type']<=255
                or not isinstance(value['auth_data'],str) or not 1<=len(value['auth_data'])<=12000):
            raise ValueError('Invalid Spotify credential record')
        return data

    def restore(self):
        if not self.path.exists(): return
        sealed=json.loads(self.path.read_text())
        if sealed.get('version')!=1:raise ValueError('Unknown Spotify credential format')
        data=self.validate(self.protector.decrypt(base64.b64decode(sealed['protected'],validate=True)))
        self.runtime.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.runtime.write_bytes(data);os.chmod(self.runtime,0o600)
        self.digest=hashlib.sha256(data).digest()

    def persist(self):
        if not self.runtime.exists():return
        data=self.validate(self.runtime.read_bytes())
        digest=hashlib.sha256(data).digest()
        if digest==self.digest:return
        sealed=self.protector.encrypt(data)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(sealed).decode()}))
        os.chmod(temporary,0o600);temporary.replace(self.path)
        self.digest=digest
