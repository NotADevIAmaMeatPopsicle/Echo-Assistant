import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from backend import deployment


class DeploymentTests(unittest.TestCase):
    def test_private_calling_binding_is_explicit_and_canonical(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);(root/'local').mkdir()
            (root/'local/deployment.json').write_text(json.dumps({'calling_private_origin':'wss://calls.example.com:8443'}))
            with patch.object(deployment,'ROOT',root),patch.dict('os.environ',{},clear=True):
                self.assertEqual(deployment.calling_private_origin(),'wss://calls.example.com:8443')
            with patch.object(deployment,'ROOT',root),patch.dict('os.environ',{'ECHO_CALLING_PRIVATE_ORIGIN':''},clear=True):
                self.assertEqual(deployment.calling_private_origin(),'')
            with patch.object(deployment,'ROOT',root),patch.dict('os.environ',{'ECHO_CALLING_PRIVATE_ORIGIN':'http://echo-calling:7880'},clear=True):
                with self.assertRaises(ValueError):deployment.calling_private_origin()

    def test_managed_calling_survives_normal_api_start_and_stop(self):
        from tools import remote_device
        origin='wss://calls.example.com:8443'
        with patch.object(deployment,'device_host',return_value='192.168.1.50'), \
             patch.object(deployment,'docker_context',return_value='example'), \
             patch.object(deployment,'calling_private_origin',return_value=origin), \
             patch.object(remote_device.subprocess,'run') as run:
            remote_device.compose('api','up','-d','--no-build')
            args=run.call_args.args[0]
            self.assertIn(str(remote_device.ROOT/'deploy/host/calling.yaml'),args)
            self.assertEqual(run.call_args.kwargs['env']['ECHO_CALLING_PRIVATE_ORIGIN'],origin)
            self.assertEqual(args[-1],'api')
            remote_device.compose('api','stop')
            self.assertEqual(run.call_args.args[0][-2:],['api','calling'])
        with patch.object(deployment,'device_host',return_value='192.168.1.50'), \
             patch.object(deployment,'docker_context',return_value='example'), \
             patch.object(deployment,'calling_private_origin',return_value=''), \
             patch.object(remote_device.subprocess,'run') as run:
            remote_device.compose('api','up','-d','--no-build')
            self.assertNotIn(str(remote_device.ROOT/'deploy/host/calling.yaml'),run.call_args.args[0])

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
