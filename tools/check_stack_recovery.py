"""Rehearse Windows DPAPI/task recovery of Echo and Hermes with synthetic data.

Uses existing images, network-disabled containers and a temporary current-user
Scheduled Task. No production containers/volumes, ports, credentials, model
requests, microphone or sound. Run on Windows with its Docker context configured.
"""
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.settings import WindowsProtector
from tools.check_host_recovery import PROBE, LABEL
from tools.backup_remote import COLLECT, PHOTO
from tools.recovery_archive import FILES,LIMITS,write_archive,read_archive,read_photo,restored_bootstrap
from tools.recovery_restore import SCRIPT
from tools.recovery_passphrase import PassphraseProtector

AGENT_PROBE=r'''
import json,sys,urllib.request,urllib.error
from pathlib import Path
v=json.load(sys.stdin)
with urllib.request.urlopen('http://127.0.0.1:8642/health',timeout=3) as response:
    assert json.load(response)['status']=='ok'
assert Path('/opt/data/echo-configuration').read_text()==v['configuration']
assert Path('/opt/data/SOUL.md').read_text()==v['personality']
assert json.loads(Path('/opt/data/echo-access.json').read_text())==v['home_access']
assert not Path('/dev/snd').exists()
for token,expected in [(None,(401,403)),(v['secrets']['API_SERVER_KEY'],(404,))]:
    headers={'Authorization':'Bearer '+token} if token else {}
    request=urllib.request.Request('http://127.0.0.1:8642/v1/runs/run_'+'a'*32,headers=headers)
    try:urllib.request.urlopen(request,timeout=3)
    except urllib.error.HTTPError as error:assert error.code in expected
    else:raise AssertionError('Unexpected run lookup result')
print('verified')
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',required=True)
    parser.add_argument('--api-image',required=True)
    parser.add_argument('--agent-image',required=True)
    parser.add_argument('--portable',action='store_true',help='Use a generated synthetic passphrase and also unlock the archive in Linux')
    args=parser.parse_args()
    if os.name!='nt':raise SystemExit('This rehearsal requires Windows DPAPI and Scheduled Tasks.')
    identifier=secrets.token_hex(6);prefix='echo-recovery-check-'+identifier
    # Packaged desktop apps can virtualize AppData for child processes, while
    # Windows Task Scheduler sees the physical host path. Use the ignored workspace.
    parent=ROOT/'output/EchoRecoveryChecks'
    parent.parent.mkdir(exist_ok=True)
    if parent.is_symlink() or parent.is_junction():raise RuntimeError('Linked rehearsal parent')
    parent.mkdir(exist_ok=True);directory=parent/identifier;directory.mkdir()
    (directory/'owner').write_text(identifier)
    helper=directory/'recover.ps1';shutil.copy2(ROOT/'deploy/remote/recover.ps1',helper)
    containers=[];volumes=[];task='Echo Recovery Rehearsal '+identifier;task_created=False
    protector=WindowsProtector();powershell_exe=shutil.which('powershell.exe')
    if not powershell_exe:raise RuntimeError('Windows PowerShell is unavailable')

    def docker(*arguments,data=None,timeout=60):
        result=subprocess.run(['docker','--context',args.context,*arguments],input=data,capture_output=True,timeout=timeout)
        if result.returncode:raise RuntimeError('Isolated Docker operation failed: '+arguments[0])
        return result.stdout

    def powershell(script,data=b'',timeout=45):
        encoded=base64.b64encode(script.encode('utf-16-le')).decode()
        result=subprocess.run([powershell_exe,'-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                              input=data,capture_output=True,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError('Isolated Windows operation failed')
        return result.stdout.decode('utf-8-sig').strip()

    def quote(value):return "'"+str(value).replace("'","''")+"'"

    def recover(mode='Recover',payload=None):
        result=subprocess.run([powershell_exe,'-NoProfile','-NonInteractive','-File',str(helper),
            '-RehearsalId',identifier,'-RehearsalDirectory',str(directory),'-DockerContext',args.context,'-Mode',mode],
            input=b'' if payload is None else json.dumps(payload).encode(),capture_output=True,timeout=100,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError('Isolated recovery helper failed: '+result.stdout.decode(errors='replace')[-500:])
        return json.loads(result.stdout.decode('utf-8-sig'))

    def owned(kind,name):
        value=json.loads(docker(kind,'inspect',name))[0]
        labels=value.get('Labels',{}) if kind=='volume' else value['Config'].get('Labels',{})
        if labels.get(LABEL)!=identifier:raise RuntimeError('Refusing an unowned recovery resource')

    def remove_containers():
        for name in list(reversed(containers)):
            owned('container',name);docker('rm','--force',name);containers.remove(name)

    def create_pair(suffix,api_image,agent_image):
        volume=prefix+'-'+suffix
        docker('volume','create','--label',LABEL+'='+identifier,volume);volumes.append(volume)
        for role,image in [('api',api_image),('agent',agent_image)]:
            name=prefix+'-'+role
            common=['create','--name',name,'--label',LABEL+'='+identifier,'--network','none','--log-driver','none',
                    '--cpus','1','--pids-limit','192','--memory','1536m','--memory-swap','1536m',
                    '--tmpfs','/tmp:mode=1777,size=128m']
            if role=='api':
                common+=['--read-only','--tmpfs','/run/echo:uid=10000,gid=10000,mode=0700,size=16m',
                         '--tmpfs','/models:uid=10000,gid=10000,mode=0700,size=1m',
                         '--mount','type=volume,source='+volume+',target=/opt/echo/local',
                         '-e','ECHO_DEPLOYMENT_MODE=validation','-e','ECHO_VOICE_ENABLED=0']
            else:
                common+=['--tmpfs','/opt/data:uid=10000,gid=10000,mode=0700,size=512m',
                         '-e','HOME=/opt/data','-e','HERMES_HOME=/opt/data','-e','PYTHONDONTWRITEBYTECODE=1']
            docker(*common,image);containers.append(name);docker('start',name)

    def wait_ready():
        deadline=time.monotonic()+95
        while time.monotonic()<deadline:
            try:
                state=recover()
                if state.get('state')=='ready' and state.get('api')=='ready':return
                if state.get('state')=='recovery_failed':raise RuntimeError('Recovery helper rejected the fixture')
            except subprocess.TimeoutExpired:raise
            time.sleep(1)
        raise RuntimeError('Isolated stack did not become ready')

    def probe(phase,proof=None):
        result=json.loads(docker('exec','-i',prefix+'-api','python','-c',PROBE,
            data=json.dumps({'phase':phase,'proof':proof}).encode(),timeout=50))
        docker('exec','-i',prefix+'-agent','/opt/hermes/.venv/bin/python','-c',AGENT_PROBE,
               data=json.dumps(bootstrap['agent']).encode())
        return result

    policy={'default_access':'hidden','devices':{'light.synthetic':{'access':'read','room':'Synthetic room'}}}
    bootstrap={'api':{'storage_key':base64.b64encode(os.urandom(32)).decode(),
        'api_token':secrets.token_urlsafe(40),'home_tools_token':secrets.token_urlsafe(40),
        'settings':{'provider':'local','model':'synthetic','agent_runtime':'direct'},
        'provider_key':'synthetic-no-network','home_access':policy},
        'agent':{'configuration':'a'*64,'personality':'Synthetic recovery personality.', 'home_access':policy,
            'secrets':{'OPENAI_API_KEY':'synthetic-no-network','API_SERVER_KEY':secrets.token_urlsafe(40)},
            'config':{'model':{'provider':'custom','default':'synthetic','base_url':'http://127.0.0.1:9/v1','api_mode':'chat_completions'},
                'agent':{'max_turns':1},'platform_toolsets':{'api_server':[]},
                'memory':{'memory_enabled':False,'user_profile_enabled':False,'nudge_interval':0},
                'skills':{'creation_nudge_interval':0},'auxiliary':{'background_review':{'enabled':False}},
                'updates':{'check':False},'telemetry':{'shared_metrics':{'enabled':False,'send':False}},
                'terminal':{'cwd':'/opt/data/workspace'}}}}
    try:
        api_image=json.loads(docker('image','inspect',args.api_image))[0]['Id']
        agent_image=json.loads(docker('image','inspect',args.agent_image))[0]['Id']
        create_pair('source',api_image,agent_image)
        assert recover('RestoreBootstrap',bootstrap)['state']=='bootstrap_restored'
        wait_ready();proof=probe('seed')
        print('Fresh isolated Windows recovery: API, Hermes authentication and saved fixtures ready.',flush=True)
        action=f'-NoProfile -NonInteractive -WindowStyle Hidden -File "{helper}" -RehearsalId {identifier} -RehearsalDirectory "{directory}" -DockerContext {args.context} -Mode Recover'
        powershell(f'''
