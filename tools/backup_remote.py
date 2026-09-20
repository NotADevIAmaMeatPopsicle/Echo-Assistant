"""Create, inspect, or explicitly restore a private Echo recovery archive.

Archives use Windows DPAPI by default, or a portable recovery passphrase.
No recordings, transcripts, browser sessions, task results or model weights enter it.
"""
import argparse
import base64
import getpass
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
from backend.remote_host import _powershell, manage, install
from tools.recovery_archive import FILES,LIMITS,read_archive as load_archive,read_photo,write_archive,restored_bootstrap,protection_kind
from tools.recovery_passphrase import PassphraseProtector,PassphraseError

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

def read_archive(path,protector=None):
    return load_archive(path,protector or WindowsProtector())


def collect():
    return json.loads(docker('exec','-i','echo-api','python','-c',COLLECT,
                            data=json.dumps({'files':FILES,'limits':LIMITS}).encode()))

def create(protector=None):
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
$policyPath=Join-Path $root 'home-access.dpapi'
if (Test-Path -LiteralPath $policyPath) {
    $raw=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($policyPath),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    $policy=[Text.Encoding]::UTF8.GetString($raw)|ConvertFrom-Json
    [Array]::Clear($raw,0,$raw.Length)
    $result.agent.home_access=$policy
    $result.api.home_access=$policy
}
Write-Output ($result|ConvertTo-Json -Depth 40 -Compress)
'''
    bootstrap=json.loads(_powershell(script))
    payload={'kind':'echo-remote','version':2,'created_at':time.time(),**saved,'bootstrap':bootstrap}
    payload['bootstrap']=restored_bootstrap(payload)
    destination=ROOT/'backups'/(time.strftime('echo-host-%Y%m%d-%H%M%S-')+secrets.token_hex(4)+'.echo-backup')
    destination.parent.mkdir(exist_ok=True)
    protector=protector or WindowsProtector()
    write_archive(destination,payload,protector,
                  lambda name:docker('exec','-i','echo-api','python','-c',PHOTO,data=json.dumps(name).encode()))
    try:
        if saved!=collect():raise ValueError('Saved data changed during backup; try again')
        read_archive(destination,protector)
    except Exception:
        destination.unlink();raise
    return destination

def restore(path,protector=None):
    payload=read_archive(path,protector)
    payload['bootstrap']=restored_bootstrap(payload)
    install(ROOT) # The restored policy uses the same serialized recovery helper.
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
    manage('RestoreBootstrap',payload['bootstrap'])
    docker('start','echo-agent','echo-api');manage('Recover')
    return previous


def portable_copy(path,source,target):
    """Rewrap a verified backup locally; preserve the original and photo ciphertext."""
    payload=read_archive(path,source)
    payload['version']=2;payload.setdefault('photos',{})
    destination=ROOT/'backups'/(time.strftime('echo-portable-%Y%m%d-%H%M%S-')+secrets.token_hex(4)+'.echo-backup')
    destination.parent.mkdir(exist_ok=True)
    write_archive(destination,payload,target,lambda name:read_photo(path,name,payload['photos'][name]))
    try:read_archive(destination,target)
    except Exception:destination.unlink();raise
    return destination


def passphrase_protector(*,confirm=False):
    if not sys.stdin.isatty():raise PassphraseError('Open an interactive terminal to enter the recovery passphrase privately.')
    # getpass can otherwise fall back to echoed input when no terminal is usable.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('error',getpass.GetPassWarning)
        try:
            value=getpass.getpass('New recovery passphrase: ' if confirm else 'Recovery passphrase: ')
            protector=PassphraseProtector(value)
            if confirm and getpass.getpass('Confirm recovery passphrase: ')!=value:
                raise PassphraseError('The recovery passphrases did not match.')
            return protector
        except getpass.GetPassWarning:
            raise PassphraseError('No private terminal input is available. Open an interactive terminal.') from None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['create','inspect','restore','make-portable'])
    parser.add_argument('archive',nargs='?',type=Path)
    parser.add_argument('--portable',action='store_true',help='Create with a recovery passphrase instead of Windows DPAPI')
    args=parser.parse_args()
    try:
        if args.portable and args.action!='create':raise ValueError('--portable applies only to create')
        if args.action=='create':
            print(create(passphrase_protector(confirm=True) if args.portable else None));return
        if not args.archive:raise ValueError('Choose an archive file')
        kind=protection_kind(args.archive)
        protector=passphrase_protector() if kind=='passphrase' else WindowsProtector()
        payload=read_archive(args.archive,protector)
        if args.action=='make-portable':print(portable_copy(args.archive,protector,passphrase_protector(confirm=True)));return
        if args.action=='inspect':print(json.dumps({'version':payload['version'],'protection':kind,'created_at':payload['created_at'],'files':list(payload['files']),'photos':len(payload.get('photos',{})),'verified':True}));return
        previous=restore(args.archive,protector)
        print('Echo recovery applied. Previous data preserved at '+str(previous))
    except PassphraseError as error:raise SystemExit(str(error)) from None
    except Exception:
        # Native exception output may contain private bootstrap material.
        raise SystemExit('Echo recovery could not complete. Existing archives were preserved. Check the archive, host availability, and the recovery passphrase or Windows account used to protect it.') from None

if __name__=='__main__':main()
