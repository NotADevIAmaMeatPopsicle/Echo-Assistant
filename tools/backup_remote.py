"""Create, inspect, or explicitly restore a private Echo recovery archive.

The archive is encrypted to the current laptop's Windows user using DPAPI.
No recordings, transcripts, browser sessions, task results or model weights enter it.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import deployment
from backend.settings import WindowsProtector
from backend.remote_host import _powershell, manage

FILES=('echo-settings.json','echo-memory.json','echo-routines.json','home-access.json',
       'speaker-selection.json','timers.json','spotify-credentials.json','remote-agent.json',
       'host-migration.json')

def docker(*args, data=None):
    result=subprocess.run(['docker','--context',deployment.docker_context(),*args],input=data,
                          capture_output=True,check=True,timeout=90)
    return result.stdout

def read_archive(path):
    if path.stat().st_size>4_000_000:raise ValueError('Recovery archive is too large')
    payload=json.loads(WindowsProtector().decrypt(path.read_bytes()))
    if payload.get('kind')!='echo-remote' or payload.get('version')!=1:raise ValueError('Unsupported archive')
    if set(payload['files'])-set(FILES):raise ValueError('Unexpected recovery file')
    for name,item in payload['files'].items():
        raw=base64.b64decode(item['data'],validate=True)
        if len(raw)>500_000 or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Damaged recovery file')
        json.loads(raw)
    for name in ('api','agent'):
        if not isinstance(payload['bootstrap'][name],dict):raise ValueError('Invalid recovery bootstrap')
    if len(base64.b64decode(payload['bootstrap']['api']['storage_key'],validate=True))!=32:raise ValueError('Invalid storage key')
    return payload

def create():
    # Individual app files are atomically replaced. A second read detects edits
    # during collection, without stopping the current speaker or persisting plaintext.
    code="""import base64,hashlib,json,sys; from pathlib import Path
names=json.load(sys.stdin); root=Path('/opt/echo/local')
def read():
    result={}
    for name in names:
        p=root/name
        if not p.exists(): continue
        if p.is_symlink() or p.stat().st_size>500000: raise ValueError('Unexpected recovery file')
        raw=p.read_bytes(); json.loads(raw)
        result[name]={'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}
    return result
files=read()
if files!=read():raise ValueError('Saved data changed during backup; try again')
print(json.dumps(files))
"""
    files=json.loads(docker('exec','-i','echo-api','python','-c',code,data=json.dumps(FILES).encode()))
    script=r'''
$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Security
$root=(Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo')
$result=@{}
foreach($name in @('api','agent')) {
    $path=Join-Path $root ($name+'-bootstrap.dpapi')
    $raw=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($path),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    $result[$name]=[Text.Encoding]::UTF8.GetString($raw)|ConvertFrom-Json
    [Array]::Clear($raw,0,$raw.Length)
}
$result.api.PSObject.Properties.Remove('migration')
Write-Output ($result|ConvertTo-Json -Depth 40 -Compress)
'''
    bootstrap=json.loads(_powershell(script))
    payload={'kind':'echo-remote','version':1,'created_at':time.time(),'files':files,'bootstrap':bootstrap}
    destination=ROOT/'backups'/time.strftime('echo-host-%Y%m%d-%H%M%S.echo-backup')
    destination.parent.mkdir(exist_ok=True)
    with destination.open('xb') as stream:stream.write(WindowsProtector().encrypt(json.dumps(payload).encode()))
    read_archive(destination)
    return destination

def restore(path):
    payload=read_archive(path)
    # Preserve current data before the explicit replacement; never import the old
    # migration snapshot over newer routines, facts or speaker selection.
    previous=create()
    docker('stop','--time','20','echo-api','echo-agent')
    code="""import base64,json,sys; from pathlib import Path
data=json.load(sys.stdin); root=Path('/opt/echo/local'); root.mkdir(exist_ok=True)
for name in data['names']:
    p=root/name
    if p.is_symlink():raise ValueError('Refusing linked recovery target')
for name in data['names']:
    p=root/name
    if name in data['files']:
        tmp=p.with_suffix('.restore-tmp');tmp.write_bytes(base64.b64decode(data['files'][name]['data'],validate=True));tmp.replace(p)
    elif p.exists():p.unlink()
"""
    docker('run','--rm','-i','--network','none','--volumes-from','echo-api','--entrypoint','python',
           'echo-host:validation-0.1','-c',code,data=json.dumps({'names':FILES,'files':payload['files']}).encode())
    script=r'''
$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Security
$root=(Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo');$data=[Console]::In.ReadToEnd()|ConvertFrom-Json
foreach($name in @('api','agent')) {
    $path=Join-Path $root ($name+'-bootstrap.dpapi')
    $raw=[Text.Encoding]::UTF8.GetBytes(($data.$name|ConvertTo-Json -Depth 40 -Compress))
    $sealed=[Security.Cryptography.ProtectedData]::Protect($raw,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    [IO.File]::WriteAllBytes(($path+'.restore-tmp'),$sealed)
    Move-Item -LiteralPath ($path+'.restore-tmp') -Destination $path -Force
    [Array]::Clear($raw,0,$raw.Length)
}
Write-Output '{"restored":true}'
'''
    _powershell(script,json.dumps(payload['bootstrap']).encode())
    docker('start','echo-agent','echo-api');manage('Recover')
    return previous

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['create','inspect','restore'])
    parser.add_argument('archive',nargs='?',type=Path)
    args=parser.parse_args()
    try:
        if args.action=='create':print(create());return
        if not args.archive:raise ValueError('Choose an archive file')
        payload=read_archive(args.archive)
        if args.action=='inspect':print(json.dumps({'created_at':payload['created_at'],'files':list(payload['files']),'verified':True}));return
        previous=restore(args.archive)
        print('Echo recovery applied. Previous data preserved at '+str(previous))
    except Exception:
        # Native exception output may contain private bootstrap material.
        raise SystemExit('Echo recovery could not complete. Existing archives were preserved. Check Echo host availability and the Windows account used to create the archive.') from None

if __name__=='__main__':main()
