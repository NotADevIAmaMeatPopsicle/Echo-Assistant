import base64
import subprocess
import unittest
from unittest.mock import patch
from backend.remote_host import _powershell


class RemoteTransportTests(unittest.TestCase):
    def test_long_script_and_payload_stay_off_the_command_line_and_separate(self):
        script='Write-Output "hello"\n'+'# context\n'*2000
        payload=b'{"synthetic_key":"not-a-real-secret"}'
        with patch('backend.remote_host.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'hello\r\n')) as run:
            self.assertEqual(_powershell(script,payload),'hello')
        command=run.call_args.args[0];stdin=run.call_args.kwargs['input']
        self.assertLess(len(' '.join(command)),2000)
        self.assertNotIn('not-a-real-secret',' '.join(command))
        first,remaining=stdin.split(b'\n',1)
        self.assertEqual(base64.b64decode(first).decode(),script)
        self.assertEqual(remaining,payload)


if __name__=='__main__':unittest.main()
