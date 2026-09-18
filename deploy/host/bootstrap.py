"""Private Linux API bootstrap. No voice listener is started by this entry point."""
import base64
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path('/opt/echo')
RUNTIME=Path('/run/echo')
sys.path.insert(0,str(ROOT))
def bootstrap_error(kind,error,tb):
    import traceback
    frames=traceback.extract_tb(tb)
    detail={'error_type':kind.__name__,'line':frames[-1].lineno if frames else None}
    try:(RUNTIME/'bootstrap-error.json').write_text(json.dumps(detail))
    except OSError:pass
sys.excepthook=bootstrap_error
envelope=RUNTIME/'bootstrap.json'
while not envelope.is_file():time.sleep(.25)
payload=json.loads(envelope.read_text())
envelope.unlink()
key=base64.b64decode(payload['storage_key'],validate=True)
if len(key)!=32:raise ValueError('Invalid storage key')
def private_file(name,content):
    path=RUNTIME/name
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'wb') as stream:stream.write(content)
    os.chmod(path,0o600)
    return path

private_file('storage.key',key)
for field,name in [('api_token','api-token'),('home_tools_token','home-tools-token')]:
    value=payload[field]
    if not isinstance(value,str) or len(value)<32:raise ValueError('Invalid private credential')
    private_file(name,value.encode())
local=ROOT/'local';local.mkdir(exist_ok=True)
def link(name,target):
    path=local/name
    if path.is_symlink():
        if path.readlink()!=target:raise ValueError('Unexpected runtime link')
    elif path.exists():raise ValueError('Unexpected persistent secret or model directory')
    else:path.symlink_to(target)
link('api-token',RUNTIME/'api-token')
link('models',Path('/models'))
(RUNTIME/'spotify').mkdir(mode=0o700,exist_ok=True)
link('spotify',RUNTIME/'spotify')
if payload.get('wifi'):
    from backend.transport import MAC,local_address
    import re
    wifi=payload['wifi']
    if (wifi.get('enabled') is not True or wifi.get('mac')!=MAC or not local_address(wifi.get('host',''))
            or not re.fullmatch('[0-9a-f]{64}',wifi.get('key',''))):
        raise ValueError('Invalid paired device configuration')
    private_file('wifi.json',json.dumps(wifi).encode());link('wifi.json',RUNTIME/'wifi.json')
if payload.get('music'):
    (local/'music.json').write_text(json.dumps(payload['music']))
if payload.get('home'):
    home=dict(payload['home'])
    private_file('ha-token',home.pop('token').encode())
    (local/'home.json').write_text(json.dumps(home))
    link('ha-token',RUNTIME/'ha-token')

from backend.settings import SettingsStore, EchoSettings, SettingsUpdate
if payload.get('migration') and os.environ.get('ECHO_DEPLOYMENT_MODE')=='device':
    from backend.host_migration import apply_migration
    apply_migration(ROOT,payload['migration'])
if not (local/'echo-settings.json').exists():
    settings=EchoSettings.model_validate(payload['settings'])
    store=SettingsStore(ROOT)
    store.save(SettingsUpdate(settings=settings,api_key=payload['provider_key']))
if not (local/'home-access.json').exists():
    from backend.home_access import HomeAccessStore
    access=HomeAccessStore(ROOT,synchronizer=lambda policy:None)
    access.update(payload['home_access'],access.snapshot()['revision'])
# Preparation rewrites host-specific model paths without network access.
import subprocess
worker_env=dict(os.environ,PYTHONHOME='/opt/python312',LD_LIBRARY_PATH='/opt/python312/lib',
                HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
if (Path('/models')/'pocket-tts-english-official/languages/english/model.safetensors').is_file():
    subprocess.run(['/opt/python312/bin/python3.12','tools/prepare_tts.py'],cwd=ROOT,env=worker_env,
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
(RUNTIME/'bootstrapped').touch(mode=0o600)
del payload,key
os.execv(sys.executable,[sys.executable,'-m','backend.container_host'])
