"""Create, inspect, or explicitly restore a private Echo recovery archive.

The archive is encrypted to the current laptop's Windows user using DPAPI.
No recordings, transcripts, browser sessions, task results or model weights enter it.
"""
import argparse
import base64
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import deployment
from backend.settings import WindowsProtector
from backend.remote_host import _powershell, manage
from tools.recovery_archive import FILES,LIMITS,read_archive as load_archive,read_photo,write_archive

# Kept as self-contained scripts so a recovery client can work with older images.
COLLECT="""import base64,hashlib,json,re,sys; from pathlib import Path
options=json.load(sys.stdin); root=Path('/opt/echo/local'); result={'files':{},'photos':{}}
for name in options['files']:
    p=root/name
    if p.is_symlink():raise ValueError('Linked recovery file')
    if not p.exists():continue
    if not p.is_file() or p.stat().st_size>options['limits'].get(name,500000):raise ValueError('Unexpected recovery file')
    raw=p.read_bytes();json.loads(raw)
    result['files'][name]={'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}
album=root/'display-photos'
if album.is_symlink():raise ValueError('Linked album')
if album.exists():
    from backend.settings import default_protector
    protector=default_protector()
    for p in sorted(album.glob('*.photo')):
        if p.is_symlink() or not p.is_file() or not re.fullmatch('[a-f0-9]{32}\\.photo',p.name) or p.stat().st_size>6000000:
            raise ValueError('Unexpected album file')
        raw=p.read_bytes()
        if not protector.decrypt(raw).startswith(bytes((255,216,255))):raise ValueError('Invalid encrypted album photo')
        result['photos']['display-photos/'+p.name]={'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    if len(result['photos'])>60:raise ValueError('Album is too large')
print(json.dumps(result))
"""

PHOTO="""import json,re,sys;from pathlib import Path
name=json.load(sys.stdin)
if not isinstance(name,str) or not re.fullmatch('display-photos/[a-f0-9]{32}\\.photo',name):raise ValueError('Invalid photo name')
p=Path('/opt/echo/local')/name
if p.parent.is_symlink() or p.is_symlink() or not p.is_file() or p.stat().st_size>6000000:raise ValueError('Invalid photo')
sys.stdout.buffer.write(p.read_bytes())
"""

def docker(*args, data=None):
    result=subprocess.run(['docker','--context',deployment.docker_context(),*args],input=data,
                          capture_output=True,check=True,timeout=90)
    return result.stdout

def read_archive(path):
    return load_archive(path,WindowsProtector())


def collect():
    return json.loads(docker('exec','-i','echo-api','python','-c',COLLECT,
                            data=json.dumps({'files':FILES,'limits':LIMITS}).encode()))

def create():
    # Individual app files are atomically replaced. A second read detects edits
    # during collection, without stopping the current speaker or persisting plaintext.
    saved=collect()
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
    payload={'kind':'echo-remote','version':2,'created_at':time.time(),**saved,'bootstrap':bootstrap}
    destination=ROOT/'backups'/(time.strftime('echo-host-%Y%m%d-%H%M%S-')+secrets.token_hex(4)+'.echo-backup')
    destination.parent.mkdir(exist_ok=True)
    write_archive(destination,payload,WindowsProtector(),
                  lambda name:docker('exec','-i','echo-api','python','-c',PHOTO,data=json.dumps(name).encode()))
    try:
        if saved!=collect():raise ValueError('Saved data changed during backup; try again')
        read_archive(destination)
    except Exception:
        destination.unlink();raise
    return destination

def restore(path):
    payload=read_archive(path)
    # Preserve current data before the explicit replacement; never import the old
    # migration snapshot over newer routines, facts or speaker selection.
    previous=create()
    image=docker('inspect','echo-api','--format','{{.Image}}').decode().strip()
    docker('stop','--time','20','echo-api','echo-agent')
    from tools.recovery_restore import SCRIPT
    command=['docker','--context',deployment.docker_context(),'run','--rm','-i','--network','none',
             '--volumes-from','echo-api','--entrypoint','python',image,'-c',SCRIPT]
    with subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as process:
        try:
            data={'names':FILES,'limits':LIMITS,'files':payload['files'],'photos':payload.get('photos',{}),
                  'storage_key':payload['bootstrap']['api']['storage_key']}
            process.stdin.write(json.dumps(data).encode()+b'\n')
            for name,item in payload.get('photos',{}).items():
                raw=read_photo(path,name,item)
                process.stdin.write(json.dumps({'name':name,'data':base64.b64encode(raw).decode()}).encode()+b'\n')
            process.stdin.close()
            if process.wait(timeout=90):raise RuntimeError('Recovery staging or application failed')
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
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
        if args.action=='inspect':print(json.dumps({'version':payload['version'],'created_at':payload['created_at'],'files':list(payload['files']),'photos':len(payload.get('photos',{})),'verified':True}));return
        previous=restore(args.archive)
        print('Echo recovery applied. Previous data preserved at '+str(previous))
    except Exception:
        # Native exception output may contain private bootstrap material.
        raise SystemExit('Echo recovery could not complete. Existing archives were preserved. Check Echo host availability and the Windows account used to create the archive.') from None

if __name__=='__main__':main()
