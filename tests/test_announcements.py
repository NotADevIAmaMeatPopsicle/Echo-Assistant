"""Synthetic routing/receipt checks. No speech engine, microphone or speaker runs."""
from concurrent.futures import Future
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.announcements import Announcements,AnnouncementUnavailable
from backend.announcement_api import install
from backend.display_voice import wave_bytes
from backend.linux_protection import LinuxProtector
from backend.round_announcements import RoundAnnouncements
from backend.settings import SettingsStore


class AnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        key=self.root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600);self.protector=LinuxProtector(key)
        self.generated=[]
        def synth(text,**kwargs):
            self.generated.append(text)
            if hasattr(self,'synth_hook'):self.synth_hook()
            return b'\0\0'*480,{'sample_rate':48000}
        with patch('backend.app.install_announcements',side_effect=lambda *a:install(*a,synthesizer=synth)):
            app=create_app('a'*40,runtime_root=self.root,settings_store=SettingsStore(protector=self.protector))
        self.api=self.enterContext(TestClient(app,base_url='http://127.0.0.1'));self.store=app.state.announcements
        self.owner={'Authorization':'Bearer '+'a'*40};self.round={**self.owner,'X-Echo-Audio-Receiver':'round'}
        self.store.voice=lambda:{'status':'armed','muted':False,'device':{'volume':'2'}}
        self.paired=[]
        for name in ['Kitchen','Study']:
            code=self.api.post('/v1/displays/pairing',headers=self.owner,json={'name':name}).json()['code']
            self.paired.append(self.api.post('/v1/displays/enroll',json={'code':code}).json())
        self.headers=[{'Authorization':'Display '+p['credential']} for p in self.paired]
        self.clients=['b'*32,'c'*32]
        self.targets=[p['id'] for p in self.paired]+['round']

    def configure(self):
        r=self.api.put('/v1/audio/rooms',headers=self.owner,json={'revision':0,'endpoints':[
            {'id':p,'room':'Room '+str(n),'enabled':True} for n,p in enumerate(self.targets)]})
        self.assertEqual(r.status_code,200,r.text)
        for headers,client in zip(self.headers,self.clients):
            self.api.post('/v1/audio/receiver',headers=headers,json={'client':client,'ready':True,'busy':False})

    def send(self,targets=None,headers=None,identifier='d'*32):
        return self.api.post('/v1/audio/messages',headers=headers or self.owner,json={'id':identifier,'title':'Dinner',
            'message':'Come downstairs.','targets':targets or self.targets,'revision':1,'issued_at':time.time()})

    def claim(self,index=0):
        return self.api.post('/v1/audio/inbox/'+'d'*32+'/claim',headers=self.headers[index],json={'client':self.clients[index]})

    def test_default_disabled_and_owner_only_configuration(self):
        catalog=self.api.get('/v1/audio/rooms',headers=self.owner).json()
        self.assertTrue(all(not i['enabled'] for i in catalog['items']))
        self.assertEqual(self.api.get('/v1/audio/rooms',headers=self.headers[0]).json()['items'],[])
        self.assertEqual(self.send().status_code,409)
        self.assertEqual(self.api.put('/v1/audio/rooms',headers=self.headers[0],json={'revision':0,'endpoints':[]}).status_code,403)
        self.assertEqual(self.api.get('/v1/audio/inbox?client=round',headers=self.owner).status_code,403)

    def test_room_scoping_shared_synthesis_and_round_state(self):
        self.configure();self.assertEqual(self.send().status_code,200)
        self.assertNotIn('audio_inbox',self.api.get('/v1/state',headers=self.owner).json())
        self.assertEqual(len(self.api.get('/v1/state',headers=self.round).json()['audio_inbox']['items']),1)
        for index in [0,1]:
            claim=self.claim(index).json()['claim']
            audio=self.api.post('/v1/audio/inbox/'+'d'*32+'/audio',headers=self.headers[index],json={'claim':claim})
            self.assertEqual(audio.status_code,200,audio.text if audio.status_code!=200 else '')
            self.assertTrue(audio.content.startswith(b'RIFF'))
            wrong=self.api.post('/v1/audio/inbox/'+'d'*32+'/receipt',headers=self.headers[1-index],json={'claim':claim,'status':'played'})
            self.assertEqual(wrong.status_code,409)
            self.assertEqual(self.api.post('/v1/audio/inbox/'+'d'*32+'/receipt',headers=self.headers[index],json={'claim':claim,'status':'played'}).status_code,200)
        self.assertEqual(self.generated,['Come downstairs.'])
        self.assertEqual(self.api.get('/v1/display/session',headers=self.headers[0]).json()['receiver_id'],self.targets[0])

    def test_duplicate_request_and_restart_do_not_replay_claims(self):
        self.configure();self.send();claim=self.claim().json()['claim']
        self.assertEqual(self.send().status_code,200)
        self.assertEqual(len(self.store.state['messages']),1)
        raw=self.store.path.read_bytes();self.assertNotIn(b'Come downstairs',raw);self.assertNotIn(claim.encode(),raw)
        restarted=Announcements(self.root,self.protector,self.store.displays,self.store.schedules,self.store.voice)
        self.assertEqual(restarted.reports('owner')['items'][0]['deliveries'][0]['status'],'unknown')
        self.assertEqual(self.claim().status_code,409)
        self.assertEqual(self.send(targets=['round']).status_code,409)

    def test_cancellation_during_synthesis_does_not_release_audio(self):
        self.configure();self.send();claim=self.claim().json()['claim']
        self.synth_hook=lambda:self.store.cancel('d'*32,'owner')
        result=self.api.post('/v1/audio/inbox/'+'d'*32+'/audio',headers=self.headers[0],json={'claim':claim})
        self.assertEqual(result.status_code,409)
        self.assertNotEqual(result.headers['content-type'],'audio/wav')

    def test_cancel_quiet_hours_and_expiry(self):
        self.configure();self.send()
        with patch.object(self.store.schedules,'snapshot',return_value={'quiet_active':True}):
            self.assertEqual(self.claim().status_code,409)
            self.assertFalse(self.store.inbox('round','round')['ready'])
        self.api.delete('/v1/audio/messages/'+'d'*32,headers=self.owner)
        self.assertEqual(self.claim().status_code,409)
        self.send(identifier='e'*32)
        now=time.time()
        self.store.clock=lambda:now+301
        self.assertTrue(all(d['status']=='expired' for d in self.store.reports('owner')['items'][0]['deliveries']))

    def test_only_sender_sees_or_cancels_paired_messages(self):
        self.configure();self.send(headers=self.headers[0])
        self.assertEqual(len(self.api.get('/v1/audio/messages',headers=self.headers[0]).json()['items']),1)
        self.assertEqual(self.api.get('/v1/audio/messages',headers=self.headers[1]).json()['items'],[])
        self.assertEqual(self.api.delete('/v1/audio/messages/'+'d'*32,headers=self.headers[1]).status_code,403)
        self.assertEqual(self.api.delete('/v1/audio/messages/'+'d'*32,headers=self.headers[0]).status_code,200)

    def test_revocation_cancels_and_background_tab_cannot_steal_receiver(self):
        self.configure();self.send();claim=self.claim().json()['claim']
        self.api.post('/v1/audio/receiver',headers=self.headers[0],json={'client':'f'*32,'ready':False,'busy':False})
        self.assertEqual(self.store.heartbeats[self.targets[0]]['client'],self.clients[0])
        self.api.delete('/v1/displays/'+self.targets[0],headers=self.owner)
        self.assertEqual(self.api.post('/v1/audio/inbox/'+'d'*32+'/audio',headers=self.headers[0],json={'claim':claim}).status_code,401)
        self.assertEqual(self.store.reports('owner')['items'][0]['deliveries'][0]['status'],'cancelled')

    def test_corrupt_storage_is_preserved_and_round_mute_prevents_claim(self):
        self.configure();self.send();self.store.voice=lambda:{'status':'armed','muted':True}
        r=self.api.post('/v1/audio/inbox/'+'d'*32+'/claim',headers=self.round,json={'client':'round'})
        self.assertEqual(r.status_code,409)
        self.store.path.write_bytes(b'invalid protected storage')
        restarted=Announcements(self.root,self.protector,self.store.displays,self.store.schedules,self.store.voice)
        with self.assertRaises(AnnouncementUnavailable):restarted.catalog()
        self.assertEqual(self.store.path.read_bytes(),b'invalid protected storage')


