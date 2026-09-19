import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.display_auth import Displays,DisplayStorageUnavailable,allowed
from backend.linux_protection import LinuxProtector
from backend.settings import SettingsStore


class DisplayAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name); key=self.root/'key'; key.write_bytes(os.urandom(32)); key.chmod(0o600)
        self.protector=LinuxProtector(key); self.now=1000
        self.displays=Displays(self.root,self.protector,lambda:self.now)

    def test_enrollment_persists_only_hashes_and_survives_restart(self):
        code=self.displays.pairing('Kitchen')['code']
        paired=self.displays.enroll(code); header='Display '+paired['credential']
        self.assertEqual(self.displays.credential(header),paired['id'])
        raw=self.displays.path.read_bytes()
        self.assertNotIn(paired['credential'].encode(),raw); self.assertNotIn(code.encode(),raw)
        self.assertNotIn('hash',self.displays.snapshot()[0])
        with self.assertRaises(HTTPException):self.displays.enroll(code)
        restarted=Displays(self.root,self.protector,lambda:self.now)
        self.assertEqual(restarted.credential(header),paired['id'])
        restarted.revoke(paired['id'])
        with self.assertRaises(HTTPException):restarted.credential(header)

    def test_expiry_and_failed_save_do_not_consume_enrollment(self):
        code=self.displays.pairing('Study')['code']; self.now+=301
        with self.assertRaises(HTTPException):self.displays.enroll(code)
        code=self.displays.pairing('Study')['code']
        with patch.object(Path,'replace',side_effect=PermissionError):
            with self.assertRaises(DisplayStorageUnavailable):self.displays.enroll(code)
        self.assertEqual(self.displays.snapshot(),[])
        self.assertEqual(self.displays.enroll(code)['name'],'Study')

    def test_scopes_deny_settings_master_credentials_and_enrollment(self):
        for method,path in [('GET','/v1/settings'),('POST','/v1/ui/ticket'),('POST','/v1/displays/pairing'),
                            ('POST','/internal/home/action'),('PUT','/v1/home/access'),('POST','/v1/text')]:
            self.assertFalse(allowed(method,path))
        self.assertTrue(allowed('POST','/v1/chat')); self.assertTrue(allowed('GET','/v1/schedules'))

    def test_real_api_pairing_session_and_immediate_revocation(self):
        settings=SettingsStore(protector=self.protector)
        with TestClient(create_app('test-owner-'*4,settings_store=settings)) as client:
            self.assertEqual(client.post('/v1/displays/pairing',json={'name':'Desk'}).status_code,401)
            owner={'Authorization':'Bearer '+'test-owner-'*4}
            code=client.post('/v1/displays/pairing',json={'name':'Desk'},headers=owner).json()['code']
            paired=client.post('/v1/displays/enroll',json={'code':code}).json()
            headers={'Authorization':'Display '+paired['credential'],'X-Echo-Request':'1'}
            self.assertEqual(client.get('/v1/state',headers=headers).status_code,200)
            self.assertEqual(client.get('/v1/settings',headers=headers).status_code,403)
            self.assertEqual(client.post('/v1/displays/pairing',json={'name':'Unauthorized'},headers=headers).status_code,403)
            response=client.post('/v1/displays/session',headers=headers)
            self.assertEqual(response.status_code,200); self.assertIn('HttpOnly',response.headers['set-cookie'])
            self.assertEqual(client.get('/v1/display/session').json()['role'],'display')
            self.assertEqual(client.post('/v1/household',json={'revision':0,'kind':'notes','text':'Cross-origin'},headers={'X-Echo-Request':'1','Origin':'https://untrusted.example'}).status_code,403)
            client.delete('/v1/displays/'+paired['id'],headers=owner)
            self.assertEqual(client.get('/v1/state',headers=headers).status_code,401)
            self.assertEqual(client.get('/v1/state').status_code,401)


if __name__=='__main__':unittest.main()
