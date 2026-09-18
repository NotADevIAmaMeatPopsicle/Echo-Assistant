"""Provision the isolated validation API. The working device host is untouched."""
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import deployment
from backend.settings import SettingsStore, WindowsProtector
from backend.home import HomeConfig
from backend.home_access import HomeAccessStore
from backend.remote_host import install, manage

def connection():
    path=ROOT/'local/remote-api.json'
    protector=WindowsProtector()
    if path.exists():
        return json.loads(protector.decrypt(base64.b64decode(json.loads(path.read_text())['protected'])))
    value={'url':'http://127.0.0.1:18669','token':secrets.token_urlsafe(40),'home_tools_token':secrets.token_urlsafe(40)}
    sealed=protector.encrypt(json.dumps(value).encode())
    path.write_text(json.dumps({'version':1,'protected':base64.b64encode(sealed).decode()}))
    return value

def provision():
    if (ROOT/'local/host-target.json').exists():
        raise RuntimeError('Use the device launcher after migration; validation provisioning is disabled')
    settings,keys,_=SettingsStore(ROOT).snapshot()
    if settings.provider!='azure' or not keys.get('azure'):raise ValueError('Configure Azure before API validation')
    value=connection()
    candidate=settings.model_dump();candidate['agent_runtime']='direct'
    home=HomeConfig.load(ROOT)
    payload={'settings':candidate,'provider_key':keys['azure'],'api_token':value['token'],
        'home_tools_token':value['home_tools_token'],'home_access':HomeAccessStore(ROOT).snapshot()['policy']}
    if home.enabled:payload['home']={'enabled':True,'base_url':home.base_url,'token':home.token,'entities':home.entities}
    install(ROOT);manage('SaveApi',payload)
    subprocess.run(['docker','--context',deployment.docker_context(),'compose','-f',str(ROOT/'deploy/host/compose.yaml'),
        'up','-d','--no-build','api'],check=True)
    result=manage('RecoverApi')
    print(json.dumps(result))

def tunnel():
    try:
        with socket.create_connection(('127.0.0.1',18669),timeout=1):
            record=ROOT/'local/remote-api-tunnel.json'
            if record.exists() and os.name=='nt':
                pid=int(json.loads(record.read_text())['pid'])
                script=("$ErrorActionPreference='Stop'; "
                    f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
                    "$s=Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 18669 -State Listen; "
                    "if ($p.Name -eq 'ssh.exe' -and $s.OwningProcess -contains $p.ProcessId -and "
                    "$p.CommandLine.Contains('127.0.0.1:18669:127.0.0.1:18668') -and "
                    "$p.CommandLine.Contains('" + deployment.ssh_target() + "')) { Write-Output 'owned' }")
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',
                    base64.b64encode(script.encode('utf-16-le')).decode()],capture_output=True,timeout=8,
                    check=True,creationflags=subprocess.CREATE_NO_WINDOW)
                if result.stdout.decode().strip()=='owned':return
            raise RuntimeError('The validation API tunnel port belongs to another process')
    except OSError:pass
    log=open(ROOT/'local/remote-api-tunnel.log','ab')
    child=subprocess.Popen(['ssh','-N','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes',
        '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',
        '-L','127.0.0.1:18669:127.0.0.1:18668',deployment.ssh_target()],
        stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    log.close();time.sleep(.5)
    if child.poll() is not None:raise RuntimeError('API tunnel could not start')
    (ROOT/'local/remote-api-tunnel.json').write_text(json.dumps({'pid':child.pid,'port':18669}))

if __name__=='__main__':
    provision();tunnel()
