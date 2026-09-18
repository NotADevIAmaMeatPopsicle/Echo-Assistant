import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from backend import deployment


class DeploymentTests(unittest.TestCase):
    def test_environment_overrides_ignored_host_config(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);(root/'local').mkdir()
            (root/'local/deployment.json').write_text(json.dumps({'ssh_target':'config-host'}))
            with patch.object(deployment,'ROOT',root),patch.dict('os.environ',{'ECHO_SSH_TARGET':'env-host'},clear=True):
                self.assertEqual(deployment.ssh_target(),'env-host')

    def test_ssh_and_context_reject_shell_syntax_and_options(self):
        for name,call in [('ECHO_SSH_TARGET',deployment.ssh_target),('ECHO_DOCKER_CONTEXT',deployment.docker_context)]:
            for value in ["host';exit;#",'-oProxyCommand=bad','host name','host\nname']:
                with self.subTest(name=name,value=value),patch.dict('os.environ',{name:value},clear=True):
                    with self.assertRaises(ValueError):call()

    def test_firewall_scope_requires_the_explicit_private_host(self):
        with patch.dict('os.environ',{'ECHO_DEVICE_HOST':'192.168.1.50','ECHO_LAN_SUBNET':'192.168.1.0/24'},clear=True):
            self.assertEqual(deployment.lan_subnet(),'192.168.1.0/24')
        for host,subnet in [('8.8.8.8','8.0.0.0/8'),('192.168.1.50','192.168.2.0/24'),('','')]:
            with patch.dict('os.environ',{'ECHO_DEVICE_HOST':host,'ECHO_LAN_SUBNET':subnet},clear=True):
                with self.assertRaises(ValueError):deployment.lan_subnet()
