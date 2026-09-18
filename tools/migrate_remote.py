"""One-time coordinated move of Echo's host and paired board to Remote host.

The source remains as a rollback copy. Secrets travel only over private stdin,
and the destination validates/re-encrypts its import before activating it.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import deployment
import httpx
from serial.tools import list_ports
from backend.settings import SettingsStore,WindowsProtector
from backend.memory import MemoryStore
from backend.home import HomeConfig
from backend.home_access import HomeAccessStore
from backend.core import Assistant
from backend.lifecycle import request_stop
from backend.transport import MAC,load_wifi
from backend import __version__
from backend.remote_host import install,manage
from tools import remote_agent
from tools.remote_device import compose,discovery,client,wait_ready
from tools.start_remote_api import connection

TARGET=ROOT/'local/host-target.json'
BACKUP=ROOT/'local/wifi-before-remote.json'
PYTHON=ROOT/'.venv/Scripts/python.exe'
WIFI_SECRETS=ROOT.parent/'Round-AMOLED-Spotify-Test/esphome/secrets.yaml'


def write_target(mode,identifier):
    temporary=TARGET.with_suffix('.tmp')
    temporary.write_text(json.dumps({'mode':mode,'migration_id':identifier}))
    temporary.replace(TARGET)


def stop_local(name):
    request_stop(ROOT,name)
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        # The OS lock remains authoritative even after a stale record or crash.
        if not request_stop(ROOT,name):return
        time.sleep(.2)
    raise RuntimeError('Local '+name+' did not release ownership')


def pair(host,port):
    command=[str(PYTHON),str(ROOT/'tools/pair_wifi.py'),'--host',host,
        '--port',port,'--wifi-secrets',str(WIFI_SECRETS)]
    subprocess.run(command,cwd=ROOT,check=True,timeout=35,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def source_digest(root):
    settings,keys,_=SettingsStore(root).snapshot()
    timer_path=root/'local/timers.json'
    Assistant(storage=timer_path).timer_states()
    value={'settings':settings.model_dump(),'keys':keys,'memory':MemoryStore(root).snapshot(),
           'home_access':HomeAccessStore(root).snapshot()['policy'],
           'timers':json.loads(timer_path.read_text()) if timer_path.exists() else []}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def preflight(resume=False,migrating=False):
    if TARGET.exists() and not migrating:raise RuntimeError('A host target already exists; inspect its migration status first')
    ports=[p.device for p in list_ports.comports() if (p.vid,p.pid)==(0x303A,0x1001) and (p.serial_number or '').lower()==MAC]
    if len(ports)!=1:raise RuntimeError('Connect the verified round board over USB before transferring')
    import yaml
    wifi_fields=yaml.safe_load(WIFI_SECRETS.read_text())
    if not all(isinstance(wifi_fields.get(k),str) for k in ('wifi_ssid','wifi_password')):
        raise RuntimeError('The existing Wi-Fi secret file is incomplete')
    wifi=load_wifi(ROOT)
    if not wifi:raise RuntimeError('The source board must already be paired')
    with client() as api:
        health=api.get('/health');health.raise_for_status()
        if health.json().get('version')!=__version__ or health.json().get('deployment_mode')!=('device' if resume else 'validation'):
            raise RuntimeError('Validate the matching destination image before transferring')
    if resume:
        receipt=json.loads((ROOT/'local/remote-cutover-receipt.json').read_text())
        if receipt.get('complete') or receipt.get('rollback')!='restored':
            raise RuntimeError('Only a fully restored transfer can resume automatically')
        saved=json.loads(WindowsProtector().decrypt(base64.b64decode(json.loads(BACKUP.read_text())['protected'])))
        if saved!=wifi:raise RuntimeError('Source pairing changed since the rollback')
        verify="""import hashlib,json,sys
