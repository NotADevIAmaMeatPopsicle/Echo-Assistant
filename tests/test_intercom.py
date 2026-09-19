"""Call state and synthetic PCM routing; no physical audio, STT or speech engine."""
import struct
from types import SimpleNamespace
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.announcements import Announcements
from backend.intercom import Intercom,IntercomConflict,IntercomDenied


class IntercomTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.;self.quiet=False;self.ids=['a'*32,'b'*32,'c'*32]
        displays=SimpleNamespace(snapshot=lambda:[{'id':i,'name':i[:1]} for i in self.ids])
        self.rooms=Announcements(None,None,displays,SimpleNamespace(snapshot=lambda:{'quiet_active':self.quiet}),lambda:{'status':'armed'})
        self.rooms.configure([{'id':i,'room':'Room '+str(n),'calls_enabled':True} for n,i in enumerate(self.ids)],0)
        self.calls=Intercom(self.rooms,lambda:self.now)
        self.clients=['1'*32,'2'*32,'3'*32]
        for i,c in zip(self.ids,self.clients):self.calls.heartbeat(i,c,True,False)
        self.id='d'*32

    def start(self):return self.calls.start(self.ids[0],self.clients[0],self.id,self.ids[1],1)
    def active(self):
        self.start();self.calls.accept(self.id,self.ids[1],self.clients[1])
        for i,c in zip(self.ids,self.clients):
            if i in self.ids[:2]:self.calls.mute(self.id,i,c,False)

    def test_answer_required_and_both_directions_are_private(self):
        self.start()
        with self.assertRaises(IntercomConflict):self.calls.push(self.id,self.ids[0],self.clients[0],0,b'\0'*3200)
        with self.assertRaises(IntercomDenied):self.calls.accept(self.id,self.ids[0],self.clients[0])
        self.calls.accept(self.id,self.ids[1],self.clients[1])
        with self.assertRaises(IntercomConflict):self.calls.push(self.id,self.ids[0],self.clients[0],0,b'\0'*3200)
        with self.assertRaises(IntercomDenied):self.calls.open_stream(self.id,self.ids[2],self.clients[2])
        for n in (0,1):
            self.calls.mute(self.id,self.ids[n],self.clients[n],False)
            self.calls.push(self.id,self.ids[n],self.clients[n],0,bytes([n+1])*3200)
        for n in (0,1):
            marker=self.calls.open_stream(self.id,self.ids[n],self.clients[n])
            block=self.calls.pull(self.id,self.ids[n],self.clients[n],marker)
            self.assertEqual(struct.unpack('<II',block[:8]),(0,3200))
            self.assertEqual(block[8:],bytes([2-n])*3200)
            self.assertEqual(self.calls.pull(self.id,self.ids[n],self.clients[n],marker),b'')

    def test_duplicate_start_and_upload_cannot_repeat_audio(self):
        self.active();self.assertEqual(self.start()['status'],'active');self.assertEqual(len(self.calls.calls),1)
        with self.assertRaises(IntercomConflict):self.calls.start(self.ids[2],self.clients[2],self.id,self.ids[1],1)
        for _ in range(2):self.calls.push(self.id,self.ids[0],self.clients[0],1,b'\1'*3200)
        marker=self.calls.open_stream(self.id,self.ids[1],self.clients[1])
        self.assertEqual(len(self.calls.pull(self.id,self.ids[1],self.clients[1],marker)),3208)

    def test_hangup_mute_and_revoke_remove_buffered_audio(self):
        self.active();self.calls.push(self.id,self.ids[0],self.clients[0],0,b'\0'*3200)
        self.calls.mute(self.id,self.ids[0],self.clients[0],True)
        self.assertFalse(self.calls.calls[self.id]['audio'][self.ids[0]])
        self.ids.remove('b'*32)
        self.assertEqual(self.calls.snapshot(self.ids[0],self.clients[0])['call']['reason'],'access_removed')
        with self.assertRaises(IntercomConflict):self.calls.push(self.id,self.ids[0],self.clients[0],1,b'\0'*3200)

    def test_no_recording_or_reconnect_replay(self):
        self.active();self.calls.push(self.id,self.ids[0],self.clients[0],0,b'\0'*3200)
        self.now+=.6
        marker=self.calls.open_stream(self.id,self.ids[1],self.clients[1])
        self.assertEqual(self.calls.pull(self.id,self.ids[1],self.clients[1],marker),b'')
        self.now+=11
        self.assertEqual(self.calls.snapshot(self.ids[0],self.clients[0])['call']['reason'],'disconnected')
        restarted=Intercom(self.rooms,lambda:self.now)
        self.assertEqual(restarted.calls,{})

    def test_quiet_busy_lease_and_ring_timeout(self):
        self.quiet=True
        with self.assertRaises(IntercomConflict):self.start()
        self.quiet=False
        self.calls.heartbeat(self.ids[1],self.clients[1],True,True)
        with self.assertRaises(IntercomConflict):self.start()
        self.calls.heartbeat(self.ids[1],self.clients[1],True,False)
        other=self.calls.heartbeat(self.ids[1],'f'*32,True,False)
        self.assertEqual(other['status'],'another_session')
        self.start();self.now+=31
        for i,c in zip(self.ids,self.clients):self.calls.receivers[i]['at']=self.now
        self.assertEqual(self.calls.snapshot(self.ids[0],self.clients[0])['call']['reason'],'no_answer')

    def test_rate_limit_and_second_stream(self):
        self.active();marker=self.calls.open_stream(self.id,self.ids[1],self.clients[1])
        with self.assertRaises(IntercomConflict):self.calls.open_stream(self.id,self.ids[1],self.clients[1])
        with self.assertRaises(ValueError):self.calls.push(self.id,self.ids[0],self.clients[0],0,b'\0'*6401)
        for seq in range(2):self.calls.push(self.id,self.ids[0],self.clients[0],seq,b'\0'*6400)
        with self.assertRaises(IntercomConflict):self.calls.push(self.id,self.ids[0],self.clients[0],2,b'\0'*6400)
        self.calls.close_stream(self.id,self.ids[1],marker)
        self.assertTrue(self.calls.open_stream(self.id,self.ids[1],self.clients[1]))

    def test_announcements_wait_for_intercom_and_release_after_disconnect(self):
        self.start();self.assertEqual(self.rooms.ready(self.ids[0])[1],'intercom')
        self.now+=11
        self.assertNotEqual(self.rooms.ready(self.ids[0])[1],'intercom')


