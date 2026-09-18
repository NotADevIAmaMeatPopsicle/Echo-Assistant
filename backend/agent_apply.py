"""Apply saved Azure settings through the existing trusted Windows host helper.

Only job metadata is written here. Keys leave the container only over Docker's
authenticated stdin/stdout channel to that helper, never through a browser API.
"""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

from .agent_runtime import HermesRuntime, configuration_fingerprint
from .lifecycle import _acquire_lock, _release_lock
from .settings import SettingsStore
from .agent_configuration import model_profile

ACTIVE = {'queued', 'applying'}
TTL = 240


class AgentApply:
    def __init__(self, root, store):
        self.root, self.store = root, store
        self.path = root/'local/agent-apply.json' if root else None

    @contextmanager
    def locked(self):
        if not self.path: raise ValueError('The managed Echo host is required')
        lock = _acquire_lock(self.path.parent, 'agent-apply')
        if lock is None: raise ValueError('Echo settings are being applied; try again shortly')
        try: yield
        finally: _release_lock(lock)

    def read(self):
        if not self.path or not self.path.exists(): return {}
        job = json.loads(self.path.read_text())
        if (not isinstance(job, dict) or job.get('state') not in ACTIVE|{'applied','failed','cancelled'}
                or not re.fullmatch('[a-f0-9]{32}', str(job.get('id', '')))
                or not re.fullmatch('[a-f0-9]{64}', str(job.get('target', '')))
                or type(job.get('created_at')) not in {int,float}):
            raise ValueError('Echo settings application status is unavailable')
        if job['state'] in ACTIVE and not 0 <= time.time()-job['created_at'] < TTL:
            return {**job, 'state':'failed', 'reason':'The host did not apply the change in time. Try Apply again.'}
        return job

    def write(self, job):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({**job, 'updated_at':time.time()}))
        temporary.replace(self.path)

    def set_configuration(self, fingerprint):
        runtime = HermesRuntime(self.root, self.store.protector)
        connection = runtime.connection()
        connection['configuration'] = fingerprint
        temporary = runtime.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version':1, 'protected':base64.b64encode(
            self.store.protector.encrypt(json.dumps(connection).encode())).decode()}))
        temporary.replace(runtime.path)

    def status(self):
        settings, keys, _ = self.store.snapshot()
        if settings.agent_runtime != 'hermes': return {'status':'not_required', 'managed':False}
        managed = os.environ.get('ECHO_CONTAINER') == '1'
        job = self.read()
        target = configuration_fingerprint(settings, keys)
        if job.get('state') in ACTIVE:
            return {'status':job['state'], 'id':job['id'], 'managed':managed}
        try:
            active = HermesRuntime(self.root, self.store.protector).connection().get('configuration') == target
        except RuntimeError: active = False
        if active: return {'status':'active', 'managed':managed}
        if job.get('target') == target and job.get('state') == 'failed':
            return {'status':'failed', 'managed':managed, 'reason':job.get('reason','The change was not applied. Try again.')}
        return {'status':'pending', 'managed':managed}

    def start(self):
        if os.environ.get('ECHO_CONTAINER') != '1':
            raise ValueError('Applying Hermes settings requires the managed Remote host host')
        with self.locked():
            state = self.status()
            if state['status'] in {'active', 'queued', 'applying'}: return state
            settings, keys, _ = self.store.snapshot()
            if settings.agent_runtime != 'hermes': raise ValueError('Choose Hermes before applying agent settings')
            model_profile(settings, keys)
            HermesRuntime(self.root, self.store.protector).connection()
            self.write({'id':uuid4().hex, 'state':'queued', 'created_at':time.time(),
                        'target':configuration_fingerprint(settings, keys)})
            return self.status()

    def cancel(self):
        with self.locked():
            job = self.read()
            if job.get('state') == 'applying':
                raise ValueError('The agent is already restarting. Wait for its result before changing it again.')
            if job.get('state') == 'queued': self.write({**job, 'state':'cancelled'})
            return self.status()

    def claim(self):
        """Called only by the existing Docker-owning host helper."""
        with self.locked():
            job = self.read()
            if job.get('state') == 'applying':
                return {'pending':True, 'resume':True, 'id':job['id'], 'configuration':job['target']}
            if job.get('state') != 'queued': return {'pending':False}
            settings, keys, _ = self.store.snapshot()
            if settings.agent_runtime != 'hermes' or job['target'] != configuration_fingerprint(settings, keys):
                self.write({**job, 'state':'failed', 'reason':'Settings changed. Apply the saved selection again.'})
                return {'pending':False}
            # From this point a restart may occur even if its acknowledgement
            # is lost. Never retain an old fingerprint as proof of a live config.
            self.set_configuration(None)
            self.write({**job, 'state':'applying'})
            return {'pending':True, 'resume':False, 'id':job['id'], 'configuration':job['target'],
                    'settings':settings.model_dump(), **model_profile(settings,keys)}

    def finish(self, identifier, succeeded):
        with self.locked():
            job = self.read()
            if job.get('id') != identifier or job.get('state') != 'applying': return {'applied':False}
            settings, keys, _ = self.store.snapshot()
            if not succeeded or job['target'] != configuration_fingerprint(settings, keys):
                self.write({**job, 'state':'failed', 'reason':'The change could not be confirmed. Review saved settings and try Apply again.'})
                return {'applied':False}
            self.set_configuration(job['target'])
            self.write({**job, 'state':'applied'})
            return {'applied':True}


def main():
    if os.environ.get('ECHO_CONTAINER') != '1': raise SystemExit('Managed container required')
    root = Path('/opt/echo')
    manager = AgentApply(root, SettingsStore(root))
    if sys.argv[1:] == ['claim']: result = manager.claim()
    elif sys.argv[1:] == ['finish']:
        request = json.load(sys.stdin)
        result = manager.finish(request['id'], request['succeeded'] is True)
    else: raise SystemExit('Unsupported configuration operation')
    print(json.dumps(result))


if __name__ == '__main__': main()