from pathlib import Path
from backend.settings import SettingsStore
from backend.memory import MemoryStore
from backend.home_access import HomeAccessStore
root=Path('/opt/echo');expected=json.load(sys.stdin)
settings,keys,_=SettingsStore(root).snapshot()
path=root/'local/timers.json'
value={'settings':settings.model_dump(),'keys':keys,'memory':MemoryStore(root).snapshot(),
'home_access':HomeAccessStore(root).snapshot()['policy'],'timers':json.loads(path.read_text()) if path.exists() else []}
actual=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
assert actual==expected['digest'], 'Source and destination data changed; reconcile before resuming'
assert json.loads((root/'local/host-migration.json').read_text())['id']==expected['id'], 'Migration identity changed'
"""
        subprocess.run(['docker','--context',deployment.docker_context(),'exec','-i','echo-api','python','-c',verify],
            input=json.dumps({'id':receipt['migration_id'],'digest':source_digest(ROOT)}).encode(),check=True)
    return ports[0],wifi


def transfer(port,wifi,resume=False):
    identifier=json.loads((ROOT/'local/remote-cutover-receipt.json').read_text())['migration_id'] if resume else uuid.uuid4().hex
    stage='source backup';paired=False
    sealed=WindowsProtector().encrypt(json.dumps(wifi).encode())
    if not resume:
        if BACKUP.exists():raise RuntimeError('A prior pairing backup exists; inspect it before another transfer')
        BACKUP.write_text(json.dumps({'protected':base64.b64encode(sealed).decode()}))
    write_target('migrating',identifier)
    try:
        stage='release laptop voice';stop_local('voice')
        stage='release laptop API';stop_local('api')
        if resume:preflight(resume=True,migrating=True)
        settings,keys,_=SettingsStore(ROOT).snapshot()
        if settings.agent_runtime!='hermes':raise RuntimeError('Select the approved Hermes runtime before transferring')
        memory=MemoryStore(ROOT).snapshot()
        timer_path=ROOT/'local/timers.json'
        Assistant(storage=timer_path).timer_states()
        timers=json.loads(timer_path.read_text()) if timer_path.exists() else []
        policy=HomeAccessStore(ROOT).snapshot()['policy']
        agent=remote_agent.connection();agent['url']='http://agent:8642'
        bundle={'id':identifier,'settings':settings.model_dump(),'keys':keys,'memory':memory,
            'timers':timers,'home_access':policy,'agent':agent}
        spotify_path=ROOT/'local/spotify/credentials.json'
        if spotify_path.exists():bundle['spotify']=json.loads(spotify_path.read_text())
        value=connection();home=HomeConfig.load(ROOT)
        payload={'settings':settings.model_dump(),'provider_key':keys['azure'],
            'api_token':value['token'],'home_tools_token':value['home_tools_token'],'home_access':policy,
            'wifi':{**wifi,'host':deployment.device_host()},'migration':bundle}
        music_path=ROOT/'local/music.json'
        if music_path.exists():payload['music']={**json.loads(music_path.read_text()),'interface':deployment.device_host()}
        if home.enabled:payload['home']={'enabled':True,'base_url':home.base_url,'token':home.token,'entities':home.entities}
        stage='provision destination'
        install(ROOT);manage('SaveApi',payload)
        fingerprint=remote_agent.prepare(home_api={'url':'http://api:8768','token':value['home_tools_token']})
        compose('agent','up','-d','--no-build','--force-recreate');compose('api','up','-d','--no-build')
        manage('Recover');remote_agent.activate(fingerprint);wait_ready()
        stage='verify destination assistant'
        with client() as api:
            response=api.post('/v1/text',json={'text':'Reply only: Echo is on Remote host.'});response.raise_for_status()
            if response.json().get('status')!='complete' or 'echo is on remote' not in response.json().get('text','').lower():
                raise RuntimeError('Destination assistant did not confirm its live reply')
        stage='pair physical board';paired=True;pair(deployment.device_host(),port)
        stage='verify physical connection';wait_ready(timeout=45,board=True)
        with client() as api:
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                response=api.get('/v1/voice');response.raise_for_status();voice=response.json()
                if voice.get('device',{}).get('volume') is not None and voice.get('speech_worker')=='ready':break
                time.sleep(.5)
            else:raise RuntimeError('Physical speech readiness was not confirmed')
            if int(voice.get('device',{}).get('volume',99))>3:raise RuntimeError('Device volume is above the approved test level')
        discovery(True)
        receipt={'complete':True,'migration_id':identifier,'version':__version__,'device_transport':'wifi',
            'volume':voice['device']['volume'],'source_preserved':True,'memory_count':len(memory),
            'timer_count':len(timers),'provider_key_count':len(keys),'audio_played':False}
        (ROOT/'local/remote-cutover-receipt.json').write_text(json.dumps(receipt,indent=2))
        write_target('remote',identifier)
        print(json.dumps(receipt))
    except Exception as error:
        rollback='restored'
        try:
            compose('api','stop')
            if paired:pair(wifi['host'],port)
            (ROOT/'local/wifi.json').write_text(json.dumps(wifi,indent=2))
            fingerprint=remote_agent.prepare()
            compose('agent','up','-d','--no-build','--force-recreate');remote_agent.activate(fingerprint)
            TARGET.unlink(missing_ok=True)
            subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(ROOT/'tools/run.ps1'),'start'],
                cwd=ROOT,check=True,timeout=45,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except Exception:rollback='needs_attention'
        receipt={'complete':False,'migration_id':identifier,'stage':stage,'error_type':type(error).__name__,'rollback':rollback}
        (ROOT/'local/remote-cutover-receipt.json').write_text(json.dumps(receipt,indent=2))
        raise SystemExit(json.dumps(receipt)) from None


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Resume a fully rolled-back transfer after verifying unchanged source and destination data')
    args=parser.parse_args()
    port,wifi=preflight(args.resume)
    if args.execute:transfer(port,wifi,args.resume)
    else:print(json.dumps({'ready':True,'port':port,'destination':deployment.device_host(),'changes_made':False}))