class ImmediateWorker:
    def submit(self,fn,*args):
        future=Future()
        try:future.set_result(fn(*args))
        except Exception as error:future.set_exception(error)
        return future


class RoundReceiverTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        def handle(request):
            self.calls.append(request)
            if request.url.path.endswith('/claim'):return httpx.Response(200,json={'claim':'c'*64})
            if request.url.path.endswith('/audio'):return httpx.Response(200,content=wave_bytes(b'\0\0'*480,48000))
            return httpx.Response(200,json={'status':'played'})
        self.client=httpx.Client(base_url='http://local',transport=httpx.MockTransport(handle));self.addCleanup(self.client.close)
        self.receiver=RoundAnnouncements(self.client,ImmediateWorker())
        self.inbox={'enabled':True,'ready':True,'status':'ready','items':[{'id':'d'*32}], 'active':[]}

    def test_round_claim_audio_and_receipt_order(self):
        self.receiver.update(self.inbox)
        self.assertIsNone(self.receiver.take());self.assertEqual(self.receiver.take(),b'\0\0'*480)
        self.assertTrue(self.receiver.playing);self.assertEqual(len(self.calls),2)
        self.receiver.finished();self.assertTrue(self.calls[-1].url.path.endswith('/receipt'))
        self.assertIn(b'played',self.calls[-1].content)
        self.receiver.take();self.assertEqual(len(self.calls),3)

    def test_cancel_after_synthesis_discards_audio_without_played_receipt(self):
        self.receiver.update(self.inbox);self.receiver.take()
        self.receiver.update({**self.inbox,'status':'quiet_hours','ready':False})
        self.assertIsNone(self.receiver.take());self.assertFalse(self.receiver.playing)
        self.assertIn(b'cancelled',self.calls[-1].content)


if __name__=='__main__':unittest.main()
