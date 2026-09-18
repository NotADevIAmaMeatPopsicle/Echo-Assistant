"""Manage Echo's isolated Remote host trial without changing Docker's active context.

No keys travel in argv, shell text, Docker environment metadata, or log output.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import deployment
from backend.settings import SettingsStore, WindowsProtector
from backend.agent_runtime import configuration_fingerprint
from backend.home import HomeConfig
from backend.home_access import HomeAccessStore
from backend.remote_host import install, manage

CONTEXT = deployment.docker_context()
CONTAINER = 'echo-agent'
URL = 'http://127.0.0.1:18643'
PRIVATE = ROOT / 'local/remote-agent.json'

def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, **kwargs)

def connection():
    protector = WindowsProtector()
    if PRIVATE.exists():
        value = json.loads(PRIVATE.read_text())
        return json.loads(protector.decrypt(base64.b64decode(value['protected'])))
    value = {'url': URL, 'token': secrets.token_urlsafe(40)}
    blob = protector.encrypt(json.dumps(value).encode())
    PRIVATE.parent.mkdir(parents=True, exist_ok=True)
    PRIVATE.write_text(json.dumps({'version': 1, 'protected': base64.b64encode(blob).decode()}))
    return value

def save_connection(value):
    blob = WindowsProtector().encrypt(json.dumps(value).encode())
    temporary = PRIVATE.with_suffix('.tmp')
    temporary.write_text(json.dumps({'version': 1, 'protected': base64.b64encode(blob).decode()}))
    temporary.replace(PRIVATE)

def compose(*args):
    # Send only the modules needed by the bounded home tools.
    target = ROOT / 'deploy/remote/backend'
    target.mkdir(exist_ok=True)
    for name in ('__init__.py', 'home.py', 'home_catalog.py', 'home_policy.py', 'core.py'):
        shutil.copyfile(ROOT / 'backend' / name, target / name)
    run('docker', '--context', CONTEXT, 'compose', '-f', str(ROOT / 'deploy/remote/compose.yaml'), *args)

def prepare(home_api=None):
    settings, keys, _ = SettingsStore(ROOT).snapshot()
    from backend.agent_configuration import model_profile
    profile=model_profile(settings,keys)
    config = {
        'model': profile['model_config'],
        'agent': {'max_turns': 12, 'gateway_timeout': 60},
        'tools': {'tool_search': {'enabled':'off'}},
        'platform_toolsets': {'api_server': []},
        'mcp_servers': {'echo-home': {'command':'/opt/hermes/.venv/bin/python',
                                   'args':['/opt/echo/home_tools.py']}},
        'memory': {'memory_enabled': False, 'user_profile_enabled': False, 'nudge_interval': 0},
        'skills': {'creation_nudge_interval': 0},
        'auxiliary': {'background_review': {'enabled': False}},
        'updates': {'check': False},
        'telemetry': {'shared_metrics': {'enabled': False, 'send': False}},
        'terminal': {'cwd': '/opt/data/workspace'},
    }
    data = {'config': config, 'personality': settings.personality,
            'configuration': configuration_fingerprint(settings, keys),
            'home_access': HomeAccessStore(ROOT).snapshot()['policy'],
            'secrets': {profile['secret_name']:profile['provider_key'], 'API_SERVER_KEY': connection()['token']}}
    home = HomeConfig.load(ROOT)
    if home_api:
        if home_api.get('url')!='http://api:8768' or len(home_api.get('token',''))<32:
            raise ValueError('Invalid internal home service')
        data['home_api']=home_api
    elif home.enabled:
        data['home'] = {'enabled':True, 'base_url':home.base_url, 'token':home.token, 'entities':home.entities}
    else:
        config.pop('mcp_servers')
    install(ROOT)
    manage('Save', data)
    return data['configuration']


def activate(fingerprint):
    result = manage('Recover')
    if result['state'] not in {'provisioned', 'ready', 'runtime_starting_or_needs_attention'}:
        raise RuntimeError('Remote host saved the configuration but its container is not ready for provisioning')
    probe = """from pathlib import Path
import json,urllib.request
p=Path('/opt/data/echo-configuration')
ready=False
try:
    with urllib.request.urlopen('http://127.0.0.1:8642/health',timeout=1) as response:
        ready=json.load(response).get('status')=='ok'
except OSError: pass
print(p.read_text() if p.exists() and ready else 'waiting')
"""
    confirmed = ''
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        result = run('docker','--context',CONTEXT,'exec',CONTAINER,
            '/opt/hermes/.venv/bin/python','-c',probe,capture_output=True,timeout=10)
        confirmed = result.stdout.decode().strip()
        if confirmed != 'waiting': break
        time.sleep(.5)
    if confirmed != fingerprint:
        raise RuntimeError('The saved configuration is not active. Use the start action to recreate Echo with it.')
    value = connection()
    value['configuration'] = fingerprint
    save_connection(value)
    print('Configuration encrypted on Remote host; automatic container recovery is installed.')


def provision():
    activate(prepare())

def tunnel():
    import socket
    try:
        with socket.create_connection(('127.0.0.1', 18643), timeout=2):
            record = ROOT / 'local/remote-tunnel.json'
            if record.exists() and os.name == 'nt':
                try:
                    pid = int(json.loads(record.read_text())['pid'])
                    script = ("$ErrorActionPreference='Stop'; "
                        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
                        "$s=Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 18643 -State Listen; "
                        "if ($p.Name -eq 'ssh.exe' -and $s.OwningProcess -contains $p.ProcessId -and "
                        "$p.CommandLine.Contains('127.0.0.1:18643:127.0.0.1:18642') -and "
                        "$p.CommandLine.Contains('" + deployment.ssh_target() + "')) { Write-Output 'owned' }")
                    checked = run('powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',
                        base64.b64encode(script.encode('utf-16-le')).decode(), capture_output=True,
                        timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
                    if checked.stdout.decode().strip() == 'owned': return
                except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                    pass
            raise SystemExit('The trial tunnel port is already occupied.')
    except OSError:
        pass
    log = open(ROOT / 'local/remote-tunnel.log', 'ab')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    child = subprocess.Popen([
        'ssh', '-N', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
        '-L', '127.0.0.1:18643:127.0.0.1:18642', deployment.ssh_target(),
    ], stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags)
    log.close()
    (ROOT / 'local/remote-tunnel.json').write_text(json.dumps({'pid': child.pid, 'port': 18643}))
    time.sleep(.5)
    if child.poll() is not None:
        raise SystemExit('The Remote host SSH tunnel could not start.')
    print('Private SSH tunnel started.')

def status():
    import httpx
    value = connection()
    with httpx.Client(trust_env=False, timeout=5) as client:
        response = client.get(URL + '/health', headers={'Authorization': 'Bearer ' + value['token']})
        response.raise_for_status()
        print(json.dumps(response.json()))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'provision', 'tunnel', 'status', 'stop'])
    action = parser.parse_args().action
    if action in {'start','provision'} and (ROOT/'local/host-target.json').exists():
        raise SystemExit('The device uses its migrated server configuration. Use tools/run.ps1 start; do not reprovision from the preserved laptop settings.')
    if action == 'start':
        fingerprint = prepare()
        compose('up', '-d', '--build', '--force-recreate')
        activate(fingerprint)
        tunnel()
    elif action == 'provision': provision()
    elif action == 'tunnel': tunnel()
    elif action == 'status': status()
    elif action == 'stop': compose('stop')
