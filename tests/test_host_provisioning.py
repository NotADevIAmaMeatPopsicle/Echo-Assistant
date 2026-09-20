"""Synthetic provisioning checks: no installs, Docker, SSH, secrets, or audio."""
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import provision_checks as checks
from tools import provision_host as cli
from tools import provision_models as models
from tools import provision_restore as recovery


class ModelProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.destination = self.root / 'destination'
        for name in models.NAMES:
            directory = self.source / name
            directory.mkdir(parents=True)
            (directory / 'model.data').write_bytes(b'synthetic ' + name.encode())
        self.value = models.inventory(self.source)

    def test_manifest_has_only_portable_names_sizes_and_hashes(self):
        path = self.root / 'models.json'
        raw = models.raw_manifest(self.value)
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(models.load(path, digest), self.value)
        self.assertNotIn(str(self.root).encode(), raw)
        path.write_bytes(raw + b' ')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            models.load(path, digest)

    def test_plan_writes_nothing_then_restore_is_verified_and_idempotent(self):
        plan = models.restore(self.source, self.destination, self.value)
        self.assertEqual(plan['missing_files'], 3)
        self.assertFalse(self.destination.exists())
        result = models.restore(self.source, self.destination, self.value, execute=True)
        self.assertEqual(result['copied_files'], 3)
        result = models.restore(self.source, self.destination, self.value, execute=True)
        self.assertEqual(result['copied_files'], 0)
        self.assertEqual(models.inventory(self.destination), self.value)

    def test_conflicting_existing_file_preserves_everything_before_any_copy(self):
        first = next(iter(self.value['files']))
        path = self.destination / first
        path.parent.mkdir(parents=True)
        path.write_bytes(b'keep this newer model')
        with self.assertRaisesRegex(ValueError, 'preserved'):
            models.restore(self.source, self.destination, self.value, execute=True)
        self.assertEqual(path.read_bytes(), b'keep this newer model')
        self.assertEqual(len(list(self.destination.rglob('*.data'))), 1)

    def test_source_tampering_or_missing_directory_never_creates_destination(self):
        name = next(iter(self.value['files']))
        (self.source / name).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            models.restore(self.source, self.destination, self.value, execute=True)
        self.assertFalse(self.destination.exists())

    def test_unsafe_paths_case_collisions_and_wrong_hash_types(self):
        first = next(iter(self.value['files']))
        model = first.split('/')[0]
        for name in ('../outside', model + '/../outside', model + '/C:escape',
                     model + '/CON.txt', model + '/file.', model + '/x\\y', model + '//file'):
            value = deepcopy(self.value)
            value['files'][name] = value['files'][first]
            with self.subTest(name=name), self.assertRaises(ValueError):
                models.validate(value)
        value = deepcopy(self.value)
        value['files'][model + '/MODEL.data'] = value['files'][first]
        with self.assertRaisesRegex(ValueError, 'Case'):
            models.validate(value)
        value = deepcopy(self.value)
        value['files'][first]['size'] = True
        with self.assertRaises(ValueError):
            models.validate(value)

    def test_duplicate_keys_and_insufficient_space_are_rejected(self):
        path = self.root / 'bad.json'
        raw = b'{"kind":"echo-models","kind":"echo-models","version":1,"files":{}}'
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            models.load(path, hashlib.sha256(raw).hexdigest())
        with patch.object(models.shutil, 'disk_usage', return_value=Mock(free=1)):
            with self.assertRaisesRegex(ValueError, 'disk space'):
                models.restore(self.source, self.destination, self.value, execute=True)
        self.assertFalse(self.destination.exists())

    def test_source_copy_change_never_publishes_damaged_file(self):
        def damaged_copy(reader, writer, **kwargs):
            writer.write(b'changed during transfer')
        with patch.object(models.shutil, 'copyfileobj', side_effect=damaged_copy):
            with self.assertRaisesRegex(ValueError, 'changed while copying'):
                models.restore(self.source, self.destination, self.value, execute=True)
        self.assertEqual(list(self.destination.rglob('*.data')), [])
        self.assertEqual(list(self.destination.rglob('.echo-model-*')), [])

    def test_linked_destination_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        try:
            self.destination.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Creating a synthetic symlink requires Windows developer mode')
        with self.assertRaisesRegex(ValueError, 'links'):
            models.restore(self.source, self.destination, self.value, execute=True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_overlapping_roots_and_unexpected_destination_files_rejected(self):
        with self.assertRaisesRegex(ValueError, 'separate trees'):
            models.restore(self.source, self.source / 'nested', self.value)
        self.destination.mkdir()
        (self.destination / 'keep.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'extra files'):
            models.restore(self.source, self.destination, self.value, execute=True)
        self.assertEqual((self.destination / 'keep.txt').read_text(), 'keep')

    def test_reparse_point_and_incomplete_runtime_inventory_are_rejected(self):
        original = Path.lstat
        def linked(path):
            if path == self.destination:
                return Mock(st_mode=0o040755, st_file_attributes=0x400)
            return original(path)
        with patch.object(Path, 'lstat', linked):
            with self.assertRaisesRegex(ValueError, 'reparse'):
                models.restore(self.source, self.destination, self.value)
        with self.assertRaisesRegex(ValueError, 'speech weights'):
            models.require_runtime(self.value)


class HostPreflightTests(unittest.TestCase):
    def options(self):
        return {'docker_context': 'synthetic', 'ssh_target': 'synthetic-host', 'host_disk_path': 'C:/',
                'disk_reserve_gib': 30, 'api_image': checks.API_IMAGE, 'agent_image': checks.AGENT_IMAGE}

    def host(self, **changes):
        return {'windows_build': 22631, 'powershell': '5.1', 'memory_bytes': 16 * checks.GIB,
                'free_bytes': 60 * checks.GIB, 'restart_needed': False, 'virtualization': True,
                'wsl_ready': True, 'ssh_running': True, 'docker_id': 'synthetic-daemon', **changes}

    def report(self, host):
        info = {'id': 'synthetic-daemon', 'os': 'linux', 'architecture': 'x86_64',
                'memory_bytes': 8 * checks.GIB, 'version': '28.0.1'}
        with patch.object(checks, 'version', return_value={'version': '99.0.0', 'supported': True}), \
             patch.object(checks, 'docker', return_value=json.dumps(info)), \
             patch.object(checks, 'remote_probe', return_value=host), \
             patch.object(checks, 'image', return_value={'id': 'synthetic', 'size': 1}), \
             patch.object(checks.importlib.metadata, 'version', return_value='1.0.0'):
            return checks.preflight(self.options())

    def test_restart_low_space_and_daemon_mismatch_block_host(self):
        for changed in ({'restart_needed': True}, {'free_bytes': 1}, {'docker_id': 'other'},
                        {'virtualization': False}, {'wsl_ready': False}):
            with self.subTest(changed=changed):
                result = self.report(self.host(**changed))
                row = next(row for row in result['checks'] if row['check'] == 'windows_host')
                self.assertFalse(row['ok'])
                self.assertNotIn('docker_id', row)
                self.assertFalse(result['ready'])

    def test_missing_image_is_an_explicit_failed_check(self):
        with patch.object(checks, 'run', side_effect=RuntimeError('unavailable')):
            result = checks.preflight(self.options())
        self.assertFalse(next(row for row in result['checks'] if row['check'] == 'api_image')['ok'])
        self.assertFalse(result['ready'])


class HostCliTests(unittest.TestCase):
    def test_bootstrap_is_plan_by_default(self):
        with patch.object(cli.subprocess, 'run') as command, patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(cli.main(['bootstrap', '--component', 'docker']), 0)
            command.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())['executed'])

    def test_no_argument_plan_reports_missing_configuration_without_writes(self):
        with patch.object(checks, 'run', side_effect=RuntimeError('missing')), \
             patch.dict('os.environ', {'ECHO_DOCKER_CONTEXT': '', 'ECHO_SSH_TARGET': ''}), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(cli.main([]), 2)
        value = json.loads(output.getvalue())
        self.assertFalse(value['executed'])
        self.assertIn('docker_context', value['missing_options'])

    def test_model_manifest_default_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inventory.json'
            value = {'kind': 'echo-models', 'version': 1, 'files': {
                name: {'size': 1, 'sha256': 'a' * 64} for name in models.runtime_files()}}
            with patch.object(models, 'inventory', return_value=value), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(cli.main(['models-manifest', '--manifest', str(path)]), 0)
            self.assertFalse(path.exists())

    def test_installer_restart_is_not_readiness(self):
        with patch.object(cli.os, 'name', 'nt'), patch.object(cli.subprocess, 'run', return_value=Mock(returncode=3010)):
            value = cli.bootstrap('docker', {}, True)
        self.assertTrue(value['restart_needed'])
        self.assertFalse(value['ready'])

    def test_config_rejects_credentials_and_resolves_relative_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'provision.json'
            config.write_text(json.dumps({'source': 'models'}))
            args = cli.parser().parse_args(['--config', str(config)])
            self.assertEqual(cli.options(args)['source'], config.parent / 'models')
            config.write_text(json.dumps({'password': 'synthetic-do-not-print'}))
            with self.assertRaisesRegex(ValueError, 'credentials'):
                cli.options(args)


