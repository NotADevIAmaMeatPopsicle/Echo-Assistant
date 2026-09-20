"""Calendar/camera permission boundaries using synthetic Home Assistant responses."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.experiences import Experiences, SourceStore, ExperienceConflict, ExperienceUnavailable
from backend.home import HomeBridge, HomeConfig, HomeUnavailable
from backend.linux_protection import LinuxProtector
from backend.settings import SettingsStore


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        key=self.root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600);self.protector=LinuxProtector(key)
        self.requests=[];self.extra=None
        def respond(request):
            self.requests.append(request)
            if self.extra:
                response=self.extra(request)
                if response is not None:return response
            if request.url.path=='/api/states':return httpx.Response(200,json=[
                {'entity_id':'calendar.demo','state':'off','attributes':{'friendly_name':'Demo agenda'}},
                {'entity_id':'binary_sensor.study','state':'on','attributes':{'device_class':'occupancy','friendly_name':'Study'}},
                {'entity_id':'camera.porch','state':'idle','attributes':{'friendly_name':'Porch','access_token':'never-export'}},
                {'entity_id':'camera.private','state':'idle','attributes':{'friendly_name':'Private camera'}}])
            if request.url.path=='/api/calendars/calendar.demo':return httpx.Response(200,json=[
                {'summary':'All-day sample','start':{'date':'2026-09-19'},'end':{'date':'2026-09-20'}},
                {'summary':'DST sample','start':{'dateTime':'2026-11-01T01:30:00-04:00'},'end':{'dateTime':'2026-11-01T01:45:00-04:00'}},
                {'summary':'Naive date rejected','start':{'dateTime':'2026-09-19T10:00:00'},'end':{'dateTime':'2026-09-19T11:00:00'}}])
            if request.url.path=='/api/camera_proxy/camera.porch':return httpx.Response(200,content=b'\xff\xd8\xffsynthetic',headers={'Content-Type':'image/jpeg'})
            return httpx.Response(404)
        self.home=HomeBridge(HomeConfig(True,'http://127.0.0.1:8123','synthetic-token',{'weather':'weather.demo'}),httpx.MockTransport(respond))
        self.store=SourceStore(self.root,self.protector);self.features=Experiences(self.home,self.store)

    def select(self):return self.features.save_sources({'calendars':['calendar.demo'],'cameras':['camera.porch']},0)

    def test_selected_only_and_credential_stays_on_server(self):
        self.assertEqual(self.features.sources()['status'],'not_selected');self.assertEqual(self.requests,[])
        with self.assertRaises(PermissionError):self.features.camera('camera.porch')
        self.select();sources=self.features.sources()
        self.assertNotIn('private',str(sources));self.assertNotIn('never-export',str(sources))
        agenda=self.features.agenda('2026-09-19',7)
        self.assertEqual(len(agenda['events']),2);self.assertTrue(agenda['events'][0]['all_day'])
        self.assertTrue(agenda['events'][1]['start'].endswith('-04:00'))
        image,mime=self.features.camera('camera.porch');self.assertEqual(mime,'image/jpeg')
        self.assertTrue(image.startswith(b'\xff\xd8\xff'))
        self.assertTrue(all(r.headers['authorization']=='Bearer synthetic-token' for r in self.requests))
        self.assertTrue(all('synthetic-token' not in str(r.url) for r in self.requests))
        self.assertFalse(any('camera.private' in str(r.url) for r in self.requests))
        with self.assertRaises(ValueError):self.features.agenda('not-a-date')

    def test_encrypted_atomic_selection_stale_edit_and_corrupt_file(self):
        first=self.select();raw=self.store.path.read_bytes();self.assertNotIn(b'calendar.demo',raw)
        restored=SourceStore(self.root,self.protector);self.assertEqual(restored.snapshot(),first)
        with self.assertRaises(ExperienceConflict):restored.save({},0)
        with patch.object(Path,'replace',side_effect=PermissionError):
            with self.assertRaises(ExperienceUnavailable):restored.save({},1)
        self.assertEqual(restored.snapshot(),first);self.assertEqual(self.store.path.read_bytes(),raw)
        self.store.path.write_text('broken')
        with self.assertRaises(ExperienceUnavailable):SourceStore(self.root,self.protector).save({},0)
        self.assertEqual(self.store.path.read_text(),'broken')

    def test_camera_redirect_type_size_and_revocation(self):
        self.select()
        for response in (httpx.Response(302,headers={'Location':'https://untrusted.example/'}),
                         httpx.Response(200,content=b'<svg/>',headers={'Content-Type':'image/svg+xml'}),
                         httpx.Response(200,content=b'\xff\xd8\xff'+b'x'*5_000_000,headers={'Content-Type':'image/jpeg'})):
            self.extra=lambda request,r=response:r
            before=len(self.requests)
            with self.assertRaises(HomeUnavailable):self.features.camera('camera.porch')
            self.assertEqual(len(self.requests),before+1)
        def revoke(request):
            self.store.save({},1)
            return httpx.Response(200,content=b'\xff\xd8\xffsynthetic',headers={'Content-Type':'image/jpeg'})
        self.extra=revoke
        with self.assertRaises(PermissionError):self.features.camera('camera.porch')

    def test_api_owner_selection_display_reads_and_removal(self):
        settings=SettingsStore(protector=self.protector)
        with TestClient(create_app('synthetic-owner-token-'*3,home=self.home,settings_store=settings)) as client:
            self.assertEqual(client.get('/v1/display/sources').status_code,401)
            client.headers['Authorization']='Bearer '+'synthetic-owner-token-'*3
            code=client.post('/v1/displays/pairing',json={'name':'Demo display'}).json()['code']
            credential=client.post('/v1/displays/enroll',json={'code':code}).json()['credential']
            selection={'revision':0,'sources':{'calendars':['calendar.demo'],'cameras':['camera.porch'],'presence_sensors':['binary_sensor.study']}}
            self.assertEqual(client.put('/v1/display/source-settings',json=selection).status_code,200)
            client.headers['Authorization']='Display '+credential
            self.assertEqual(client.get('/v1/display/source-settings').status_code,403)
            self.assertEqual(client.put('/v1/display/source-settings',json=selection).status_code,403)
            presence=client.get('/v1/display/presence')
            self.assertEqual(presence.status_code,200)
            self.assertTrue(presence.json()['items'][0]['occupied'])
            self.assertEqual(presence.headers['cache-control'],'no-store')
            self.assertEqual(client.get('/v1/display/agenda?start=2026-09-19').status_code,200)
            self.assertEqual(client.get('/v1/display/cameras/camera.porch/snapshot').status_code,200)
            self.assertEqual(client.get('/v1/display/cameras/camera.private/snapshot').status_code,403)
            self.assertEqual(client.get('/v1/display/cameras/camera.porch/snapshot').headers['cache-control'],'no-store')
            from tests.test_camera_stream import part
            self.extra=lambda request:httpx.Response(200,content=part()+b'--sample--\r\n',headers={'Content-Type':'multipart/x-mixed-replace; boundary=sample'}) if request.url.path.endswith('/camera.porch') else None
            streamed=client.get('/v1/display/cameras/camera.porch/stream')
            self.assertEqual(streamed.status_code,200);self.assertIn(b'--echo-frame',streamed.content)
            self.assertEqual(streamed.headers['cache-control'],'no-store')
            self.assertEqual(client.get('/v1/display/cameras/camera.private/stream').status_code,403)
            self.assertEqual(client.get('/v1/display/doorbells').json()['events'],[])
            self.extra=None
            client.headers['Authorization']='Bearer '+'synthetic-owner-token-'*3
            self.assertEqual(client.put('/v1/display/source-settings',json={'revision':1,'sources':{}}).status_code,200)
            client.headers['Authorization']='Display '+credential
            self.assertEqual(client.get('/v1/display/cameras/camera.porch/snapshot').status_code,403)
            self.assertEqual(client.get('/v1/display/presence').json()['items'],[])


if __name__=='__main__':unittest.main()