$ErrorActionPreference='Stop'
$name={quote(task)}
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {{ throw 'Task exists' }}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$action=New-ScheduledTaskAction -Execute {quote(powershell_exe)} -Argument {quote(action)} -WorkingDirectory {quote(directory)}
$principal=New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$null=Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings
''');task_created=True
        # Empty tmpfs really loses both runtimes' bootstrap material on restart.
        docker('restart','--time','10',*containers,timeout=50)
        powershell(f"Start-ScheduledTask -TaskName {quote(task)}")
        # First wait observes task execution; it does not invoke recovery manually.
        deadline=time.monotonic()+100;task_ok=False
        while time.monotonic()<deadline:
            state=json.loads(powershell(f"$t=Get-ScheduledTask -TaskName {quote(task)}; $i=Get-ScheduledTaskInfo -TaskName {quote(task)}; @{{state=[string]$t.State;result=$i.LastTaskResult;ran=($i.LastRunTime -gt (Get-Date).AddMinutes(-3))}}|ConvertTo-Json -Compress"))
            if state['ran'] and state['state']!='Running':
                if state['result']!=0:
                    report=json.loads((directory/'recovery-status.json').read_text()) if (directory/'recovery-status.json').exists() else {}
                    raise RuntimeError('Rehearsal Scheduled Task failed: '+json.dumps({'result':state['result'],'recovery':report}))
                task_ok=True;break
            time.sleep(1)
        if not task_ok:raise RuntimeError('Rehearsal Scheduled Task did not finish')
        # The task provisions; startup can finish afterward without another invocation.
        deadline=time.monotonic()+75
        while True:
            try:probe('verify',proof);break
            except RuntimeError:
                if time.monotonic()>deadline:raise
                time.sleep(1)
        print('Actual current-user Scheduled Task restored both stopped-and-restarted runtimes.',flush=True)
        saved=json.loads(docker('exec','-i',prefix+'-api','python','-c',COLLECT,
            data=json.dumps({'files':FILES,'limits':LIMITS}).encode()))
        payload={'kind':'echo-remote','version':2,'created_at':time.time(),**saved,'bootstrap':bootstrap}
        archive=directory/'synthetic.echo-backup'
        phrase=secrets.token_urlsafe(32) if args.portable else None
        archive_protector=PassphraseProtector(phrase) if args.portable else protector
        write_archive(archive,payload,archive_protector,lambda name:docker('exec','-i',prefix+'-api','python','-c',PHOTO,data=json.dumps(name).encode()))
        restored=read_archive(archive,archive_protector);bootstrap=restored_bootstrap(restored)
        if args.portable:
            # Transfer only an encrypted archive plus synthetic passphrase over stdin.
            # Execute the current decoder source in memory, without modifying the image.
            code=r'''
