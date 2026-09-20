"""Inspect or explicitly bootstrap a replacement Windows/Docker Echo host.

The default action is plan. Every write requires --execute. No passphrases,
provider keys, host identities, or model weights are generated in manifests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.provision_error import ProvisionError
from tools import provision_checks as checks
from tools import provision_models as models

PATHS = {'source', 'destination', 'manifest', 'archive', 'environment'}
CONFIG_FIELDS = PATHS | {'docker_context', 'ssh_target', 'host_disk_path', 'api_image', 'agent_image',
                        'disk_reserve_gib', 'manifest_sha256'}
COMPONENTS = ('git', 'python', 'docker', 'wsl', 'openssh-client', 'openssh-server', 'recovery-env')


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('action', nargs='?', default='plan',
                        choices=('plan', 'bootstrap', 'models-manifest', 'models-restore', 'models-import', 'restore'))
    result.add_argument('--config', type=Path, help='Private nonsecret JSON options; relative paths resolve against this file')
    result.add_argument('--execute', action='store_true', help='Explicitly perform the selected write operation')
    result.add_argument('--component', choices=COMPONENTS, help='One local prerequisite to install; bootstrap only')
    for name in sorted(CONFIG_FIELDS):
        result.add_argument('--' + name.replace('_', '-'), type=int if name == 'disk_reserve_gib' else str)
    return result


def options(args):
    result = {'api_image': checks.API_IMAGE, 'agent_image': checks.AGENT_IMAGE,
              'disk_reserve_gib': 30, 'source': ROOT / 'local/models'}
    if args.config:
        if args.config.stat().st_size > 32_000:
            raise ProvisionError('Provisioning configuration is too large')
        value = json.loads(args.config.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or set(value) - CONFIG_FIELDS:
            raise ProvisionError('Configuration contains unsupported fields; credentials are not accepted')
        for name, entry in value.items():
            if name in PATHS:
                if not isinstance(entry, str) or not entry:
                    raise ProvisionError('Configuration path must be a nonempty string')
                entry = args.config.absolute().parent / entry
            result[name] = entry
    for name in CONFIG_FIELDS:
        if getattr(args, name) is not None:
            result[name] = getattr(args, name)
    for name in ('docker_context', 'ssh_target'):
        result.setdefault(name, os.environ.get('ECHO_' + name.upper(), ''))
    if type(result['disk_reserve_gib']) is not int or not 10 <= result['disk_reserve_gib'] <= 100_000:
        raise ProvisionError('Disk reserve must be 10 through 100000 GiB')
    for name in PATHS & result.keys():
        result[name] = Path(result[name]).absolute()
    for name in CONFIG_FIELDS - PATHS - {'disk_reserve_gib'}:
        if name in result and not isinstance(result[name], str):
            raise ProvisionError('Provisioning options must be strings')
    return result


def require(value, *names):
    if any(not value.get(name) for name in names):
        raise ProvisionError('Required options: ' + ', '.join('--' + name.replace('_', '-') for name in names))


def select_host(value):
    require(value, 'docker_context', 'ssh_target', 'host_disk_path')
    checks.context_name(value['docker_context'])
    checks.ssh_name(value['ssh_target'])
    checks.image_name(value['api_image'])
    checks.image_name(value['agent_image'])
    # Process-local only. Existing helpers keep their own deployment contract.
    os.environ['ECHO_DOCKER_CONTEXT'] = value['docker_context']
    os.environ['ECHO_SSH_TARGET'] = value['ssh_target']


def model_manifest(value):
    require(value, 'manifest', 'manifest_sha256')
    document = models.load(value['manifest'], value['manifest_sha256'])
    models.require_runtime(document)
    return document


def bootstrap_commands(component, value):
    if component in ('git', 'python', 'docker'):
        package = {'git': 'Git.Git', 'python': 'Python.Python.3.13', 'docker': 'Docker.DockerDesktop'}[component]
        return [['winget', 'install', '--id', package, '--exact', '--source', 'winget',
                 '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity']]
    if component == 'wsl':
        return [['wsl.exe', '--install', '--no-distribution', '--no-launch']]
    if component in ('openssh-client', 'openssh-server'):
        feature = 'Client' if component == 'openssh-client' else 'Server'
        return [['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                 "$ErrorActionPreference='Stop'; $r=Add-WindowsCapability -Online -Name OpenSSH." + feature +
                 "~~~~0.0.1.0; if ($r.RestartNeeded) { exit 3010 }"]]
    if component == 'recovery-env':
        require(value, 'environment')
        environment = models.unlinked(value['environment'])
        if environment.exists():
            raise ProvisionError('Choose a new recovery environment; an existing environment is preserved')
        python = environment / 'Scripts/python.exe'
        # Match current repository pins without installing audio/server packages
        # or downloading speech models just to manage an encrypted backup.
        return [[sys.executable, '-m', 'venv', str(environment)],
                [str(python), '-m', 'pip', 'install', 'cryptography==46.0.7',
                 'pydantic==2.13.3', 'httpx==0.28.1']]
    raise ProvisionError('Select one prerequisite with --component')


def bootstrap(component, value, execute):
    commands = bootstrap_commands(component, value)
    if not execute:
        return {'executed': False, 'component': component, 'commands': commands,
                'scope': 'This management machine only; run locally on the intended replacement host'}
    if os.name != 'nt':
        raise ProvisionError('Prerequisite installation requires Windows')
    for command in commands:
        # Inherit the operator terminal for installer/UAC progress. No background
        # helper, global context switch, unattended reboot or secret parameters.
        completed = subprocess.run(command, check=False)
        code = completed.returncode & 0xffffffff
        if code in (1641, 3010):
            return {'executed': True, 'component': component, 'restart_needed': True,
                    'ready': False, 'next': 'Restart Windows, open a new terminal, and rerun plan'}
        if code:
            raise ProvisionError('Prerequisite installer failed; inspect its terminal output and rerun plan')
    return {'executed': True, 'component': component, 'ready': False,
            'next': 'Open a new terminal and rerun plan; installation alone does not confirm host readiness'}


def dispatch(args, value):
    if args.action == 'bootstrap':
        return bootstrap(args.component, value, args.execute)
    if args.component:
        raise ProvisionError('--component applies only to bootstrap')
    if args.action == 'models-manifest':
        require(value, 'source', 'manifest')
        document = models.inventory(value['source'])
        models.require_runtime(document)
        raw = models.raw_manifest(document)
        result = {'executed': args.execute, 'files': len(document['files']),
                  'bytes': sum(item['size'] for item in document['files'].values()),
                  'manifest_sha256': hashlib.sha256(raw).hexdigest()}
        if args.execute:
            target = models.unlinked(value['manifest'])
            if target.is_relative_to(models.unlinked(value['source'])):
                raise ProvisionError('Store the model manifest outside the model source tree')
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
        return result
    if args.action == 'models-restore':
        require(value, 'source', 'destination')
        return models.restore(value['source'], value['destination'], model_manifest(value), execute=args.execute)
    if args.action == 'models-import':
        require(value, 'source', 'docker_context')
        document = model_manifest(value)
        models.verify_source(value['source'], document)
        from tools.import_remote_models import IMAGE
        checks.image(value['docker_context'], IMAGE)
        if not args.execute:
            return {'executed': False, 'local_files_verified': len(document['files']),
                    'remote_volume_verified': False, 'next': 'Explicit import uses the existing importer ownership and conflict checks'}
        completed = subprocess.run([sys.executable, str(ROOT / 'tools/import_remote_models.py'),
                                    '--source', str(value['source']), '--context', value['docker_context']], check=False)
        if completed.returncode:
            raise ProvisionError('Model import did not complete; existing volume was preserved')
        return {'executed': True, 'model_import_verified': True}
    if args.action == 'restore':
        select_host(value)
    if args.action == 'plan' and args.execute:
        raise ProvisionError('plan never executes changes; select an explicit operation')
    model_bytes = 0
    artifact = {'model_manifest_verified': False, 'model_source_verified': False}
    if value.get('manifest'):
        document = model_manifest(value)
        models.verify_source(value['source'], document)
        model_bytes = sum(item['size'] for item in document['files'].values())
        artifact.update(model_manifest_verified=True, model_source_verified=True, model_bytes=model_bytes)
    result = checks.preflight(value, model_bytes=model_bytes)
    result['artifacts'] = artifact
    if value.get('archive'):
        from tools.recovery_archive import protection_kind
        artifact.update(archive_protection=protection_kind(value['archive']), archive_verified=False)
    else:
        artifact['archive_present'] = False
    result['missing_options'] = [name for name in ('docker_context', 'ssh_target', 'host_disk_path') if not value.get(name)]
    result['ready_to_validate_restore'] = result['ready'] and artifact['model_source_verified'] and bool(value.get('archive'))
    result['ready_for_restore'] = False
    result['remaining_restore_checks'] = ['empty target and recovery-account Docker identity', 'remote model hashes', 'protected archive integrity']
    if args.action == 'plan':
        result['executed'] = False
        return result
    require(value, 'archive', 'manifest', 'manifest_sha256')
    if not result['ready_to_validate_restore']:
        return result | {'executed': False, 'restore_blocked': True}
    from tools.provision_restore import restore_fresh
    planned = restore_fresh(value['archive'], None, context=value['docker_context'],
                            api_image=value['api_image'], agent_image=value['agent_image'], execute=False)
    if not args.execute:
        return planned
    protector = None
    if args.execute:
        from tools.backup_remote import passphrase_protector
        from backend.settings import WindowsProtector
        protector = passphrase_protector() if artifact['archive_protection'] == 'passphrase' else WindowsProtector()
        # Verify the actual remote model inventory with the existing read-only
        # checker before restoring saved speech selections into a fresh service.
        from tools.import_remote_models import IMAGE, check
        checks.image(value['docker_context'], IMAGE)
        state = check({name: item['sha256'] for name, item in document['files'].items()}, value['docker_context'])
        if any(state[key] for key in ('missing', 'different', 'extra')):
            raise ProvisionError('Docker model volume does not match the verified manifest')
    return restore_fresh(value['archive'], protector, context=value['docker_context'],
                         api_image=value['api_image'], agent_image=value['agent_image'], execute=args.execute)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = dispatch(args, options(args))
        print(json.dumps(result, indent=2))
        return 2 if result.get('restore_blocked') or args.action == 'plan' and not result.get('ready_to_validate_restore') else 0
    except ProvisionError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (ValueError, OSError, RuntimeError, ImportError, KeyError, TypeError):
        # Never expose a traceback, archive payload, command output or private
        # bootstrap. These instructions are static and independent of secret data.
        print('Provisioning could not complete. Check the selected options, prerequisites, artifact hashes, free space, target occupancy and private recovery passphrase. Existing archives and conflicting model files are preserved.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
