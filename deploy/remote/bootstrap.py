"""Trial bootstrap. Credentials and Hermes runtime files remain in tmpfs.

The Windows provisioner supplies a small JSON envelope over authenticated Docker
stdin. Restarting the container clears it and waits for fresh provisioning.
"""
import json
import os
from pathlib import Path
import time
import yaml
import sys
sys.path.insert(0, '/opt/echo')
from backend.home_policy import validate_policy

root = Path('/opt/data')
# The live storage repair relocates package data without restarting a user's
# session. Recreate its links after a plain container restart; newly created
# containers use the dedicated Compose volumes at these same home paths.
for relative, backing in (
    ('lazy-packages', '/opt/echo-packages'),
    ('home/.cache/uv', '/opt/echo-uv-cache'),
):
    target = Path(backing)
    link = root / relative
    if not target.is_dir() or link.is_symlink():
        continue
    if link.is_dir() and not any(link.iterdir()):
        link.rmdir()
    if not link.exists():
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=True)
envelope = root / '.echo-bootstrap.json'
while not envelope.is_file():
    time.sleep(.25)
payload = json.loads(envelope.read_text())
envelope.unlink()
secret_name={'azure-foundry':'AZURE_FOUNDRY_API_KEY','openai-api':'OPENAI_API_KEY',
             'anthropic':'ANTHROPIC_API_KEY','custom':'OPENAI_API_KEY'}.get(payload['config']['model']['provider'])
if secret_name is None: raise SystemExit('Unsupported Echo provider')
allowed = {secret_name, 'API_SERVER_KEY'}
if set(payload['secrets']) != allowed:
    raise SystemExit('Invalid bootstrap credentials')
for name, value in payload['secrets'].items():
    if not isinstance(value, str) or not value or any(ord(c) < 33 for c in value):
        raise SystemExit('Invalid bootstrap credential format')
    os.environ[name] = value
# The gateway's live key resolver reads .env as well as its environment. Replace
# the fresh image's generated key inside tmpfs so both resolve the same identity.
env_file = root / '.env'
env_file.write_text(''.join(name + '=' + json.dumps(value) + '\n'
                            for name, value in payload['secrets'].items()))
os.chmod(env_file, 0o600)
os.environ.update(API_SERVER_ENABLED='true', API_SERVER_HOST='0.0.0.0',
                  API_SERVER_PORT='8642', PYTHONUNBUFFERED='1',
                  HERMES_GATEWAY_NO_SUPERVISE='1')
# Discovery, two device actions and a final reply must fit a normal household
# request. Echo still owns the 55-second deadline and 12-action admission cap.
payload['config'].setdefault('agent',{})['max_turns']=12
# Echo exposes only three bounded home tools. Present their schemas directly;
# deferred discovery adds model turns and a generic batching wrapper here.
payload['config'].setdefault('tools',{}).setdefault('tool_search',{'enabled':'off'})
(root / 'config.yaml').write_text(yaml.safe_dump(payload['config'], sort_keys=False))
(root / 'echo-configuration').write_text(payload['configuration'])
(root / 'SOUL.md').write_text(payload['personality'])
(root / 'echo-access.json').write_text(json.dumps(validate_policy(payload['home_access'])))
os.chmod(root / 'echo-access.json', 0o600)
if payload.get('home_api'):
    service=payload['home_api']
    if service.get('url')!='http://api:8768' or len(service.get('token',''))<32:
        raise ValueError('Invalid internal home service')
    home_file=root/'echo-home-api.json'
    home_file.write_text(json.dumps(service));os.chmod(home_file,0o600)
elif payload.get('home'):
    home_file = root / 'echo-home.json'
    home_file.write_text(json.dumps(payload['home']))
    os.chmod(home_file, 0o600)
os.chmod(root / 'config.yaml', 0o600)
os.chdir(root)
# Hermes may log assistant text. Keep all its output in the same volatile home.
log = os.open(root / 'runtime.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.dup2(log, 1)
os.dup2(log, 2)
os.close(log)
os.execv('/opt/hermes/.venv/bin/hermes', ['hermes', 'gateway', 'run'])
