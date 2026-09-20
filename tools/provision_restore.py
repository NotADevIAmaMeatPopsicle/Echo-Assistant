"""Fresh-host restore, composed from Echo's existing archive/Compose/recovery tools."""
from __future__ import annotations

from tools.provision_error import ProvisionError

import base64
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

from tools import provision_checks as checks
from tools.recovery_archive import FILES, LIMITS, protection_kind, read_archive, read_photo, restored_bootstrap

ROOT = Path(__file__).resolve().parents[1]
CONTAINERS = {'echo-api', 'echo-agent'}
VOLUMES = {'echo_host_data', 'echo_agent_packages', 'echo_agent_uv_cache'}
HOST_EMPTY = r'''
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
$root=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Echo'
$occupied=(Test-Path -LiteralPath $root) -or [bool](Get-ScheduledTask -TaskName 'Echo Runtime Recovery' -ErrorAction SilentlyContinue) -or [bool](Get-ScheduledTask -TaskName 'Echo Spotify Discovery' -ErrorAction SilentlyContinue)
$listeners=Get-NetTCPConnection -LocalPort 18668,18642 -State Listen -ErrorAction SilentlyContinue
$occupied=$occupied -or [bool]$listeners
$id=(& docker info --format '{{.ID}}' 2>$null)
if ($LASTEXITCODE -ne 0) { throw 'Host Docker unavailable' }
@{occupied=[bool]$occupied;docker_id=([string]$id).Trim()}|ConvertTo-Json -Compress
'''


def fresh_state(context, api_image, agent_image):
    from backend import deployment
    target = deployment.ssh_target()
    current = checks.docker(context, 'info', '--format', '{{.ID}}').strip()
    host = checks.remote_probe(target, HOST_EMPTY)
    if not current or host['docker_id'] != current:
        raise ProvisionError('Selected Docker context differs from the recovery account daemon')
    if host['occupied']:
        raise ProvisionError('Host Echo directory, recovery/discovery task or management listener already exists')
    names = set(checks.docker(context, 'container', 'ls', '-a', '--format', '{{.Names}}').splitlines())
    volumes = set(checks.docker(context, 'volume', 'ls', '--format', '{{.Name}}').splitlines())
    networks = set(checks.docker(context, 'network', 'ls', '--format', '{{.Name}}').splitlines())
    if CONTAINERS & names or VOLUMES & volumes or 'echo_default' in networks:
        raise ProvisionError('Echo containers, data volumes, or network already exist; fresh restore refused')
    if 'echo_models' not in volumes:
        raise ProvisionError('Import verified models before restoring saved data')
    owner = checks.docker(context, 'volume', 'inspect', 'echo_models', '--format', '{{index .Labels "org.echo.owner"}}')
    if owner != 'round-voice':
        raise ProvisionError('Model volume is not owned by Echo')
    images = {'api': checks.image(context, api_image), 'agent': checks.image(context, agent_image)}
    if any(not re.fullmatch(r'sha256:[a-f0-9]{64}', item['id']) for item in images.values()):
        raise ProvisionError('Could not pin existing image identities')
    return images


