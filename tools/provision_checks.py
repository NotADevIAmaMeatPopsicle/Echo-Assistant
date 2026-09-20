"""Read-only, deliberately narrow replacement-host diagnostics."""
from __future__ import annotations

from tools.provision_error import ProvisionError

import base64
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys

GIB = 1024 ** 3
API_IMAGE = 'echo-host:validation-0.1'
AGENT_IMAGE = 'echo-hermes:trial-0.1'


def run(args, *, data=None, timeout=25):
    """Never include external stderr/stdout in exception messages."""
    try:
        result = subprocess.run(args, input=data, capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        raise ProvisionError('Required command was unavailable or timed out') from None
    if result.returncode:
        raise ProvisionError('Required command failed; check the selected host and prerequisites')
    return result.stdout.decode('utf-8-sig').strip()


def version(args, minimum):
    output = run(args)
    match = re.search(r'(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?', output)
    if not match:
        raise ProvisionError('Could not identify tool version')
    parsed = tuple(int(v or 0) for v in match.groups())
    return {'version': '.'.join(map(str, parsed)), 'supported': parsed >= minimum}


def context_name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', value or ''):
        raise ProvisionError('Select an explicit Docker context')
    return value


def ssh_name(value):
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,200}', value or '') or value.startswith('-'):
        raise ProvisionError('Select an explicit SSH alias or user@host')
    return value


def image_name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}', value or ''):
        raise ProvisionError('Invalid image reference')
    return value


def docker(context, *args, **kwargs):
    return run(['docker', '--context', context_name(context), *args], **kwargs)


def image(context, reference):
    # Inspect only these fields; Docker environment metadata can hold credentials.
    result = json.loads(docker(context, 'image', 'inspect', image_name(reference), '--format',
                               '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}},"size":{{.Size}}}'))
    if result.get('os') != 'linux' or result.get('architecture') != 'amd64':
        raise ProvisionError('Image must be an existing Linux amd64 image')
    return result


