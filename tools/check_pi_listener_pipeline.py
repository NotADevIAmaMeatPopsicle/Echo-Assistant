"""Linux native voice check using synthetic child processes, never ALSA hardware."""
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from listener import Listener


class Music:
    def __init__(self):self.lock=threading.RLock();self.holds={}
    def held(self):return bool(self.holds)
    def focus(self,key,busy):
        if busy:self.holds[key]=True
        else:self.holds.pop(key,None)
    def snapshot(self):return {'status':'paused'}
    def duck(self,key,busy):pass


class Detector:
    def __init__(self,path):self.fired=False
    def reset(self):pass
    def feed(self,pcm):
        if not self.fired:self.fired=True;return True
        return False


def main():
    if sys.platform!='linux':raise SystemExit('Run this isolated pipe check on Linux.')
    children=[];outputs=[];requests=[]
    capture="import sys,time;from array import array\nfor i in range(400):\n sys.stdout.buffer.write(array('h',[1200,-1200]*640).tobytes() if i<25 else bytes(2560));sys.stdout.buffer.flush();time.sleep(.08)\n"
    playback="import sys,time;data=sys.stdin.buffer.read();assert len(data)>0 and len(data)%2==0;time.sleep(.16)"
    def popen(args,**kwargs):
        if args[0]=='arecord':script=capture
        elif args[0]=='aplay':
            outputs.append(kwargs['stdin'].read());kwargs['stdin'].seek(0);script=playback
        else:raise AssertionError('Unexpected executable')
        process=subprocess.Popen([sys.executable,'-u','-c',script],**kwargs);children.append(process);return process
    result=io.BytesIO()
    with wave.open(result,'wb') as wav:
        wav.setparams((1,2,48000,0,'NONE','not compressed'));wav.writeframes(b'\xe8\x03'*4800)
    def request(path,body=None,content_type=None,timeout=None):
        requests.append(path)
        if path=='/v1/display/voice':return {'available':True}
        if path.endswith('/stop'):return {'cancel_requested':True}
        assert 'capture_id=' in path and content_type=='audio/wav'
        with wave.open(io.BytesIO(body),'rb') as wav:
            assert wav.getparams()[:3]==(1,2,16000) and 1600<=wav.getnframes()<=128000
        return {'status':'complete','text':'Synthetic reply','transcript':'Synthetic command',
                'calendar_draft':{'event':{'title':'Synthetic draft'},'questions':[],'expires_at':time.time()+900},
                'audio':{'data':base64.b64encode(result.getvalue()).decode()}}
    with tempfile.TemporaryDirectory() as home:
        listener=Listener(request,Music(),home,captures=lambda:[{'id':'mic'}],speakers=lambda:[{'id':'speaker'}],detector_factory=Detector,popen=popen)
        listener.ready=lambda:True
        listener.configure({**listener.config,'enabled':True,'muted':False,'input':'mic','output':'speaker'})
        listener.start()
        try:
            deadline=time.monotonic()+14
            while time.monotonic()<deadline and not (len(outputs)>=2 and listener.phase=='armed'):time.sleep(.05)
            assert len(outputs)==2,('Expected cue and reply',listener.phase,listener.error)
            assert listener.result['text']=='Synthetic reply'
            assert listener.result['calendar_draft']['event']['title']=='Synthetic draft'
            from array import array
            assert max(array('h',outputs[1]))==20,'Reply must be attenuated to 2%'
            listener.control('mute');time.sleep(.4)
            assert listener.config['muted'] and listener.phase=='muted'
        finally:listener.close()
        assert all(child.poll() is not None for child in children)
        assert not listener.music.holds
    print(json.dumps({'native_pipeline':'passed','microphone':'synthetic child pipe','playback':'synthetic child process',
                      'physical_audio_opened':False,'cue_and_reply':len(outputs),'gain_percent':2,'mute_closed_capture':True}))


if __name__=='__main__':main()
