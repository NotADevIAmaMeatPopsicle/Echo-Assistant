from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.photos import Photos,PhotoUnavailable
from backend.linux_protection import LinuxProtector
from backend.settings import SettingsStore


class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        key=self.root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600);self.protector=LinuxProtector(key)
        image=Image.new('RGB',(50,30),'navy');exif=Image.Exif();exif[270]='Private original description'
        buffer=BytesIO();image.save(buffer,'JPEG',exif=exif);self.raw=buffer.getvalue()

    def test_pixels_survive_but_original_metadata_does_not(self):
        photos=Photos(self.root,self.protector);added=photos.add(self.raw)
        saved=photos.directory/(added['id']+'.photo');self.assertNotIn(b'JFIF',saved.read_bytes())
        restored=Photos(self.root,self.protector);self.assertEqual(restored.snapshot()['items'][0]['id'],added['id'])
        image=Image.open(BytesIO(restored.read(added['id'])))
        self.assertEqual(image.size,(50,30));self.assertEqual(dict(image.getexif()),{})
        self.assertNotIn(b'Private original',restored.read(added['id']))
        self.assertTrue(restored.add(self.raw)['existing']);self.assertEqual(len(restored.entries()),1)
        with self.assertRaises(ValueError):photos.add(b'<svg/>')
        with self.assertRaises(KeyError):photos.read('../config')
        saved.write_bytes(b'broken')
        with self.assertRaises(PhotoUnavailable):restored.read(added['id'])
        self.assertEqual(saved.read_bytes(),b'broken')

    def test_failed_write_and_quota_do_not_change_album(self):
        photos=Photos(self.root,self.protector)
        with patch.object(Path,'replace',side_effect=PermissionError):
            with self.assertRaises(PhotoUnavailable):photos.add(self.raw)
        self.assertEqual(photos.entries(),[])
        photos.maximum=0
        with self.assertRaises(ValueError):photos.add(self.raw)

    def test_only_owner_uploads_and_removes_paired_displays_can_view(self):
        with TestClient(create_app('synthetic-owner-token-'*3,settings_store=SettingsStore(protector=self.protector))) as client:
            self.assertEqual(client.get('/v1/display/photos').status_code,401)
            client.headers['Authorization']='Bearer '+'synthetic-owner-token-'*3
            code=client.post('/v1/displays/pairing',json={'name':'Demo'}).json()['code']
            credential=client.post('/v1/displays/enroll',json={'code':code}).json()['credential']
            result=client.post('/v1/display/photos',content=self.raw,headers={'Content-Type':'image/jpeg'})
            self.assertEqual(result.status_code,200);identifier=result.json()['id']
            client.headers['Authorization']='Display '+credential
            self.assertEqual(client.get('/v1/display/photos/'+identifier).status_code,200)
            self.assertEqual(client.post('/v1/display/photos',content=self.raw,headers={'Content-Type':'image/jpeg'}).status_code,403)
            self.assertEqual(client.delete('/v1/display/photos/'+identifier).status_code,403)
            client.headers['Authorization']='Bearer '+'synthetic-owner-token-'*3
            self.assertEqual(client.delete('/v1/display/photos/'+identifier).status_code,200)
            self.assertEqual(client.get('/v1/display/photos/'+identifier).status_code,404)
