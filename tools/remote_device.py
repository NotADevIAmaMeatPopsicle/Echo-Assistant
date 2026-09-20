"""Operate the already provisioned Echo host without re-importing laptop data."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import deployment
import httpx
from backend.remote_host import _powershell,manage
from tools.start_remote_api import connection,tunnel


def compose(service,*arguments):
    files=[ROOT/'deploy/remote/compose.yaml'] if service=='agent' else [ROOT/'deploy/host/compose.yaml',ROOT/'deploy/host/device.yaml']
    environment={**__import__('os').environ,'ECHO_BIND_ADDRESS':deployment.device_host()}
    private_calling=deployment.calling_private_origin() if service=='api' else ''
    if private_calling:
        files.append(ROOT/'deploy/host/calling.yaml')
        environment['ECHO_CALLING_PRIVATE_ORIGIN']=private_calling
    command=['docker','--context',deployment.docker_context(),'compose']
    for path in files:command+=['-f',str(path)]
    services=[service,'calling'] if private_calling and arguments and arguments[0]=='stop' else [service]
    subprocess.run([*command,*arguments,*services],check=True,env=environment)


def discovery(enabled):
    config=json.dumps({'enabled':enabled,'host':deployment.device_host(),'port':18899})
    script=r'''$root=(Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo'); $data=[Console]::In.ReadToEnd(); [IO.File]::WriteAllText((Join-Path $root 'discovery.json'),$data); if (($data|ConvertFrom-Json).enabled) { $task=Get-ScheduledTask -TaskName 'Echo Spotify Discovery'; if ($task.State -ne 'Running') { Start-ScheduledTask -TaskName 'Echo Spotify Discovery' } }; Write-Output '{"configured":true}' '''
    return json.loads(_powershell(script,config.encode()))


def client():
    tunnel();value=connection()
    return httpx.Client(base_url=value['url'],headers={'Authorization':'Bearer '+value['token']},trust_env=False,timeout=60)


def wait_ready(timeout=45,board=False):
    deadline=time.monotonic()+timeout
    with client() as api:
        while time.monotonic()<deadline:
            try:
                response=api.get('/health',timeout=3);response.raise_for_status();health=response.json()
                if health.get('deployment_mode')=='device' and (not board or health.get('device_transport')=='wifi_connected'):
                    return health
            except (httpx.HTTPError,ValueError):pass
            time.sleep(.5)
    raise RuntimeError('The Remote host device host did not become ready in time')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','stop','status'])
    parser.add_argument('--play-music',action='store_true')
    args=parser.parse_args()
    if json.loads((ROOT/'local/host-target.json').read_text()).get('mode')!='remote':
        raise RuntimeError('Complete the host transfer before using this launcher')
    if args.action=='start':
        compose('agent','up','-d','--no-build');compose('api','up','-d','--no-build')
        manage('Recover');discovery(True)
        health=wait_ready()
        if args.play_music:
            wait_ready(board=True)
            with client() as api:
                response=api.post('/v1/music/control',json={'action':'play'});response.raise_for_status()
    elif args.action=='stop':
        discovery(False);compose('api','stop');compose('agent','stop')
        print('Echo services stopped on Remote host.');return
    else:
        with client() as api:
            response=api.get('/health');response.raise_for_status();health=response.json()
    print(json.dumps({k:health.get(k) for k in ('version','status','device_transport','speech_to_text','text_to_speech','spotify_connect')}))


if __name__=='__main__':main()
