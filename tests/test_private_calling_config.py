"""Synthetic private server export; never contact the real runtime or provider."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.calling import CallSettings
from tools.private_calling_config import main, render_config, write_new_config


ORIGIN = 'wss://calls.private.example:8443'
KEY = 'synthetic-private-key'
SECRET = 'synthetic-private-secret-' * 3


def settings(**changes):
    return CallSettings.model_validate({'revision':0, 'enabled':False, 'url':ORIGIN,
                                       'api_key':KEY, 'api_secret':SECRET, **changes})


class RenderPrivateCallingConfigTests(unittest.TestCase):
    def test_pinned_config_uses_saved_credentials_even_when_calling_is_disabled(self):
        source = settings()
        result = render_config(source, ORIGIN, '100.64.0.10')
        self.assertEqual(result, {'port':7880, 'bind_addresses':['0.0.0.0'],
            'rtc':{'tcp_port':7881, 'force_tcp':True, 'node_ip':'100.64.0.10',
                   'use_external_ip':False, 'advertise_internal_ip':False}, 'keys':{KEY:SECRET}})
        self.assertFalse(source.enabled)
        self.assertEqual(source.revision, 0)
        self.assertEqual(json.loads(json.dumps(result)), result)
        self.assertEqual(render_config(settings(enabled=True), ORIGIN, '100.127.255.254')['keys'], {KEY:SECRET})

    def test_only_literal_tailnet_ipv4_is_accepted(self):
        for node in ('100.63.255.255', '100.128.0.0', '127.0.0.1', '192.168.1.1', '::1',
                     '100.064.0.1', '100.64.0.1/10', '100.64.0.1:7881', 'node.example',
                     '100.64.0.1\n', '', None, 1681915905):
            with self.subTest(node=node), self.assertRaises(ValueError):
                render_config(settings(), ORIGIN, node)

    def test_private_origin_must_be_nonempty_canonical_and_exactly_saved(self):
        for origin in ('', None, 'http://echo-calling:7880', ORIGIN+'/', ORIGIN+'?x=y',
                       'wss://CALLS.private.example:8443', 'wss://calls.private.example:9443',
                       'wss://calls.private.example', 'wss://another.example:8443'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                render_config(settings(), origin, '100.64.0.10')
        with self.assertRaises(ValueError):
            render_config(settings(url='wss://another.example:8443'), ORIGIN, '100.64.0.10')

    def test_missing_or_invalid_saved_credentials_fail_without_echoing_them(self):
        for changes in ({'api_key':''}, {'api_secret':''}, {'api_secret':'short'}, {'url':''}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError) as error:
                render_config(settings(**changes), ORIGIN, '100.64.0.10')
            self.assertNotIn(SECRET, str(error.exception))
            self.assertNotIn(KEY, str(error.exception))

    def test_cli_refuses_non_runtime_and_plaintext_arguments_without_leaking_values(self):
        for arguments in (['--node-ip','100.64.0.10','--output','/run/echo/new.json'],
                          ['--api-secret',SECRET]):
            stdout, stderr = StringIO(), StringIO()
            with patch('tools.private_calling_config.sys.platform', 'win32'), \
                 patch('tools.private_calling_config.CallStore') as store, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(arguments), 1)
                store.assert_not_called()
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(), 'Private calling configuration was not saved.\n')

    def test_cli_reads_only_protected_store_and_prints_only_saved_boolean(self):
        stdout, stderr = StringIO(), StringIO()
        with patch('tools.private_calling_config.sys.platform', 'linux'), \
             patch('tools.private_calling_config.ROOT', Path('/opt/echo')), \
             patch.dict(os.environ, {'ECHO_CONTAINER':'1', 'ECHO_CALLING_PRIVATE_ORIGIN':ORIGIN}), \
             patch('tools.private_calling_config.os.geteuid', return_value=10000, create=True), \
             patch('tools.private_calling_config._private_directory', return_value=123), \
             patch('tools.private_calling_config.os.close'), \
             patch('pathlib.Path.is_symlink', return_value=False), \
             patch('pathlib.Path.is_file', return_value=True), \
             patch('tools.private_calling_config.CallStore') as store, \
             patch('tools.private_calling_config.LinuxProtector') as protector, \
             patch('tools.private_calling_config.write_new_config') as write, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            store.return_value.require.return_value = settings()
            self.assertEqual(main(['--node-ip','100.64.0.10','--output','/run/echo/new.json']), 0)
            store.assert_called_once_with(Path('/opt/echo'), protector.return_value)
            write.assert_called_once_with(render_config(settings(), ORIGIN, '100.64.0.10'), '/run/echo/new.json')
        self.assertEqual(stdout.getvalue(), '{"saved": true}\n')
        self.assertEqual(stderr.getvalue(), '')


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'Requires real POSIX file ownership and no-follow operations')
class PrivateCallingConfigFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root/'private'
        self.private.mkdir(mode=0o700)
        self.private.chmod(0o700)
        self.config = render_config(settings(), ORIGIN, '100.64.0.10')

    def test_new_private_file_and_overwrite_refusal(self):
        target = self.private/'provider.json'
        write_new_config(self.config, target, private_dir=self.private)
        self.assertEqual(json.loads(target.read_text()), self.config)
        info = target.stat()
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        self.assertEqual(info.st_uid, os.geteuid())
        self.assertEqual(info.st_nlink, 1)
        original = target.read_bytes()
        with self.assertRaises(FileExistsError):
            write_new_config({'keys':{}}, target, private_dir=self.private)
        self.assertEqual(target.read_bytes(), original)

    def test_target_symlink_and_directory_links_cannot_escape(self):
        outside = self.root/'outside.json'
        outside.write_text('preserve')
        target = self.private/'linked.json'
        target.symlink_to(outside)
        with self.assertRaises(OSError):
            write_new_config(self.config, target, private_dir=self.private)
        self.assertEqual(outside.read_text(), 'preserve')
        self.assertTrue(target.is_symlink())
        alias = self.root/'alias'
        alias.symlink_to(self.private, target_is_directory=True)
        with self.assertRaises(OSError):
            write_new_config(self.config, alias/'new.json', private_dir=alias)
        ancestor = self.root/'parent-alias'
        ancestor.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            write_new_config(self.config, ancestor/'private/new.json', private_dir=ancestor/'private')
        self.assertFalse((self.private/'new.json').exists())

    def test_nonprivate_directory_and_wrong_owner_are_rejected(self):
        self.private.chmod(0o750)
        with self.assertRaises(ValueError):
            write_new_config(self.config, self.private/'new.json', private_dir=self.private)
        self.private.chmod(0o700)
        with patch('tools.private_calling_config.os.geteuid', return_value=os.geteuid()+1), self.assertRaises(ValueError):
            write_new_config(self.config, self.private/'new.json', private_dir=self.private)
        self.assertFalse((self.private/'new.json').exists())

    def test_traversal_nested_and_arbitrary_output_locations_are_rejected(self):
        for target in (self.root/'outside.json', self.private/'../escape.json',
                       self.private/'nested/new.json', self.private/'hidden.txt', self.private/'.hidden.json'):
            with self.subTest(name=target.name), self.assertRaises(ValueError):
                write_new_config(self.config, target, private_dir=self.private)
        self.assertEqual(list(self.private.iterdir()), [])

    def test_partial_write_failure_removes_only_new_file(self):
        target = self.private/'new.json'
        with patch('tools.private_calling_config.os.fsync', side_effect=OSError('synthetic')), self.assertRaises(OSError):
            write_new_config(self.config, target, private_dir=self.private)
        self.assertFalse(target.exists())
        existing = self.private/'existing.json'
        existing.write_text('preserve')
        with self.assertRaises(FileExistsError):
            write_new_config(self.config, existing, private_dir=self.private)
        self.assertEqual(existing.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