def _stage(context, image, path, payload):
    from tools.recovery_restore import SCRIPT
    # Created data volume only. The helper validates and stages encrypted files,
    # resets queued announcements, then publishes them using its existing rules.
    script = SCRIPT + "\nfor p in Path('/opt/echo/local').rglob('*'):\n if not p.is_symlink(): os.chown(p,10000,10000)\nos.chown('/opt/echo/local',10000,10000)\n"
    command = ['docker', '--context', context, 'run', '--rm', '-i', '--network', 'none',
               '--pull', 'never', '--user', '0', '--log-driver', 'none',
               '--mount', 'type=volume,src=echo_host_data,dst=/opt/echo/local',
               '--entrypoint', 'python', image, '-c', script]
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL) as process:
        try:
            message = {'names': FILES, 'limits': LIMITS, 'files': payload['files'],
                       'photos': payload.get('photos', {}), 'storage_key': payload['bootstrap']['api']['storage_key']}
            process.stdin.write(json.dumps(message).encode() + b'\n')
            for name, item in payload.get('photos', {}).items():
                raw = read_photo(path, name, item)
                process.stdin.write(json.dumps({'name': name, 'data': base64.b64encode(raw).decode()}).encode() + b'\n')
            process.stdin.close()
            if process.wait(timeout=120):
                raise ProvisionError('Fresh recovery staging failed')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def restore_fresh(path, protector, *, context, api_image, agent_image, execute=False):
    """Never replace an existing deployment. Failures retain state for inspection.

    Callers must separately preflight Windows/disk/models. Plan checks envelope
    type and host occupancy only; no archive data is unlocked until execute=True.
    """
    context = checks.context_name(context)
    kind = protection_kind(path)
    images = fresh_state(context, api_image, agent_image)
    if not execute:
        return {'executed': False, 'fresh_target': True, 'archive_protection': kind,
                'archive_verified': False, 'scope': 'loopback validation services; voice disabled'}
    payload = read_archive(path, protector)
    payload['bootstrap'] = restored_bootstrap(payload)
    # Recheck after archive validation/private passphrase entry, before mutation.
    if fresh_state(context, api_image, agent_image) != images:
        raise ProvisionError('Target images changed during preflight')
    from backend import deployment, remote_host
    remote_host.HOST = deployment.ssh_target()
    attempt = uuid.uuid4().hex
    label = 'org.echo.provision-attempt'
    override = {'services': {'api': {'image': images['api']['id'], 'labels': {label: attempt},
                                    'environment': {'ECHO_VOICE_ENABLED': '0', 'ECHO_DEPLOYMENT_MODE': 'validation'}},
                             'agent': {'image': images['agent']['id'], 'labels': {label: attempt}}},
                'volumes': {name: {'labels': {label: attempt}} for name in ('host_data', 'agent_packages', 'agent_uv_cache')}}
    wifi = payload['bootstrap']['api'].get('wifi')
    if wifi:
        mac = wifi.get('mac')
        if not isinstance(mac, str) or not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac):
            raise ProvisionError('Archived device identity is invalid')
        override['services']['api']['environment']['ECHO_DEVICE_MAC'] = mac

    def owned(kind, name):
        field = '.Config.Labels' if kind == 'container' else '.Labels'
        try:
            return checks.docker(context, kind, 'inspect', name, '--format',
                                 '{{index ' + field + ' "' + label + '"}}') == attempt
        except Exception:
            return False
    changed = False
    try:
        changed = True
        checks.docker(context, 'compose', '--project-name', 'echo',
                      '-f', str(ROOT / 'deploy/remote/compose.yaml'),
                      '-f', str(ROOT / 'deploy/host/compose.yaml'), '-f', '-',
                      'create', '--no-recreate', '--no-build', '--pull', 'never', 'api', 'agent',
                      data=json.dumps(override).encode(), timeout=90)
        if not all(owned('container', name) for name in CONTAINERS) or not all(owned('volume', name) for name in VOLUMES):
            raise ProvisionError('Fresh resources do not belong to this restore attempt')
        _stage(context, images['api']['id'], path, payload)
        remote_host.install(ROOT)
        remote_host.manage('RestoreBootstrap', payload['bootstrap'])
        checks.docker(context, 'start', 'echo-agent', 'echo-api', timeout=35)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = remote_host.manage('Recover')
            if state.get('state') == 'ready' and state.get('api') == 'ready':
                return {'executed': True, 'archive_verified': True, 'services_ready': True,
                        'scope': 'loopback validation services; voice disabled',
                        'physical_or_fresh_machine_acceptance': False}
            if state.get('state') == 'recovery_failed' or state.get('api') == 'recovery_failed':
                raise ProvisionError('Restored runtime could not start')
            time.sleep(2)
        raise ProvisionError('Restored services did not become ready before timeout')
    except Exception:
        if changed:
            # Stop only containers created after the empty-target guard. Preserve
            # volumes, protected bootstrap and task; never retry/replace blindly.
            try:
                for name in CONTAINERS:
                    if owned('container', name):
                        checks.docker(context, 'stop', '--time', '20', name, timeout=35)
            except Exception:
                pass
        raise ProvisionError('Fresh restore failed. Partial resources were preserved; check container state before any manual recovery. Do not rerun as a fresh restore.') from None
