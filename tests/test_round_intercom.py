"""Synthetic call control and PCM pipes. No devices, recordings, models or home actions."""
import struct
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend.announcements import Announcements
from backend.intercom import Intercom
from backend.round_intercom import CallAudio,RoundIntercom
from backend.speaker import Speaker


def wait_for(predicate,timeout=3):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.01)
    raise AssertionError('Synthetic call did not reach its expected state')


class Cleaner:
    def reset(self):pass
    def process_frame(self,pcm,reference):return pcm
    def close(self):pass


class Response:
    def __init__(self,data):self.data=data
    def json(self):return self.data
    def raise_for_status(self):pass


class AudioDouble:
    def __init__(self,client,identifier,cleaner,clock):
        self.identifier=identifier;self.stop=threading.Event();self.muted=True;self.frames=[];self.last_input=clock()
    def start(self):pass
    def mute(self,value):self.muted=value;self.frames.clear()
    def feed(self,pcm,reference):
        if not self.muted:self.frames.append(pcm)
    def close(self):self.stop.set();self.frames.clear()


class RoundControlTests(unittest.TestCase):
    def setUp(self):
        self.peer='a'*32;self.call_id='c'*32;self.client_id='b'*32;self.fail=False
        rooms=Announcements(None,None,SimpleNamespace(snapshot=lambda:[{'id':self.peer,'name':'Kitchen'}]),
                            SimpleNamespace(snapshot=lambda:{'quiet_active':False}),
                            lambda:{'status':'intercom','muted':False,'device':{'intercom':'1'}})
        rooms.configure([{'id':'round','room':'Round speaker','calls_enabled':True},
                         {'id':self.peer,'room':'Kitchen','calls_enabled':True}],0)
        self.server=Intercom(rooms)
        self.server.heartbeat(self.peer,self.client_id,True,False)
        test=self
        class Client:
            def request(self,method,path,**kwargs):
                if test.fail:raise OSError('Synthetic network loss')
                body=kwargs['json'];s=test.server
                if path.endswith('/heartbeat'):result=s.heartbeat('round',body['client'],body['enabled'],body['busy'])
                elif path=='/v1/intercom/calls':result=s.start('round','round',body['id'],body['target'],body['revision'])
                else:
                    identifier,action=path.split('/')[-2:]
                    if action=='accept':result=s.accept(identifier,'round','round')
                    elif action=='end':result=s.end(identifier,'round','round')
                    elif action=='mute':result=s.mute(identifier,'round','round',body['muted'])
                    else:raise AssertionError(path)
                return Response(result)
        self.patch=patch('backend.round_intercom.CallAudio',AudioDouble);self.patch.start();self.addCleanup(self.patch.stop)
        self.writes=[];self.receiver=RoundIntercom(Client(),self.writes.append,cleaner_factory=Cleaner)
        self.addCleanup(self.receiver.close)
        self.receiver.tick({'device':{'intercom':'1'},'muted':False},'armed')
        self.receiver.receive('EVENT intercom_enabled=1')
        wait_for(lambda:self.receiver.state.get('ready'))

    def incoming(self):
        self.server.start(self.peer,self.client_id,self.call_id,'round',1)
        wait_for(lambda:self.receiver.call.get('status')=='ringing')

    def test_answer_capture_ack_mute_and_hangup(self):
        self.incoming();r=self.receiver;pcm=b'\1\0'*256
        self.assertIsNone(r.audio);self.assertIsNone(r.consent)
        r.receive(f'EVENT intercom_action=answer id={"d"*32}');self.assertIsNone(r.consent)
        r.receive(f'EVENT intercom_action=answer id={self.call_id}');wait_for(lambda:r.active)
        r.feed([pcm],[pcm]);self.assertEqual(r.audio.frames,[])
        r.receive(f'EVENT intercom_capture={self.call_id}');r.feed([pcm],[pcm])
        self.assertEqual(r.audio.frames,[],'Discard the batch containing the capture acknowledgement')
        r.feed([pcm],[pcm]);self.assertEqual(r.audio.frames,[pcm])
        r.receive(f'EVENT intercom_action=mute id={self.call_id}');r.feed([pcm],[pcm]);self.assertEqual(r.audio.frames,[])
        r.receive(f'EVENT intercom_action=unmute id={self.call_id}');wait_for(lambda:not r.audio.muted)
        r.feed([pcm],[pcm]);self.assertEqual(r.audio.frames,[],'Unmute needs a new firmware capture acknowledgement')
        r.receive(f'EVENT intercom_capture={self.call_id}');r.feed([pcm],[pcm]);r.feed([pcm],[pcm]);self.assertEqual(r.audio.frames,[pcm])
        r.receive(f'EVENT intercom_action=hangup id={self.call_id}');wait_for(lambda:not r.busy)
        self.assertIsNone(r.audio);self.assertIsNone(r.capture)

    def test_outgoing_binds_room_selection_and_does_not_rejoin_after_network_loss(self):
        r=self.receiver
        r.receive(f'EVENT intercom_call=0 binding={"0"*16} id={self.call_id}')
        self.assertIsNone(r.consent)
        r.receive(f'EVENT intercom_call=0 binding={r.binding} id={self.call_id}')
        wait_for(lambda:r.call.get('status')=='ringing')
        self.server.accept(self.call_id,self.peer,self.client_id);wait_for(lambda:r.active)
        self.fail=True;wait_for(lambda:not r.enabled)
        self.assertFalse(r.active);self.assertIsNone(r.consent)
        self.fail=False;time.sleep(1.2);self.assertFalse(r.active);self.assertFalse(r.enabled)

    def test_cancelling_queued_action_cannot_start_a_call(self):
        r=self.receiver;r.disable()
        r.action(('start',self.call_id,self.peer,1))
        self.assertNotIn(self.call_id,self.server.calls)

    def test_hangup_before_server_ack_revokes_outgoing_consent(self):
        r=self.receiver;r.consent=self.call_id
        self.assertFalse(r.call)
        r.receive(f'EVENT intercom_action=hangup id={self.call_id}')
        self.assertIsNone(r.consent)
        r.action(('start',self.call_id,self.peer,1))
        self.assertNotIn(self.call_id,self.server.calls)


