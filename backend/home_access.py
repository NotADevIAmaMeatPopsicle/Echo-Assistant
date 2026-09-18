"""Encrypted home access preferences, with explicit remote application status."""
import base64
import json
from pathlib import Path
from threading import RLock
from .home_policy import validate_policy, policy_hash
from .settings import default_protector


class HomeAccessUnavailable(RuntimeError):
    pass


class HomeAccessStore:
    def __init__(self, root=None, protector=None, synchronizer=None):
        self.path = Path(root) / 'local/home-access.json' if root else None
        self.protector = protector or default_protector()
        self.synchronizer = synchronizer
        self.lock = RLock()
        self.policy = {'default_access': 'read', 'devices': {}}
        self.applied = None
        self.error = False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size > 500_000: raise ValueError()
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if data['version'] != 1: raise ValueError()
                saved = json.loads(self.protector.decrypt(base64.b64decode(data['protected'], validate=True)))
                self.policy = validate_policy(saved['policy'])
            except (ValueError, KeyError, TypeError, OSError, RuntimeError):
                self.error = True

    def snapshot(self):
        with self.lock:
            if self.error: raise HomeAccessUnavailable('Home access settings could not be read. The saved file was preserved.')
            revision = policy_hash(self.policy)
            return {'policy': validate_policy(self.policy), 'revision': revision,
                    'applied': self.applied == revision}

    def ensure_applied(self):
        with self.lock:
            state = self.snapshot()
            if state['applied']: return
            if self.synchronizer is None:
                raise HomeAccessUnavailable('Home access settings have not reached Remote host. Retry from the Devices page.')
            try:
                self.synchronizer(state['policy'])
            except (RuntimeError, OSError):
                raise HomeAccessUnavailable('Home access settings are saved locally but Remote host has not confirmed them. Retry from the Devices page.') from None
            self.applied = state['revision']

    def update(self, policy, expected_revision):
        policy = validate_policy(policy)
        with self.lock:
            if expected_revision != self.snapshot()['revision']:
                raise ValueError('Device settings changed in another page. Refresh before saving.')
            if self.path:
                temporary = self.path.with_suffix('.tmp')
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    blob = self.protector.encrypt(json.dumps({'policy': policy}).encode())
                    temporary.write_text(json.dumps({'version': 1, 'protected': base64.b64encode(blob).decode()}), encoding='utf-8')
                    temporary.replace(self.path)
                except (OSError, RuntimeError):
                    raise HomeAccessUnavailable('Home access settings could not be saved. Your previous choices are unchanged.') from None
            self.policy = policy
            self.ensure_applied()
            return self.snapshot()
