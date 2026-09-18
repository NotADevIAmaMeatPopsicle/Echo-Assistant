"""Replace Echo's private UI device allowlist using exact Tailscale node names.

Does not change the tailnet ACL, tags, Serve configuration or other services.
The complete intended set must be supplied with repeated --allow arguments.
"""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.remote_host import _powershell


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow', action='append', required=True, help='Exact Tailscale HostName')
    args = parser.parse_args()
    inventory = json.loads(_powershell("& (Get-Command tailscale.exe -ErrorAction Stop).Source status --json"))
    nodes = [inventory['Self'], *inventory.get('Peer', {}).values()]
    chosen = []
    for name in args.allow:
        matches = [n for n in nodes if n['HostName'].casefold() == name.casefold()]
        if len(matches) != 1:
            raise SystemExit('Each requested name must match exactly one current Tailscale node')
        node = matches[0]
        if node['ID'] not in {n['id'] for n in chosen}:
            chosen.append({'name': node['HostName'], 'id': node['ID'], 'ips': node['TailscaleIPs']})
    script = r'''
$ErrorActionPreference='Stop'
$root=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo'
$path=Join-Path $root 'tailnet.json'
$config=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
# Keep the array inside an object: Windows PowerShell can wrap a root JSON array
# in a PSObject with value/Count properties when captured from a pipeline.
$update=ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())
$config.allowed_devices=$update.allowed_devices
$temporary=$path+'.tmp'
[IO.File]::WriteAllText($temporary,($config|ConvertTo-Json -Depth 10),(New-Object Text.UTF8Encoding($false)))
Stop-ScheduledTask -TaskName 'Echo Private Tailnet UIs'
Move-Item -LiteralPath $temporary -Destination $path -Force
Start-ScheduledTask -TaskName 'Echo Private Tailnet UIs'
Write-Output '{"updated":true}'
'''
    result = json.loads(_powershell(script, json.dumps({'allowed_devices': chosen}).encode()))
    print(json.dumps({**result, 'devices': [n['name'] for n in chosen]}))


if __name__ == '__main__': main()