class CallAudioTests(unittest.TestCase):
    def test_old_firmware_does_not_start_intercom_requests_or_cleaner(self):
        client=Mock();cleaner=Mock();receiver=RoundIntercom(client,lambda _:None,cleaner_factory=cleaner)
        receiver.tick({'device':{'version':'0.13.0'},'muted':False},'armed')
        receiver.close()
        client.request.assert_not_called();cleaner.assert_not_called()

    def test_bounded_output_duplicate_frames_and_silence_keepalive(self):
        now=[10.];audio=CallAudio(None,'a'*32,Cleaner(),lambda:now[0])
        audio.append(struct.pack('<1600h',*([3000]*1600)))
        self.assertLessEqual(len(audio.output),24)
        pcm=audio.read();self.assertEqual(len(pcm),512);self.assertEqual(struct.unpack('<h',pcm[-2:])[0],3000)
        now[0]+=1;self.assertEqual(audio.read(),b'\0'*512)
        audio.close();self.assertIsNone(audio.read());self.assertEqual(audio.partial,b'')

    def test_capture_is_muted_until_enabled_and_upload_never_uses_raw_unpaired_frames(self):
        uploads=[]
        class Client:
            def request(self,method,path,**kwargs):uploads.append(kwargs['content']);return Response({})
        audio=CallAudio(Client(),'a'*32,Cleaner());self.addCleanup(audio.close)
        pcm=b'\1\0'*256;audio.feed(pcm,pcm);self.assertTrue(audio.input.empty())
        audio.mute(False);audio.feed(pcm,None);self.assertTrue(audio.input.empty())
        thread=threading.Thread(target=audio.upload);thread.start()
        try:
            for _ in range(7):audio.feed(pcm,pcm);time.sleep(.02)
            wait_for(lambda:len(uploads)==1);self.assertEqual(uploads[0],b'\1\0'*1600)
            audio.mute(True)
            for _ in range(8):audio.feed(pcm,pcm)
            time.sleep(.15);self.assertEqual(len(uploads),1)
        finally:audio.close();thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_download_parses_fragmented_keepalives_and_skips_duplicates(self):
        pcm=b'\7\0'*320
        raw=struct.pack('<II',0,0)+struct.pack('<II',1,len(pcm))+pcm+struct.pack('<II',1,len(pcm))+pcm
        class Stream:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def raise_for_status(self):pass
            def iter_bytes(self):
                for at in range(0,len(raw),17):yield raw[at:at+17]
        audio=CallAudio(SimpleNamespace(stream=lambda *a,**k:Stream()),'a'*32,Cleaner())
        audio.download();self.assertEqual(len(audio.output),3)
        self.assertTrue(audio.failed,'An ended response must stop the live call')

    def test_intercom_sender_uses_shorter_credit_window_than_music(self):
        speaker=Speaker(lambda _:None);speaker.start_stream(lambda:b'\0'*512,kind='I')
        speaker.receive(f'EVENT audio_ready={speaker.session} capacity=256')
        for _ in range(5):speaker.pump()
        self.assertEqual(speaker.sent,24)


if __name__=='__main__':unittest.main()