import base64,hashlib,json,sys,tempfile,types
from pathlib import Path
data=json.load(sys.stdin)
crypto=types.ModuleType('recovery_passphrase');exec(compile(data['crypto'],'recovery_passphrase.py','exec'),crypto.__dict__)
archive_module=types.ModuleType('recovery_archive');exec(compile(data['archive_source'],'recovery_archive.py','exec'),archive_module.__dict__)
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/'synthetic.echo-backup';path.write_bytes(base64.b64decode(data['archive']))
    payload=archive_module.read_archive(path,crypto.PassphraseProtector(data['phrase']))
    assert hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()==data['digest']
print('Portable Windows archive verified in Linux without Windows keys.')
'''
            import hashlib
            transfer={'crypto':(ROOT/'tools/recovery_passphrase.py').read_text(),
                'archive_source':(ROOT/'tools/recovery_archive.py').read_text(),
                'archive':base64.b64encode(archive.read_bytes()).decode(),'phrase':phrase,
                'digest':hashlib.sha256(json.dumps(restored,sort_keys=True).encode()).hexdigest()}
            docker('exec','-i',prefix+'-api','python','-c',code,data=json.dumps(transfer).encode())
            print('Portable Windows archive verified in Linux without Windows keys.',flush=True)
        # A stale host policy must be replaced along with both bootstrap envelopes.
        stale={'default_access':'read','devices':{}}
        (directory/'home-access.dpapi').write_bytes(protector.encrypt(json.dumps(stale).encode()))
        remove_containers();create_pair('restored',api_image,agent_image)
        header={'names':FILES,'limits':LIMITS,'files':restored['files'],'photos':restored['photos'],'storage_key':bootstrap['api']['storage_key']}
        stream=json.dumps(header).encode()+b'\n'
        for name,item in restored['photos'].items():
            stream+=json.dumps({'name':name,'data':base64.b64encode(read_photo(archive,name,item)).decode()}).encode()+b'\n'
        docker('exec','-i',prefix+'-api','python','-c',SCRIPT,data=stream)
        assert recover('RestoreBootstrap',bootstrap)['state']=='bootstrap_restored'
        assert json.loads(protector.decrypt((directory/'home-access.dpapi').read_bytes()))==policy
        wait_ready();probe('verify',proof)
        print('PASS: '+('Portable' if args.portable else 'DPAPI')+' archive restored into fresh API/Hermes containers and a fresh data volume; stale host policy replaced. No network, provider calls or audio.',flush=True)
    finally:
        if task_created:
            powershell(f"$t=Get-ScheduledTask -TaskName {quote(task)}; if (-not $t.Actions.Arguments.Contains({quote(str(helper))})) {{ throw 'Task identity changed' }}; Stop-ScheduledTask -TaskName {quote(task)}; Unregister-ScheduledTask -TaskName {quote(task)} -Confirm:$false")
        remove_containers()
        for name in reversed(volumes):owned('volume',name);docker('volume','rm',name)
        # Only delete the verified absolute directory created by this invocation.
        if directory.resolve()!=parent.resolve()/identifier or directory.is_symlink() or directory.is_junction() or (directory/'owner').read_text()!=identifier:
            raise RuntimeError('Refusing unowned rehearsal cleanup')
        shutil.rmtree(directory)


if __name__=='__main__':main()
