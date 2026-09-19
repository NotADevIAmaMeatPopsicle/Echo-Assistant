"""Receiver adapter; claims before audio and never automatically retries a delivery."""
from io import BytesIO
import time
import wave


class RoundAnnouncements:
    def __init__(self,client,worker):
        self.client,self.worker=client,worker
        self.inbox={};self.updated=0.;self.job=None;self.current=None;self.playing=False
        self.attempted=set();self.receipts=[]

    def request(self,method,path,body=None):
        response=self.client.request(method,path,headers={'X-Echo-Audio-Receiver':'round'},
                                     **({'json':body} if body is not None else {}),timeout=100)
        response.raise_for_status();return response

    def update(self,inbox):
        self.inbox=inbox;self.updated=time.monotonic()
        self.receipts=[job for job in self.receipts if not job.done()]
        if not self.job and not self.playing:
            self.attempted.intersection_update(i['id'] for i in inbox.get('items',[]))

    @property
    def stop_requested(self):
        if not self.current:return False
        if time.monotonic()-self.updated>5:return True
        if not self.inbox.get('enabled') or self.inbox.get('status') in {'quiet_hours','muted','disabled'}:return True
        return any(i['id']==self.current['id'] and i['status']!='claimed' for i in self.inbox.get('active',[]))

    def prepare(self,identifier):
        path='/v1/audio/inbox/'+identifier
        claim=self.request('POST',path+'/claim',{'client':'round'}).json()['claim']
        try:
            response=self.request('POST',path+'/audio',{'claim':claim})
            with wave.open(BytesIO(response.content),'rb') as source:
                if (source.getnchannels(),source.getsampwidth(),source.getframerate())!=(1,2,48000) or source.getnframes()>48000*60:raise ValueError('Invalid announcement audio')
                pcm=source.readframes(source.getnframes())
                if not pcm:raise ValueError('Empty announcement audio')
            return {'id':identifier,'claim':claim,'pcm':pcm}
        except Exception:
            try:self.request('POST',path+'/receipt',{'claim':claim,'status':'failed'})
            except Exception:pass  # Unknown delivery is not replayed.
            raise

    def take(self):
        if self.playing:return None
        if self.job:
            if not self.job.done():return None
            job,self.job=self.job,None
            try:self.current=job.result()
            except Exception:self.current=None;return None
            if self.stop_requested:self.finished('cancelled');return None
            self.playing=True
            return self.current.pop('pcm')
        if self.inbox.get('ready') and time.monotonic()-self.updated<5:
            message=next((i for i in self.inbox.get('items',[]) if i['id'] not in self.attempted),None)
            if message:
                self.attempted.add(message['id']);self.job=self.worker.submit(self.prepare,message['id'])
        return None

    def finished(self,status='played'):
        if self.current:
            self.receipts.append(self.worker.submit(self.request,'POST','/v1/audio/inbox/'+self.current['id']+'/receipt',
                                                   {'claim':self.current['claim'],'status':status}))
        self.current=None;self.playing=False

    def cancel(self,status='cancelled'):
        self.finished(status)
        if self.job:
            job,self.job=self.job,None
            def discard(done):
                if done.cancelled():return
                try:
                    result=done.result()
                    self.worker.submit(self.request,'POST','/v1/audio/inbox/'+result['id']+'/receipt',{'claim':result['claim'],'status':status})
                except Exception:pass
            job.add_done_callback(discard);job.cancel()
