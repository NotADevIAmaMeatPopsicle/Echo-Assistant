"""Explicit Pi push-to-talk through ALSA and the paired loopback bridge. No wake listener."""
import argparse
import array
import base64
from io import BytesIO
import json
import shutil
import subprocess
import sys
import urllib.request
import wave
from connect import NoRedirect

BASE='http://127.0.0.1:8790'


def request(path,body=None,content_type='application/json',timeout=120):
    headers={'Origin':BASE,'X-Echo-Request':'1'}
    if body is not None:headers['Content-Type']=content_type
    query=urllib.request.Request(BASE+path,data=body,headers=headers)
    opener=urllib.request.build_opener(NoRedirect,urllib.request.ProxyHandler({}))
    with opener.open(query,timeout=timeout) as response:
        raw=response.read(12_000_001)
        if len(raw)>12_000_000:raise ValueError('Oversized audio response')
        return json.loads(raw)


def stop_request():
    try:
        activity=request('/v1/chat/activity',timeout=5)
        if activity.get('active') and activity.get('id'):request('/v1/chat/activity/'+activity['id']+'/stop',b'{}',timeout=5)
    except (OSError,ValueError):pass


def wav(pcm):
    result=BytesIO()
    with wave.open(result,'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(pcm)
    return result.getvalue()


def scaled_reply(encoded,volume):
    raw=base64.b64decode(encoded,validate=True)
    with wave.open(BytesIO(raw),'rb') as audio:
        if audio.getnchannels()!=1 or audio.getsampwidth()!=2 or audio.getframerate()!=48000 or audio.getnframes()>48000*90:raise ValueError('Unsupported reply audio')
        pcm=audio.readframes(audio.getnframes())
        if len(pcm)!=audio.getnframes()*2:raise ValueError('Incomplete reply audio')
    samples=array.array('h');samples.frombytes(pcm)
    if sys.byteorder!='little':samples.byteswap()
    samples=array.array('h',(round(sample*volume/100) for sample in samples))
    if sys.byteorder!='little':samples.byteswap()
    return samples.tobytes()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true');parser.add_argument('--once',action='store_true')
    parser.add_argument('--capture-device');parser.add_argument('--playback-device')
    parser.add_argument('--volume',type=float,default=2);parser.add_argument('--text-only',action='store_true')
    parser.add_argument('--allow-home',action='store_true',help='Allow this request to use granted home controls')
    args=parser.parse_args()
    if sys.platform!='linux':raise SystemExit('The ALSA adapter runs on the Pi. Use the web display elsewhere.')
    if args.check:
        for binary in ('arecord','aplay'):
            if shutil.which(binary):subprocess.run([binary,'-l'],check=False,timeout=5)
            else:print(binary+' is not installed')
        return
    if not args.once or not args.capture_device or not (args.playback_device or args.text_only):
        raise SystemExit('Choose --once, --capture-device and --playback-device (or --text-only).')
    if not 0<=args.volume<=30:raise SystemExit('Use a quiet playback level from 0 to 30 percent; default is 2.')
    if not request('/v1/display/voice',timeout=10)['available']:raise SystemExit('Local Whisper is not ready on the Echo host.')
    print('Listening for eight seconds. Ctrl+C cancels. No recording is saved.',flush=True)
    with subprocess.Popen(['arecord','-q','-D',args.capture_device,'-t','raw','-f','S16_LE','-r','16000','-c','1','-d','8'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL) as capture:
        try:pcm,_=capture.communicate(timeout=12)
        finally:
            if capture.poll() is None:capture.kill();capture.wait()
        if capture.returncode or not 3200<=len(pcm)<=256000:raise SystemExit('Microphone capture failed. Check the selected ALSA device.')
    print('Asking Echo…',flush=True)
    try:
        result=request('/v1/display/voice?allow_home='+str(args.allow_home).lower()+'&reply_audio='+str(not args.text_only).lower(),wav(pcm),'audio/wav')
    except (KeyboardInterrupt,OSError):stop_request();raise
    print(result.get('text','No answer received.'))
    if result.get('audio') and not args.text_only:
        pcm=scaled_reply(result['audio']['data'],args.volume)
        subprocess.run(['aplay','-q','-D',args.playback_device,'-t','raw','-f','S16_LE','-r','48000','-c','1'],input=pcm,check=True,timeout=95)
    elif result.get('audio_error'):print(result['audio_error'])


if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:raise SystemExit('Stopped.') from None
    except (OSError,ValueError,subprocess.SubprocessError,wave.Error):raise SystemExit('Pi speech failed. Check the bridge, speech runtime and selected audio devices. No request was retried.') from None
