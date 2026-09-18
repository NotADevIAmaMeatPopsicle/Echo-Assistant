import json
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from backend.agent_runtime import configuration_fingerprint
from backend.host_migration import apply_migration
from backend.linux_protection import LinuxProtector
from backend.memory import MemoryStore,MemoryUnavailable
from backend.settings import EchoSettings,SettingsStore,SettingsUpdate


class MigrationTests(unittest.TestCase):
    def bundle(self):
        settings=EchoSettings(provider='azure',agent_runtime='hermes',model='synthetic',
            azure_url='https://synthetic.openai.azure.com',tts_engine='pocket',tts_voice='george')
        keys={'azure':'synthetic-azure-key','anthropic':'synthetic-other-key'}
        return {'id':'a'*32,'settings':settings.model_dump(),'keys':keys,
            'memory':[{'id':'b'*32,'text':'Synthetic tea preference','created_at':10,'updated_at':20}],
            'home_access':{'default_access':'read','devices':{}},'timers':[],
            'agent':{'url':'http://agent:8642','token':'t'*40,'configuration':configuration_fingerprint(settings,keys)},
            'spotify':{'username':'synthetic-account','auth_type':1,'auth_data':'synthetic-spotify-key'}}

    def protector(self,root):
        path=root/'key';path.write_bytes(secrets.token_bytes(32));path.chmod(0o600)
        return LinuxProtector(path)

    def test_transfer_preserves_keys_memories_and_does_not_reapply_after_updates(self):
        with TemporaryDirectory() as folder,patch.dict('os.environ',{'ECHO_CONTAINER':'1'}):
            root=Path(folder);protector=self.protector(root);bundle=self.bundle()
            result=apply_migration(root,bundle,protector)
            self.assertEqual(result['provider_key_count'],2)
            self.assertEqual(SettingsStore(root,protector).snapshot()[1],bundle['keys'])
            self.assertEqual(MemoryStore(root,protector).snapshot(),bundle['memory'])
            for path in (root/'local').glob('*.json'):
                data=path.read_bytes()
                for secret in ('synthetic-azure-key','synthetic-other-key','Synthetic tea preference','synthetic-spotify-key'):
                    self.assertNotIn(secret.encode(),data)
            MemoryStore(root,protector).save('Added after the transfer')
            self.assertEqual(apply_migration(root,bundle,protector),result)
            self.assertEqual(len(MemoryStore(root,protector).snapshot()),2)
            with self.assertRaises(ValueError):apply_migration(root,{**bundle,'id':'c'*32},protector)

    def test_invalid_transfer_preserves_existing_files_before_any_replacement(self):
        with TemporaryDirectory() as folder,patch.dict('os.environ',{'ECHO_CONTAINER':'1'}):
            root=Path(folder);protector=self.protector(root)
            SettingsStore(root,protector).save(SettingsUpdate(settings=EchoSettings()))
            path=root/'local/echo-settings.json';original=path.read_bytes()
            bundle=self.bundle();bundle['memory']=[{'bad':'record'}]
            with self.assertRaises(MemoryUnavailable):apply_migration(root,bundle,protector)
            self.assertEqual(path.read_bytes(),original)
            self.assertFalse((root/'local/host-migration.json').exists())


if __name__=='__main__':unittest.main()
