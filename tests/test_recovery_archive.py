"""Recovery rehearsal with generated keys, sample notes and encrypted image bytes."""
import base64
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from backend.linux_protection import LinuxProtector
from tools.recovery_archive import FILES,LIMITS,ENVELOPE,read_archive,read_photo,write_archive,validate,restored_bootstrap
from tools.recovery_restore import restore


def record(raw):
    return {'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}


class RecoveryTests(unittest.TestCase):
    def test_restored_bootstraps_use_saved_api_policy_not_stale_agent_grants(self):
        policy={'default_access':'hidden','devices':{'light.synthetic':{'access':'read','room':'Study'}}}
        self.payload['bootstrap']['agent']['home_access']={'default_access':'read','devices':{}}
        raw=json.dumps({'version':1,'protected':base64.b64encode(self.protector.encrypt(json.dumps({'policy':policy}).encode())).decode()}).encode()
        self.payload['files']['home-access.json']=record(raw)
        self.write();loaded=read_archive(self.archive,self.protector);value=restored_bootstrap(loaded)
        self.assertEqual(value['agent']['home_access'],policy)
        self.assertEqual(value['api']['home_access'],policy)
        self.assertEqual(loaded['bootstrap']['agent']['home_access']['default_access'],'read')

    def test_legacy_missing_policy_uses_archive_bootstrap_and_rejects_damaged_ciphertext(self):
        policy={'default_access':'hidden','devices':{}}
        self.payload['bootstrap']['agent']['home_access']=policy
        self.assertEqual(restored_bootstrap(self.payload)['api']['home_access'],policy)
        blob=self.protector.encrypt(json.dumps({'policy':policy}).encode())
        blob=blob[:-1]+bytes([blob[-1]^1])
        self.payload['files']['home-access.json']=record(json.dumps({'version':1,'protected':base64.b64encode(blob).decode()}).encode())
        from cryptography.exceptions import InvalidTag
        with self.assertRaises(InvalidTag):restored_bootstrap(self.payload)

    def test_personal_accounts_and_memory_survive_restore_without_live_sessions(self):
        from backend.members import Members
        from backend.display_profiles import DisplayProfile
        members=Members(self.root,self.protector)
        members.base_profile=lambda _: {'profile':DisplayProfile().model_dump(),'profile_revision':0}
        account=members.create('Synthetic member');principal=members.login('owner',account['id'],account['passcode'])
        members.memory(principal).save('Synthetic member fact')
        self.payload['files']['echo-members.json']=record(members.path.read_bytes());self.write()
        destination=self.root/'restored';destination.mkdir();restore(destination,self.stream())
        # Recovery restores files into the chosen local data directory.
        restored_root=self.root/'replacement';(restored_root/'local').mkdir(parents=True)
        (destination/'echo-members.json').replace(restored_root/'local/echo-members.json')
        loaded=Members(restored_root,self.protector);loaded.base_profile=members.base_profile
        self.assertEqual(loaded.sessions,{})
        principal=loaded.login('owner',account['id'],account['passcode'])
        self.assertEqual(loaded.memory(principal).snapshot()[0]['text'],'Synthetic member fact')

    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.key=os.urandom(32);key_path=self.root/'key';key_path.write_bytes(self.key);key_path.chmod(0o600)
        self.protector=LinuxProtector(key_path)
        self.photo_name='display-photos/'+'a'*32+'.photo'
        self.photo=self.protector.encrypt(b'private synthetic photo pixels')
        self.payload={'kind':'echo-remote','version':2,'created_at':1.0,
            'files':{'echo-household.json':record(b'{"synthetic":"household"}')},
            'photos':{self.photo_name:{'size':len(self.photo),'sha256':hashlib.sha256(self.photo).hexdigest()}},
            'bootstrap':{'api':{'storage_key':base64.b64encode(self.key).decode()},'agent':{}}}
        self.archive=self.root/'recovery.echo-backup'

    def write(self):
        write_archive(self.archive,self.payload,self.protector,lambda _:self.photo)

    def stream(self,payload=None,photo=None):
        payload=payload or self.payload
        header={'names':FILES,'limits':LIMITS,'files':payload['files'],'photos':payload.get('photos',{}),
                'storage_key':payload['bootstrap']['api']['storage_key']}
        lines=[json.dumps(header).encode()]
        for name in payload.get('photos',{}):
            lines.append(json.dumps({'name':name,'data':base64.b64encode(self.photo if photo is None else photo).decode()}).encode())
        return io.BytesIO(b'\n'.join(lines)+b'\n')

    def test_current_archive_includes_album_and_does_not_expose_data(self):
        self.write()
        self.assertEqual(read_archive(self.archive,self.protector),self.payload)
        self.assertNotIn(b'private synthetic',self.archive.read_bytes())
        self.assertNotIn(b'"household"',self.archive.read_bytes())
        encrypted=read_photo(self.archive,self.photo_name,self.payload['photos'][self.photo_name])
        self.assertEqual(self.protector.decrypt(encrypted),b'private synthetic photo pixels')
        with self.assertRaises(FileExistsError):self.write()

    def test_legacy_archives_remain_readable_and_missing_stores_are_explicit(self):
        payload=deepcopy(self.payload);payload['version']=1;payload.pop('photos')
        self.archive.write_bytes(self.protector.encrypt(json.dumps(payload).encode()))
        self.assertEqual(read_archive(self.archive,self.protector),payload)
        target=self.root/'restored';target.mkdir();album=target/'display-photos';album.mkdir()
        (album/('b'*32+'.photo')).write_bytes(self.photo)
        restore(target,self.stream(payload))
        self.assertEqual(list(album.iterdir()),[])

    def test_rejects_unlisted_compressed_and_damaged_entries(self):
        for name,raw,compression in (('../outside',b'x',zipfile.ZIP_STORED),
                                     (self.photo_name,self.photo,zipfile.ZIP_DEFLATED),
                                     (self.photo_name,b'x'*len(self.photo),zipfile.ZIP_STORED)):
            with zipfile.ZipFile(self.archive,'w') as z:
                z.writestr(ENVELOPE,self.protector.encrypt(json.dumps(self.payload).encode()))
                z.writestr(name,raw,compress_type=compression)
            with self.assertRaises(ValueError):read_archive(self.archive,self.protector)
        invalid=deepcopy(self.payload);invalid['files']['unexpected.json']=record(b'{}')
        with self.assertRaises(ValueError):validate(invalid)

    def test_changed_photo_cannot_leave_a_successful_archive(self):
        with self.assertRaises(ValueError):
            write_archive(self.archive,self.payload,self.protector,lambda _:b'changed')
        self.assertFalse(self.archive.exists())

    def test_restores_files_and_photos_and_removes_absent_snapshot_entries(self):
        target=self.root/'restored';target.mkdir()
        (target/'echo-memory.json').write_bytes(b'{"newer":"preserved in pre-restore archive"}')
        (target/'unrelated.txt').write_text('keep')
        restore(target,self.stream())
        self.assertEqual((target/'echo-household.json').read_bytes(),b'{"synthetic":"household"}')
        self.assertEqual((target/self.photo_name).read_bytes(),self.photo)
        self.assertFalse((target/'echo-memory.json').exists())
        self.assertEqual((target/'unrelated.txt').read_text(),'keep')

    def test_bad_photo_and_linked_target_do_not_modify_existing_files(self):
        target=self.root/'restored';target.mkdir();original=target/'echo-household.json';original.write_bytes(b'{}')
        with self.assertRaises(ValueError):restore(target,self.stream(photo=b'corrupt'))
        self.assertEqual(original.read_bytes(),b'{}')
        try:(target/'display-photos').symlink_to(self.root,target_is_directory=True)
        except OSError:return  # Windows may not grant symlink creation to this user.
        with self.assertRaises(ValueError):restore(target,self.stream())
        self.assertEqual(original.read_bytes(),b'{}')

    def test_commit_io_failure_rolls_back_already_changed_files(self):
        target=self.root/'restored';target.mkdir()
        for name in ('echo-displays.json','echo-memory.json'):(target/name).write_bytes(b'{"old":true}')
        payload=deepcopy(self.payload)
        for name in ('echo-displays.json','echo-memory.json'):payload['files'][name]=record(b'{"new":true}')
        replace=Path.replace
        def fail(path,destination):
            if path.name=='echo-memory.json' and path.parent.name=='new':raise PermissionError('synthetic I/O failure')
            return replace(path,destination)
        with patch.object(Path,'replace',fail),self.assertRaises(PermissionError):restore(target,self.stream(payload))
        for name in ('echo-displays.json','echo-memory.json'):self.assertEqual((target/name).read_bytes(),b'{"old":true}')
        self.assertFalse((target/'echo-household.json').exists())

    def test_restored_room_policy_survives_without_replaying_announcements(self):
        from backend.announcements import SavedAnnouncements
        saved=SavedAnnouncements.model_validate({'revision':2,'policy':{'endpoints':[
            {'id':'a'*32,'room':'Study','enabled':True,'calls_enabled':True}]},'messages':[
                {'id':'b'*32,'fingerprint':'c'*64,'sender':'d'*64,'title':'Sample','message':'A sample announcement',
                 'created':1.0,'expires':301.0,'deliveries':[{'endpoint':'a'*32,'status':'claimed'}]}]}).model_dump()
        raw=json.dumps({'version':1,'protected':base64.b64encode(self.protector.encrypt(json.dumps(saved).encode())).decode()}).encode()
        payload=deepcopy(self.payload);payload['files']['echo-announcements.json']=record(raw)
        payload['files']['echo-calendar-receipts.json']=record(b'{"synthetic":"receipt"}')
        target=self.root/'restored';target.mkdir();restore(target,self.stream(payload))
        envelope=json.loads((target/'echo-announcements.json').read_bytes())
        restored=SavedAnnouncements.model_validate(json.loads(self.protector.decrypt(base64.b64decode(envelope['protected'])))).model_dump()
        self.assertEqual(restored['policy'],saved['policy'])
        self.assertEqual(restored['messages'][0]['deliveries'][0]['status'],'unknown')
        self.assertEqual((target/'echo-calendar-receipts.json').read_bytes(),b'{"synthetic":"receipt"}')
        saved['messages'][0]['deliveries'][0]['status']='queued'
        payload['files']['echo-announcements.json']=record(json.dumps({'version':1,'protected':
            base64.b64encode(self.protector.encrypt(json.dumps(saved).encode())).decode()}).encode())
        restore(target,self.stream(payload))
        envelope=json.loads((target/'echo-announcements.json').read_bytes())
        restored=json.loads(self.protector.decrypt(base64.b64decode(envelope['protected'])))
        self.assertEqual(restored['messages'][0]['deliveries'][0]['status'],'cancelled')


if __name__=='__main__':unittest.main()