class IntercomApiTests(unittest.TestCase):
    def test_real_scopes_and_streamed_audio_require_answer_and_stop_at_hangup(self):
        app=create_app('z'*40)
        with TestClient(app) as api:
            owner={'Authorization':'Bearer '+'z'*40};paired=[]
            for name in ('Kitchen','Living room','Other'):
                code=api.post('/v1/displays/pairing',json={'name':name},headers=owner).json()['code']
                paired.append(api.post('/v1/displays/enroll',json={'code':code}).json())
            headers=[{'Authorization':'Display '+p['credential']} for p in paired]
            clients=['1'*32,'2'*32,'3'*32]
            result=api.put('/v1/audio/rooms',headers=owner,json={'revision':0,'endpoints':[
                {'id':p['id'],'room':p['name'],'calls_enabled':True} for p in paired]})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(api.post('/v1/intercom/heartbeat',headers=owner,json={'client':clients[0],'enabled':True,'busy':False}).status_code,403)
            for h,c in zip(headers,clients):self.assertEqual(api.post('/v1/intercom/heartbeat',headers=h,json={'client':c,'enabled':True,'busy':False}).status_code,200)
            identifier='d'*32;path='/v1/intercom/calls/'+identifier
            result=api.post('/v1/intercom/calls',headers=headers[0],json={'id':identifier,'client':clients[0],'target':paired[1]['id'],'revision':1})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(api.get(path+'/audio?client='+clients[1],headers=headers[1]).status_code,409)
            self.assertEqual(api.post(path+'/accept',headers=headers[2],json={'client':clients[2]}).status_code,403)
            self.assertEqual(api.post(path+'/accept',headers=headers[1],json={'client':clients[1]}).status_code,200)
            api.post(path+'/mute',headers=headers[0],json={'client':clients[0],'muted':False})
            delivered=Event();opened=Event();pull=app.state.intercom.pull
            def observe(*args):
                opened.set();block=pull(*args)
                if block:delivered.set()
                return block
            with patch.object(app.state.intercom,'pull',side_effect=observe),ThreadPoolExecutor(max_workers=1) as worker:
                stream=worker.submit(api.get,path+'/audio?client='+clients[1],headers=headers[1])
                self.assertTrue(opened.wait(2))
                response=api.post(path+'/audio?client='+clients[0]+'&sequence=0',headers={**headers[0],'Content-Type':'application/octet-stream'},content=b'\1\0'*1600)
                self.assertEqual(response.status_code,200,response.text);self.assertTrue(delivered.wait(2))
                api.post(path+'/end',headers=headers[1],json={'client':clients[1]})
                response=stream.result(timeout=3)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.content,struct.pack('<II',0,3200)+b'\1\0'*1600)
                self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertEqual(api.post(path+'/audio?client='+clients[0]+'&sequence=1',headers={**headers[0],'Content-Type':'application/octet-stream'},content=b'\1\0'*1600).status_code,409)


if __name__=='__main__':unittest.main()