class FreshRestoreTests(unittest.TestCase):
    def images(self):
        return {'api': {'id': 'sha256:' + 'a' * 64}, 'agent': {'id': 'sha256:' + 'b' * 64}}

    def test_default_fresh_plan_does_not_unlock_or_mutate(self):
        with patch.object(recovery, 'protection_kind', return_value='passphrase'), \
             patch.object(recovery, 'fresh_state', return_value=self.images()), \
             patch.object(recovery, 'read_archive') as unlock, patch.object(recovery.checks, 'docker') as docker:
            result = recovery.restore_fresh('synthetic.echo-backup', None, context='synthetic', api_image='api', agent_image='agent')
        self.assertFalse(result['executed'])
        unlock.assert_not_called()
        docker.assert_not_called()

    def test_occupied_host_or_wrong_daemon_refuses_before_image_or_restore(self):
        for state in ({'occupied': True, 'docker_id': 'same'}, {'occupied': False, 'docker_id': 'different'}):
            with self.subTest(state=state), patch.object(recovery.checks, 'docker', return_value='same'), \
                 patch.object(recovery.checks, 'remote_probe', return_value=state), \
                 patch.object(recovery.checks, 'image') as image:
                with self.assertRaises(ValueError):
                    recovery.fresh_state('synthetic', 'api', 'agent')
                image.assert_not_called()

    def test_fresh_execution_uses_existing_compose_and_protected_helpers(self):
        from backend import remote_host
        payload = {'bootstrap': {'api': {'wifi': {'mac': '02:00:00:00:00:01', 'key': 'private-synthetic-value'}},
                                 'synthetic': 'private-synthetic-value'}}
        commands = []
        def docker(context, *args, **kwargs):
            commands.append((args, kwargs))
            if 'inspect' in args:
                return 'synthetic-attempt'
            return ''
        with patch.object(recovery, 'protection_kind', return_value='passphrase'), \
             patch.object(recovery, 'fresh_state', return_value=self.images()), \
             patch.object(recovery, 'read_archive', return_value=payload), \
             patch.object(recovery, 'restored_bootstrap', return_value=payload['bootstrap']), \
             patch.object(recovery, '_stage') as stage, \
             patch.object(recovery.uuid, 'uuid4', return_value=Mock(hex='synthetic-attempt')), \
             patch.object(recovery.checks, 'docker', side_effect=docker), \
             patch.object(remote_host, 'install') as install, \
             patch.object(remote_host, 'manage', side_effect=[{'state': 'bootstrap_restored'}, {'state': 'ready', 'api': 'ready'}]) as manage:
            result = recovery.restore_fresh('synthetic', object(), context='synthetic', api_image='api', agent_image='agent', execute=True)
        self.assertTrue(result['services_ready'])
        stage.assert_called_once()
        install.assert_called_once()
        self.assertEqual(manage.call_args_list[0].args, ('RestoreBootstrap', payload['bootstrap']))
        compose, kwargs = commands[0]
        self.assertIn('--no-recreate', compose)
        self.assertIn('--no-build', compose)
        self.assertIn('never', compose)
        self.assertNotIn('private-synthetic-value', str(commands))
        override = json.loads(kwargs['data'])
        self.assertEqual(override['services']['api']['environment']['ECHO_VOICE_ENABLED'], '0')
        self.assertEqual(override['services']['api']['environment']['ECHO_DEPLOYMENT_MODE'], 'validation')
        self.assertEqual(override['services']['api']['environment']['ECHO_DEVICE_MAC'], '02:00:00:00:00:01')

    def test_invalid_archive_never_creates_resources(self):
        with patch.object(recovery, 'protection_kind', return_value='passphrase'), \
             patch.object(recovery, 'fresh_state', return_value=self.images()), \
             patch.object(recovery, 'read_archive', side_effect=ValueError('invalid archive')), \
             patch.object(recovery.checks, 'docker') as docker:
            with self.assertRaises(ValueError):
                recovery.restore_fresh('synthetic', object(), context='synthetic', api_image='api', agent_image='agent', execute=True)
        docker.assert_not_called()

    def test_creation_failure_does_not_stop_unowned_containers(self):
        from backend import remote_host
        payload = {'bootstrap': {'api': {}}}
        commands = []
        def docker(context, *args, **kwargs):
            commands.append(args)
            if args[0] == 'compose':
                raise RuntimeError('collision during creation')
            return 'some-other-attempt'
        with patch.object(recovery, 'protection_kind', return_value='passphrase'), \
             patch.object(recovery, 'fresh_state', return_value=self.images()), \
             patch.object(recovery, 'read_archive', return_value=payload), \
             patch.object(recovery, 'restored_bootstrap', return_value=payload['bootstrap']), \
             patch.object(recovery.checks, 'docker', side_effect=docker), \
             patch.object(remote_host, 'install') as install, patch.object(recovery, '_stage') as stage:
            with self.assertRaisesRegex(ValueError, 'Partial resources'):
                recovery.restore_fresh('synthetic', object(), context='synthetic', api_image='api', agent_image='agent', execute=True)
        install.assert_not_called()
        stage.assert_not_called()
        self.assertFalse(any(args[0] == 'stop' for args in commands))


if __name__ == '__main__':
    unittest.main()
