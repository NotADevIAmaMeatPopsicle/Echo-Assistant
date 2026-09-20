"""Paired player relay tests with an in-memory upstream, never a real speaker."""
import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from backend.app import create_app
from backend.display_profiles import DisplayProfile
from backend.group_stream import player_message
from backend.linux_protection import LinuxProtector
from backend.settings import SettingsStore

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from grouped import worker_volume


class FakeRemote:
    def __init__(self):self.sent=[]
    async def __aenter__(self):self.queue=asyncio.Queue();return self
    async def __aexit__(self,*_):pass
    async def send(self,value):
        parsed=json.loads(value);self.sent.append(parsed)
        if parsed['type']=='auth':await self.queue.put(json.dumps({'type':'auth_ok'}))
        elif parsed['type']=='client/hello':await self.queue.put(json.dumps({'type':'server/hello','payload':{'sample':True}}))
    async def recv(self):return await self.queue.get()
    def __aiter__(self):return self
    async def __anext__(self):return await self.recv()


class GroupStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name)
        key=root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
        self.app=create_app('owner-token-'*4,settings_store=SettingsStore(protector=LinuxProtector(key)))
        self.client=TestClient(self.app);self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.owner={'Authorization':'Bearer '+'owner-token-'*4}
        code=self.client.post('/v1/displays/pairing',headers=self.owner,json={'name':'Demo display'}).json()['code']
        self.paired=self.client.post('/v1/displays/enroll',json={'code':code}).json()
        self.header={'Authorization':'Display '+self.paired['credential']}
        config={'enabled':True,'url':'http://echo-music:8095','receivers':[self.paired['id']]}
        self.app.state.group_music.configure(config,'server-only-secret',0)
        self.remotes=[]
        def connector(url,**kwargs):
            self.assertEqual(url,'ws://echo-music:8095/sendspin');self.assertIsNone(kwargs['proxy'])
            remote=FakeRemote();self.remotes.append(remote);return remote
        self.app.state.group_streams.connector=connector
        self.path='/v1/music/groups/stream'
        self.hello={'type':'client/hello','payload':{'client_id':'echo-'+self.paired['id'],'name':'Sample player','version':1,
            'supported_roles':['player@v1'],'player@v1_support':{'supported_formats':[]}}}

    def test_authorized_stream_keeps_server_token_off_client(self):
        with self.client.websocket_connect(self.path,headers=self.header) as ws:
            ws.send_json(self.hello);value=ws.receive_json()
            self.assertEqual(value['type'],'server/hello');self.assertNotIn('server-only-secret',json.dumps(value))
            self.assertEqual(self.remotes[0].sent[0],{'type':'auth','token':'server-only-secret','client_id':'echo-'+self.paired['id']})
            ws.send_json({'type':'client/command','payload':{'controller':{'command':'play'}}})
            with self.assertRaises(WebSocketDisconnect):ws.receive_json()
        self.assertEqual(len(self.remotes[0].sent),2)

    def test_unpaired_owner_and_unapproved_receiver_are_denied(self):
        for header in ({},self.owner):
            with self.assertRaises(WebSocketDisconnect),self.client.websocket_connect(self.path,headers=header):pass
        self.app.state.group_music.configure({'enabled':True,'url':'http://echo-music:8095'},None,1)
        with self.assertRaises(WebSocketDisconnect),self.client.websocket_connect(self.path,headers=self.header):pass
        self.assertEqual(self.remotes,[])

    def test_identity_spoof_and_uploaded_binary_are_rejected(self):
        with self.client.websocket_connect(self.path,headers=self.header) as ws:
            self.hello['payload']['client_id']='echo-'+'f'*32;ws.send_json(self.hello)
            with self.assertRaises(WebSocketDisconnect):ws.receive_json()
        self.assertEqual(self.remotes,[])
        with self.client.websocket_connect(self.path,headers=self.header) as ws:
            ws.send_bytes(b'not a player hello')
            with self.assertRaises(WebSocketDisconnect):ws.receive_json()

    def test_duplicate_cannot_release_existing_receiver_and_guest_change_revokes(self):
        with self.client.websocket_connect(self.path,headers=self.header) as ws:
            ws.send_json(self.hello);ws.receive_json()
            with self.assertRaises(WebSocketDisconnect),self.client.websocket_connect(self.path,headers=self.header):pass
            self.assertIn(self.paired['id'],self.app.state.group_streams.active)
            r=self.client.put('/v1/displays/'+self.paired['id']+'/profile',headers=self.owner,
                json={'revision':0,'profile':DisplayProfile(mode='guest').model_dump()})
            self.assertEqual(r.status_code,200)
            with self.assertRaises(WebSocketDisconnect):ws.receive_json()

    def test_configuration_rejects_unknown_receiver_and_protocol_roles(self):
        r=self.client.put('/v1/music/groups/settings',headers=self.owner,json={'revision':1,'config':{
            'enabled':True,'url':'http://echo-music:8095','receivers':['a'*32]}})
        self.assertEqual(r.status_code,422)
        self.hello['payload']['supported_roles'].append('controller@v1')
        with self.assertRaises(ValueError):player_message(json.dumps(self.hello),'echo-'+self.paired['id'],hello=True)
        with self.assertRaises(ValueError):player_message('x'*17000,'echo-'+self.paired['id'])

    def test_native_attenuation_matches_echo_volume_and_eighty_percent_duck(self):
        for volume in (0,2,15,30):
            normal=(worker_volume(volume,1)/100)**1.5
            ducked=(worker_volume(volume,.2)/100)**1.5
            self.assertAlmostEqual(normal,volume/100);self.assertAlmostEqual(ducked,normal*.2)
        self.assertEqual(worker_volume(2,0),0)


if __name__=='__main__':unittest.main()