def remote_probe(target, script, data=b''):
    # Same stdin envelope as backend.remote_host; no secrets or shell interpolation.
    bootstrap = '$s=[Console]::In.ReadLine(); & ([scriptblock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($s))))'
    encoded = base64.b64encode(bootstrap.encode('utf-16-le')).decode()
    return json.loads(run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                          '-o', 'StrictHostKeyChecking=yes', ssh_name(target), 'powershell.exe',
                          '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                         data=base64.b64encode(script.encode()) + b'\n' + data, timeout=35))


HOST_PROBE = r'''
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$options=[Console]::In.ReadToEnd()|ConvertFrom-Json
$os=Get-CimInstance Win32_OperatingSystem
$computer=Get-CimInstance Win32_ComputerSystem
$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1
$restart=(Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')
$pending=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations
$restart=$restart -or [bool]$pending
$path=[string]$options.disk_path
if (-not [IO.Path]::IsPathRooted($path) -or -not (Test-Path -LiteralPath $path)) { throw 'Select an existing absolute host Docker backing-disk path' }
$drive=(Get-Item -LiteralPath $path).PSDrive
if ($null -eq $drive.Free) { throw 'Host disk free space unavailable' }
$dockerId=(& docker info --format '{{.ID}}' 2>$null)
if ($LASTEXITCODE -ne 0) { throw 'Host Docker unavailable' }
$wsl=Get-Command wsl.exe -ErrorAction SilentlyContinue
$wslReady=$false
if ($wsl) { $null=& wsl.exe --status 2>$null; $wslReady=$LASTEXITCODE -eq 0 }
$ssh=Get-Service sshd -ErrorAction SilentlyContinue
@{ windows_build=[int]$os.BuildNumber; powershell=$PSVersionTable.PSVersion.ToString(); memory_bytes=[long]$computer.TotalPhysicalMemory; free_bytes=[long]$drive.Free; restart_needed=[bool]$restart; virtualization=[bool]($computer.HypervisorPresent -or $cpu.VirtualizationFirmwareEnabled); wsl_ready=$wslReady; ssh_running=[bool]($ssh -and $ssh.Status -eq 'Running'); docker_id=([string]$dockerId).Trim() }|ConvertTo-Json -Compress
'''


def preflight(options, *, model_bytes=0):
    checks = []

    def check(name, call):
        try:
            details = call()
            ok = details.pop('supported', True)
            checks.append({'check': name, 'ok': bool(ok), **details})
            return details if ok else None
        except (ValueError, OSError, RuntimeError, KeyError, TypeError):
            checks.append({'check': name, 'ok': False, 'detail': 'Missing, invalid, unavailable, or not verifiable'})
            return None

    check('management_python', lambda: {'version': platform.python_version(),
          'supported': os.name == 'nt' and (3, 12) <= sys.version_info[:2] < (3, 15) and struct.calcsize('P') == 8})
    def dependencies():
        versions = {}
        for name in ('cryptography', 'pydantic', 'httpx'):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = 'missing'
        minimum = {'cryptography': (46, 0), 'pydantic': (2, 0), 'httpx': (0, 28)}
        compatible = True
        for name, text in versions.items():
            found = re.match(r'(\d+)\.(\d+)', text)
            compatible = compatible and bool(found and tuple(map(int, found.groups())) >= minimum[name])
        return {'supported': compatible, 'versions': versions}
    check('recovery_dependencies', dependencies)
    check('git', lambda: version(['git', '--version'], (2, 30, 0)))
    check('powershell', lambda: version(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', '$PSVersionTable.PSVersion.ToString()'], (5, 1, 0)))
    check('ssh_client', lambda: version(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                                       '(Get-Command ssh.exe -ErrorAction Stop).Version.ToString()'], (7, 0, 0)))
    check('docker_client', lambda: version(['docker', '--version'], (24, 0, 0)))
    check('compose', lambda: version(['docker', '--context', context_name(options['docker_context']), 'compose', 'version', '--short'], (2, 20, 0)))

    def server():
        value = json.loads(docker(options['docker_context'], 'info', '--format',
            '{"id":{{json .ID}},"os":{{json .OSType}},"architecture":{{json .Architecture}},"memory_bytes":{{.MemTotal}},"version":{{json .ServerVersion}}}'))
        if value['os'] != 'linux' or value['architecture'] not in ('x86_64', 'amd64') or not value['id']:
            raise ProvisionError('Requires the Linux x86-64 Docker engine')
        daemon_id.append(value.pop('id'))
        match = re.match(r'(\d+)\.', value['version'])
        value['supported'] = value['memory_bytes'] >= 6 * GIB and bool(match and int(match.group(1)) >= 24)
        return value

    daemon_id = []
    check('docker_server', server)

    def host():
        value = remote_probe(options['ssh_target'], HOST_PROBE,
                             json.dumps({'disk_path': options['host_disk_path']}).encode())
        matches = bool(daemon_id and value.pop('docker_id') == daemon_id[0])
        value['same_docker_daemon'] = matches
        value['minimum_free_bytes'] = max(options['disk_reserve_gib'] * GIB, model_bytes + 10 * GIB)
        value['supported'] = (matches and value['windows_build'] >= 19045 and value['virtualization'] and
                              value['wsl_ready'] and value['ssh_running'] and not value['restart_needed'] and
                              value['memory_bytes'] >= 8 * GIB and value['free_bytes'] >= value['minimum_free_bytes'])
        return value

    check('windows_host', host)
    for role in ('api', 'agent'):
        def inspect(role=role):
            value = image(options['docker_context'], options[role + '_image'])
            value.pop('id')
            return value
        check(role + '_image', inspect)
    return {'ready': all(row['ok'] for row in checks), 'checks': checks,
            'disk_estimate': 'Conservative reserve, not a measured image-build peak; select the real Docker Desktop backing-disk drive.',
            'scope': 'Windows Docker Desktop with WSL 2; existing Linux amd64 images; loopback validation services'}
