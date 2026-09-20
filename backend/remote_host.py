"""Narrow, authenticated management of Echo's dedicated Remote host bootstrap."""
from backend import deployment
import base64
import hashlib
import json
from pathlib import Path
import subprocess

HOST = deployment.ssh_target()
HELPER = "(Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo/recover.ps1')"


def _powershell(script, data=b'', timeout=45):
    # Windows OpenSSH's default shell has a command-line length limit. Send the
    # script separately from its JSON/source payload through the encrypted stdin.
    bootstrap = '$s=[Console]::In.ReadLine(); & ([scriptblock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($s))))'
    encoded = base64.b64encode(bootstrap.encode('utf-16-le')).decode('ascii')
    envelope = base64.b64encode(script.encode('utf-8')) + b'\n' + data
    try:
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', HOST,
            'powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
            input=envelope, capture_output=True, timeout=timeout, check=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.stdout.decode('utf-8-sig').strip()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise RuntimeError('Remote host could not confirm the requested Echo configuration change') from None


def manage(mode, payload=None):
    if mode not in {'Save', 'SavePolicy', 'SaveApi', 'RestoreBootstrap', 'Recover', 'RecoverApi', 'Status'}: raise ValueError('Unknown recovery action')
    script = "$ProgressPreference='SilentlyContinue'; & " + HELPER + " -Mode " + mode + '; exit $LASTEXITCODE'
    data = b'' if payload is None else json.dumps(payload, ensure_ascii=True).encode()
    return json.loads(_powershell(script, data, timeout=90 if mode == 'Recover' else 45))


def install(root):
    """Install only Echo's dedicated current-user recovery task and helper."""
    source = (Path(root) / 'deploy/remote/recover.ps1').read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    probe = r'''
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$path=(Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo/recover.ps1')
$task=Get-ScheduledTask -TaskName 'Echo Runtime Recovery' -ErrorAction SilentlyContinue
$current=$false
if ((Test-Path -LiteralPath $path) -and $task -and $task.Actions.Arguments.Contains($path) -and $task.Actions.Execute -eq (Join-Path $PSHOME 'powershell.exe')) {
    $current=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -eq 'DIGEST'
}
Write-Output (@{current=$current}|ConvertTo-Json -Compress)
'''.replace('DIGEST', digest)
    if json.loads(_powershell(probe)).get('current'):
        return {'installed':True, 'task':'Echo Runtime Recovery', 'unchanged':True}
    script = r'''
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$directory=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo'
if ($directory -ne (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo')) { throw 'Unexpected Echo installation path' }
if ((Test-Path -LiteralPath $directory) -and ((Get-Item -LiteralPath $directory).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Echo installation cannot be a linked directory' }
$null=New-Item -ItemType Directory -Path $directory -Force
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$acl=New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner($identity.User)
foreach ($sid in @($identity.User,(New-Object Security.Principal.SecurityIdentifier('S-1-5-18')))) {
    $rule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $directory -AclObject $acl
$path=Join-Path $directory 'recover.ps1'
[IO.File]::WriteAllText($path,[Console]::In.ReadToEnd(),(New-Object Text.UTF8Encoding($false)))
$name='Echo Runtime Recovery'
$existing=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and -not $existing.Actions.Arguments.Contains($path)) { throw 'Recovery task name is already in use' }
$action=New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'powershell.exe') -WorkingDirectory $directory -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$path+'" -Mode Recover')
$logon=New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$periodic=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal=New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$null=Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon,$periodic) -Principal $principal -Settings $settings -Description 'Restore only Echo bootstrap credentials into its running Docker container after restart.' -Force
Write-Output '{"installed":true,"task":"Echo Runtime Recovery"}'
'''
    return json.loads(_powershell(script, source))
