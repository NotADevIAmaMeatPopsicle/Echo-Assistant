"""Storage and API boundaries for the large display. No audio or home devices."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.household import HouseholdStore, HouseholdConflict, HouseholdUnavailable
from backend.linux_protection import LinuxProtector
from backend.settings import SettingsStore
from deploy.pi.kiosk import validate_url, x11_geometry, dedicated_x11_flags


class SmartDisplayTests(unittest.TestCase):
    def test_dedicated_kiosk_uses_active_primary_bounds(self):
        listing = ('Screen 0: current 2944 x 1080\n'
                   'HDMI-1 connected primary 1024x600+1920+0 (normal)\n'
                   '   1920x1200 60.00\n'
                   'HDMI-2 connected 1920x1080+0+0 (normal)\n')
        self.assertEqual(x11_geometry(listing), ['--window-size=1024,600','--window-position=1920,0'])
        self.assertEqual(x11_geometry(listing.replace('primary ', '')), [])
        self.assertEqual(x11_geometry('HDMI-1 disconnected\n'), [])
        with patch.dict(os.environ, {'ECHO_DEDICATED_X11':'0','DISPLAY':':0'}), patch('deploy.pi.kiosk.subprocess.run') as run:
            self.assertEqual(dedicated_x11_flags(), [])
            run.assert_not_called()

    def test_kiosk_rejects_credentials_and_insecure_remote_urls(self):
        for url in ('https://echo.example/display','http://127.0.0.1:8768/display','http://[::1]:8768/display'):
            self.assertEqual(validate_url(url),url)
        for url in ('http://echo.example/display','file:///display','https://name:secret@echo.example/display',
                    'https://echo.example/display?token=secret','https://echo.example/display#ticket=secret'):
            with self.assertRaises(ValueError): validate_url(url)

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        key = self.root/'test-key'
        key.write_bytes(os.urandom(32)); key.chmod(0o600)
        self.protector = LinuxProtector(key)

    def test_encrypted_round_trip_conflict_edit_delete(self):
        store = HouseholdStore(self.root,self.protector)
        state = store.change(0,kind='shopping',text='Synthetic jasmine tea')
        identifier = state['items'][0]['id']
        self.assertNotIn(b'jasmine',store.path.read_bytes())
        restored = HouseholdStore(self.root,self.protector)
        self.assertEqual(restored.snapshot(),state)
        with self.assertRaises(HouseholdConflict): restored.change(0,kind='notes',text='Stale edit')
        self.assertEqual(restored.change(1,identifier=identifier,done=True)['items'][0]['done'],True)
        self.assertEqual(restored.change(2,identifier=identifier,delete=True)['items'],[])
        self.assertEqual(HouseholdStore(self.root,self.protector).snapshot()['revision'],3)

    def test_write_failure_and_damaged_data_preserve_previous_state(self):
        store = HouseholdStore(self.root,self.protector)
        original = store.change(0,kind='notes',text='Keep this note')
        saved = store.path.read_bytes()
        with patch.object(Path,'replace',side_effect=PermissionError):
            with self.assertRaises(HouseholdUnavailable): store.change(1,kind='notes',text='Failed write')
        self.assertEqual(store.path.read_bytes(),saved)
        self.assertEqual(store.snapshot(),original)
        store.path.write_text('{"version":2,"protected":"broken"}')
        damaged = HouseholdStore(self.root,self.protector)
        with self.assertRaises(HouseholdUnavailable): damaged.change(0,kind='notes',text='Do not replace')
        self.assertIn('broken',store.path.read_text())

    def test_list_reordering_preserves_other_categories_and_rejects_stale_edit(self):
        store=HouseholdStore(self.root,self.protector)
        store.change(0,kind='shopping',text='Tea')
        store.change(1,kind='notes',text='Keep the note here')
        state=store.change(2,kind='shopping',text='Coffee')
        coffee=state['items'][2]['id']
        moved=store.change(3,identifier=coffee,position=0)
        self.assertEqual([i['text'] for i in moved['items']],['Coffee','Keep the note here','Tea'])
        with self.assertRaises(HouseholdConflict):store.change(3,identifier=coffee,text='Stale coffee')
        self.assertEqual(HouseholdStore(self.root,self.protector).snapshot(),moved)

    def client(self):
        settings = SettingsStore(protector=self.protector)
        return TestClient(create_app('synthetic-test-token-'*3,settings_store=settings))

    def test_authenticated_api_and_validation(self):
        with self.client() as client:
            item = {'revision':0,'kind':'shopping','text':'Demo coffee'}
            self.assertEqual(client.get('/v1/household').status_code,401)
            self.assertEqual(client.post('/v1/household',json=item).status_code,401)
            client.headers['Authorization'] = 'Bearer '+'synthetic-test-token-'*3
            for bad in ({**item,'revision':True},{**item,'kind':'passwords'},{**item,'text':' '},{**item,'text':'a'*501},{**item,'text':'bad\x00value'}):
                self.assertEqual(client.post('/v1/household',json=bad).status_code,422)
            response = client.post('/v1/household',json=item)
            self.assertEqual(response.status_code,200)
            identifier = response.json()['items'][0]['id']
            self.assertEqual(client.post('/v1/household',json=item).status_code,409)
            self.assertEqual(client.patch('/v1/household/'+identifier,json={'revision':1,'done':True}).status_code,200)
            self.assertEqual(client.request('DELETE','/v1/household/'+identifier,json={'revision':2}).status_code,200)
            self.assertEqual(client.get('/v1/household').json()['items'],[])

    def test_schedule_and_household_commands_reach_real_app(self):
        with self.client() as client:
            self.assertEqual(client.get('/v1/schedules').status_code,401)
            client.headers['Authorization']='Bearer '+'synthetic-test-token-'*3
            spec={'title':'Synthetic morning','time':'07:30','timezone':'UTC','weekdays':[0,1,2,3,4]}
            created=client.post('/v1/schedules',json={'revision':0,'schedule':spec})
            self.assertEqual(created.status_code,200)
            self.assertEqual(client.get('/v1/schedules').json()['items'][0]['title'],spec['title'])
            reply=client.post('/v1/chat',json={'text':'Add oats to my shopping list'})
            self.assertEqual(reply.status_code,200)
            self.assertEqual(reply.json()['capability'],'household')
            self.assertEqual(client.get('/v1/household').json()['items'][0]['text'],'oats')
            self.assertEqual(client.post('/v1/text',json={'text':'Show my shopping list'}).json()['capability'],'household')

    def test_browser_session_origin_and_display_assets(self):
        with self.client() as client:
            response = client.get('/display')
            self.assertEqual(response.status_code,200)
            self.assertIn('blob:',response.headers['content-security-policy'])
            self.assertNotIn('blob:',client.get('/').headers['content-security-policy'])
            for asset in ('display.js','display.css'):
                self.assertEqual(client.get('/assets/display/'+asset).status_code,200)
            ticket = client.post('/v1/ui/ticket',headers={'Authorization':'Bearer '+'synthetic-test-token-'*3}).json()['ticket']
            login = client.post('/v1/ui/session',json={'ticket':ticket},headers={'Origin':'http://testserver','X-Echo-Request':'1'})
            self.assertEqual(login.status_code,200)
            self.assertIn('HttpOnly',login.headers['set-cookie'])
            body = {'revision':0,'kind':'notes','text':'Same origin only'}
            self.assertEqual(client.post('/v1/household',json=body,headers={'Origin':'https://untrusted.example','X-Echo-Request':'1'}).status_code,403)
            self.assertEqual(client.post('/v1/household',json=body,headers={'Origin':'http://testserver'}).status_code,403)
            self.assertEqual(client.post('/v1/household',json=body,headers={'Origin':'http://testserver','X-Echo-Request':'1'}).status_code,200)


if __name__ == '__main__': unittest.main()
