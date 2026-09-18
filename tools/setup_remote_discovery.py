"""Install Echo's scoped Windows DNS-SD helper; no audio or credentials involved."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import deployment
from backend.remote_host import _powershell


def setup():
    payload={name:(ROOT/path).read_text(encoding='utf-8') for name,path in {
        'spotify_discovery.py':'deploy/remote/spotify_discovery.py',
        'discovery-requirements.txt':'config/discovery-windows.lock.txt'}.items()}
    script=r'''
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$root=(Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo')
if (-not (Test-Path -LiteralPath (Join-Path $root 'recover.ps1'))) { throw 'Install the private Echo runtime first' }
$files=[Console]::In.ReadToEnd()|ConvertFrom-Json
foreach ($name in @('spotify_discovery.py','discovery-requirements.txt')) {
    [IO.File]::WriteAllText((Join-Path $root $name),$files.$name,(New-Object Text.UTF8Encoding($false)))
}
$python=Join-Path $root 'discovery-python\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & py -3.13 -m venv (Join-Path $root 'discovery-python')
    if ($LASTEXITCODE) { throw 'Discovery virtual environment failed' }
}
$null=& $python -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $root 'discovery-requirements.txt') 2>&1
if ($LASTEXITCODE) { throw 'Discovery dependency setup failed' }
$pythonw=Join-Path $root 'discovery-python\Scripts\pythonw.exe'
$basePython=& $python -c "import sys; print(sys._base_executable)"
$networkPython=Join-Path (Split-Path $basePython.Trim() -Parent) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $networkPython)) { throw 'Discovery interpreter identity could not be verified' }
if (-not (Test-Path -LiteralPath (Join-Path $root 'discovery.json'))) {
    [IO.File]::WriteAllText((Join-Path $root 'discovery.json'),'HOLD_CONFIG')
}
$address=Get-NetIPAddress -AddressFamily IPv4 -IPAddress deployment.device_host()
if ($address.PrefixLength -ne LAN_PREFIX) { throw 'Home subnet changed; review network setup' }
foreach ($rule in @(
    @{Name='Echo-Spotify-Discovery';Protocol='UDP';Port=5353;Program=$networkPython},
    @{Name='Echo-Spotify-Receiver';Protocol='TCP';Port=18899;Program='Any'},
    @{Name='Echo-Paired-Voice';Protocol='TCP';Port=8769;Program='Any'}
)) {
    $existing=Get-NetFirewallRule -Name $rule.Name -ErrorAction SilentlyContinue
    if ($existing -and $existing.Group -ne 'Echo speaker') { throw 'Firewall rule name belongs to another application' }
    $localAddresses=if ($rule.Protocol -eq 'UDP') { @(deployment.device_host(),'224.0.0.251') } else { @(deployment.device_host()) }
    if (-not $existing) {
        $null=New-NetFirewallRule -Name $rule.Name -DisplayName $rule.Name -Group 'Echo speaker' -Direction Inbound -Action Allow -Enabled True -Profile Any -Protocol $rule.Protocol -LocalPort $rule.Port -LocalAddress $localAddresses -RemoteAddress 'LAN_SUBNET' -InterfaceAlias $address.InterfaceAlias -Program $rule.Program
    } else {
        $null=Set-NetFirewallRule -Name $rule.Name -Direction Inbound -Action Allow -Enabled True -Profile Any -Protocol $rule.Protocol -LocalPort $rule.Port -LocalAddress $localAddresses -RemoteAddress 'LAN_SUBNET' -InterfaceAlias $address.InterfaceAlias -Program $rule.Program
    }
}
$name='Echo Spotify Discovery'
$path=Join-Path $root 'spotify_discovery.py'
$task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($task -and -not $task.Actions.Arguments.Contains($path)) { throw 'Discovery task name belongs to another application' }
if (-not $task) {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $action=New-ScheduledTaskAction -Execute $pythonw -Argument ('"'+$path+'"')
    $trigger=New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
    $principal=New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $null=Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Advertise the reachable Echo Docker Spotify receiver on the home LAN.'
}
$enabled=(Get-Content -LiteralPath (Join-Path $root 'discovery.json') -Raw|ConvertFrom-Json).enabled
Write-Output (@{installed=$true;discovery_enabled=$enabled;firewall_scope='LAN_SUBNET';task=$name}|ConvertTo-Json -Compress)
'''.replace('HOLD_CONFIG',json.dumps({'enabled':False,'host':deployment.device_host(),'port':18899}))
    script=script.replace('deployment.device_host()',json.dumps(deployment.device_host())).replace('LAN_SUBNET',deployment.lan_subnet()).replace('LAN_PREFIX',deployment.lan_subnet().split('/')[1])
    return json.loads(_powershell(script,json.dumps(payload).encode(),timeout=120))


if __name__=='__main__': print(json.dumps(setup()))
