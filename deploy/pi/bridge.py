"""Loopback-only browser bridge. The restricted device credential stays off the page."""
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import ssl
import stat
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from kiosk import validate_url
from connect import NoRedirect
from spotify import Spotify,Unavailable
from alerts import Alerts
from listener import Listener
from screen import Screen
from grouped import GroupReceiver
from bluetooth_session import BluetoothSession
from video_session import VideoSession
from local_library import LocalLibrary, byte_range
from local_camera import LocalCamera


class Bridge(BaseHTTPRequestHandler):
    configuration=None
    opener=None
    music=None
    alerts=None
    voice=None
    screen=None
    group_music=None
    bluetooth=None
    video=None
    library=None
    camera=None

    def local_camera(self,path,body,base,headers):
        try:
            profile,revision=self.access_profile(base,headers)
            if profile.get('mode')!='household':return self.error_reply(403,'Camera access requires Household mode')
            if self.headers.get('X-Echo-Profile-Revision') not in (None,str(revision)):
                return self.error_reply(409,'Display access changed. Reload this page.')
            if self.command=='GET' and path=='/v1/display/camera':result=self.camera.snapshot()
            elif self.command in {'POST','PUT'} and body and len(body)<=2048:
                value=json.loads(body)
                if not isinstance(value,dict):raise ValueError('Use a camera request object')
                if self.command=='PUT' and path!='/v1/display/camera':return self.error_reply(405,'Unsupported camera method')
                if self.command=='PUT' and path=='/v1/display/camera':result=self.camera.configure(value)
                elif path.endswith('/start'):result=self.camera.start_capture(value.get('client'),value.get('purpose'))
                elif path.endswith('/pulse'):result=self.camera.pulse(value)
                elif path.endswith('/stop'):result=self.camera.release(value)
                elif path.endswith('/off'):result=self.camera.disable()
                elif path.endswith('/focus'):result=self.camera.focus(value)
                elif path.endswith('/meet'):result=self.camera.launch_meet(value.get('client'),value.get('code'))
                elif path.endswith('/frame'):
                    raw=self.camera.frame(value);self.send_response(200)
                    for key,val in {'Content-Type':'image/jpeg','Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}.items():self.send_header(key,val)
                    self.end_headers();self.wfile.write(raw);return
                else:return self.error_reply(404,'Unknown camera action')
            else:return self.error_reply(405,'Unsupported camera method')
            raw=json.dumps(result).encode();self.send_response(200)
            for key,val in {'Content-Type':'application/json','Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Echo-Display-Bridge':'1'}.items():self.send_header(key,val)
            self.end_headers();self.wfile.write(raw)
        except (ValueError,TypeError):return self.error_reply(422,'Choose valid camera settings')
        except Unavailable as error:return self.error_reply(409,str(error))
        except (OSError,urllib.error.URLError):return self.error_reply(503,'Camera access is unavailable')

    def local_library(self,path,base,headers):
        try:
            profile,_=self.access_profile(base,headers)
            if profile.get('mode')!='household':return self.error_reply(403,'On-device music is available in Household mode')
        except urllib.error.HTTPError as error:return self.error_reply(error.code,'Pair this display before opening its music library')
        except (OSError,urllib.error.URLError):return self.error_reply(503,'Display access is unavailable')
        if self.command not in {'GET','HEAD'}:return self.error_reply(405,'The music library is read only')
        try:
            if path=='/v1/display/library':
                raw=json.dumps(self.library.scan(force=urlsplit(self.path).query=='rescan=1')).encode()
                self.send_response(200)
                for key,value in {'Content-Type':'application/json','Content-Length':str(len(raw)),
                                  'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}.items():self.send_header(key,value)
                self.end_headers()
                if self.command!='HEAD':self.wfile.write(raw)
                return
            match=re.fullmatch(r'/v1/display/library/stream/([a-f0-9]{32})',path)
            if not match:return self.error_reply(404,'Unknown music library route')
            stream,size,kind=self.library.open_track(match[1])
            with stream:
                try:start,end,partial=byte_range(self.headers.get('Range'),size)
                except ValueError:
                    self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
                self.send_response(206 if partial else 200)
                for key,value in {'Content-Type':kind,'Content-Length':str(end-start+1),'Accept-Ranges':'bytes',
                                  'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}.items():self.send_header(key,value)
                if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                self.end_headers()
                if self.command=='HEAD':return
                stream.seek(start);remaining=end-start+1
                try:
                    while remaining:
                        block=stream.read(min(65536,remaining))
                        if not block:break
                        self.wfile.write(block);remaining-=len(block)
                except (BrokenPipeError,ConnectionResetError):pass
        except FileNotFoundError:return self.error_reply(404,'Track is unavailable. Rescan your music folder.')
        except OSError:return self.error_reply(503,'The music folder is unavailable')

    def access_profile(self,base,headers):
        request=urllib.request.Request(base+'/v1/display/session',headers=headers)
        with self.opener.open(request,timeout=5) as response:
            result=json.loads(response.read(64000))
        return result.get('profile',{'mode':'household'}),result.get('profile_revision',0)

    def local_screen(self,body):
        # Local screen comfort settings must work even when the host is offline.
        # proxy() has already enforced loopback Host and same-origin write headers.
        try:
            if self.command in {'GET','HEAD'}:result=self.screen.snapshot()
            elif self.command=='PUT' and body and len(body)<=512:
                result=self.screen.configure(json.loads(body))
            elif self.command=='POST' and body and len(body)<=128:
                value=json.loads(body)
                if value=={'action':'wake'}:self.screen.wake()
                elif value=={'action':'sleep'}:
                    if not self.video or not self.video.active():self.screen.sleep()
                else:raise ValueError('Invalid screen action')
                result={'ok':True}
            else:return self.error_reply(405,'Unsupported screen method')
            raw=json.dumps(result).encode();self.send_response(200)
            for key,value in {'Content-Type':'application/json','Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Echo-Display-Bridge':'1'}.items():self.send_header(key,value)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        except (ValueError,TypeError):return self.error_reply(422,'Choose valid screen settings; sleep must follow dimming')
        except (OSError,subprocess.SubprocessError):return self.error_reply(503,'Display power control is unavailable')

    def local_music(self,path,body,base,headers):
        # Local controls retain the display's enrollment boundary. A revoked
        # credential cannot edit this receiver through the kiosk.
        request=urllib.request.Request(base+'/v1/display/session',headers=headers)
        try:
            profile,_=self.access_profile(base,headers)
            if profile['mode']=='guest' and self.command=='PUT':return self.error_reply(403,'Music setup is managed by the owner')
        except urllib.error.HTTPError as error:return self.error_reply(error.code,'Pair this display before using local music')
        except (urllib.error.URLError,TimeoutError):return self.error_reply(503,'Echo host unavailable')
        try:
            if self.command in {'GET','HEAD'} and path.endswith('/now-playing'):result=self.music.snapshot()
            elif self.command in {'GET','HEAD'} and path.endswith('/settings'):result=self.music.settings()
            elif self.command=='GET' and re.fullmatch(r'/v1/display/music/artwork/[a-f0-9]{64}',path):
                raw,kind=self.music.artwork(path.rsplit('/',1)[1]);result=None
            elif self.command in {'POST','PUT'}:
                if not body or len(body)>2048:raise ValueError('Invalid music request')
                value=json.loads(body)
                if self.command=='PUT' and path.endswith('/settings'):result=self.music.configure(value)
                elif self.command=='POST' and path.endswith('/control') and isinstance(value,dict) and set(value)<={'action','value'}:result=self.music.control(value.get('action'),value.get('value'))
                elif self.command=='POST' and path.endswith('/focus') and isinstance(value,dict) and set(value)=={'client','busy'}:
                    result=self.music.focus(value['client'],value['busy'])
                    if value['busy'] and self.alerts is not None:self.alerts.interrupt()
                    if value['busy'] and self.voice is not None:self.voice.interrupt()
                else:raise ValueError('Unsupported music request')
            else:return self.error_reply(405,'Unsupported music method')
            if result is not None:raw=json.dumps(result).encode();kind='application/json'
            self.send_response(200)
            for key,value in {'Content-Type':kind,'Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Echo-Display-Bridge':'1'}.items():self.send_header(key,value)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        except (ValueError,TypeError):return self.error_reply(422,'Invalid music settings or control')
        except Unavailable as error:return self.error_reply(409,str(error))
        except (OSError,urllib.error.URLError):return self.error_reply(503,'Pi music is unavailable')

    def local_group_music(self,path,body,base,headers):
        try:
            if path.endswith('/focus') and self.command=='GET':
                bluetooth_active=bool(self.bluetooth and self.bluetooth.snapshot().get('output_active'))
                video_active=bool(self.video and self.video.active())
                with self.music.lock:
                    result={'held':self.music.held(),'ducked':self.music.ducked(),
                            'other_music':bluetooth_active or video_active or bool(self.music.player and self.music.player.poll() is None)}
            else:
                profile,_=self.access_profile(base,headers)
                if profile['mode']=='guest':return self.error_reply(403,'Grouped music is managed by the owner')
                if self.command=='GET':result=self.group_music.snapshot()
                elif self.command=='PUT' and body and len(body)<=2048:result=self.group_music.configure(json.loads(body))
                else:return self.error_reply(405,'Unsupported grouped-music method')
            raw=json.dumps(result).encode();self.send_response(200)
            for key,value in {'Content-Type':'application/json','Content-Length':str(len(raw)),'Cache-Control':'no-store'}.items():self.send_header(key,value)
            self.end_headers();self.wfile.write(raw)
        except urllib.error.HTTPError as error:return self.error_reply(error.code,'Display pairing is unavailable')
        except (ValueError,TypeError):return self.error_reply(422,'Choose valid grouped-music settings')
        except Unavailable as error:return self.error_reply(409,str(error))
        except OSError:return self.error_reply(503,'Grouped music is unavailable')

    def local_alerts(self,body,base,headers):
        request=urllib.request.Request(base+'/v1/display/session',headers=headers)
        try:
            profile,_=self.access_profile(base,headers)
            if profile['mode']=='guest' and self.command=='PUT':return self.error_reply(403,'Alert setup is managed by the owner')
        except urllib.error.HTTPError as error:return self.error_reply(error.code,'Display pairing is unavailable')
        except (OSError,urllib.error.URLError):return self.error_reply(503,'Echo host unavailable')
        try:
            if self.command in {'GET','HEAD'}:result=self.alerts.settings()
            elif self.command=='PUT':result=self.alerts.configure(json.loads(body or b'{}'))
            else:return self.error_reply(405,'Unsupported alert method')
            raw=json.dumps(result).encode();self.send_response(200)
            for key,value in {'Content-Type':'application/json','Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Echo-Display-Bridge':'1'}.items():self.send_header(key,value)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        except (ValueError,TypeError):return self.error_reply(422,'Choose valid alert settings and an available speaker output')
        except Unavailable as error:return self.error_reply(409,str(error))
        except OSError:return self.error_reply(503,'Pi alert settings could not be saved')

    def local_voice(self,body,base,headers):
        request=urllib.request.Request(base+'/v1/display/session',headers=headers)
        try:
            profile,revision=self.access_profile(base,headers)
            if profile['mode']=='guest':
                if not profile.get('conversation',False):return self.error_reply(403,'Conversation is not shared with this display')
                if self.command=='PUT':return self.error_reply(403,'Voice setup is managed by the owner')
        except urllib.error.HTTPError as error:return self.error_reply(error.code,'Display pairing is unavailable')
        except (OSError,urllib.error.URLError):return self.error_reply(503,'Echo host unavailable')
        try:
            if self.command in {'GET','HEAD'}:result=self.voice.settings()
            elif body and len(body)<=2048 and self.command=='PUT':result=self.voice.configure(json.loads(body))
            elif body and len(body)<=2048 and self.command=='POST':
                value=json.loads(body)
                if not isinstance(value,dict) or 'action' not in value or not set(value)<={'action','allow_home','reply_audio'}:raise ValueError()
                expected=self.headers.get('X-Echo-Profile-Revision')
                if value['action']=='talk' and (expected is not None or profile.get('personal')) and expected!=str(revision):
                    return self.error_reply(409,'Account access changed. Refresh before speaking.')
                if profile['mode']=='guest' and value.get('action')=='talk' and not profile.get('home_voice',False):value['allow_home']=False
                result=self.voice.control(**value)
            else:return self.error_reply(405,'Unsupported Pi voice request')
            result=dict(result)
            if result.get('result') and result['result'].get('access_revision',0)!=revision:result['result']=None
            raw=json.dumps(result).encode();self.send_response(200)
            for key,value in {'Content-Type':'application/json','Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Echo-Display-Bridge':'1'}.items():self.send_header(key,value)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        except (ValueError,TypeError):return self.error_reply(422,'Choose valid Pi voice settings and attached devices')
        except Unavailable as error:return self.error_reply(409,str(error))
        except OSError:return self.error_reply(503,'Pi voice settings could not be saved')

    def local_video(self,path,body):
        try:
            if self.command=='GET' and path.endswith('/output'):
                result=self.video.snapshot()
            elif self.command=='POST' and body and len(body)<=256:
                value=json.loads(body)
                if not isinstance(value,dict):raise ValueError('Invalid video request')
                if path.endswith('/player') and set(value)=={'lease','action'}:
                    result=self.video.pulse(value['lease'],value['action'])
                elif path.endswith('/output') and value=={'action':'stop'}:
                    result=self.video.end()
                elif path.endswith('/output') and set(value)=={'action','revision'} and value['action']=='start':
                    result=self.video.launch(value['revision'])
                else:raise ValueError('Invalid video request')
            else:return self.error_reply(405,'Unsupported local video method')
            raw=json.dumps(result).encode();self.send_response(200)
            for key,value in {'Content-Type':'application/json','Content-Length':str(len(raw)),
                              'Cache-Control':'no-store','X-Echo-Display-Bridge':'1'}.items():self.send_header(key,value)
            self.end_headers();self.wfile.write(raw)
        except (ValueError,TypeError):return self.error_reply(422,'Choose a valid video action')
        except Unavailable as error:return self.error_reply(409,str(error))
        except (OSError,subprocess.SubprocessError):return self.error_reply(503,'The local video player is unavailable')

    def log_message(self,*args): pass

    def error_reply(self,code,message):
        body=json.dumps({'detail':message}).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.send_header('X-Echo-Display-Bridge','1'); self.end_headers()
        if self.command!='HEAD': self.wfile.write(body)

    def waiting_page(self):
        # This must work before the host's JavaScript has ever loaded, including
        # a boot where Wi-Fi, Tailscale or the API is still starting.
        body=b'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5;url=/display"><title>Echo is reconnecting</title>
<style>body{margin:0;min-height:100vh;display:grid;place-content:center;text-align:center;
background:radial-gradient(ellipse at top,#183449,#07121f);color:#edf5ff;font:22px system-ui}
h1{font-size:42px;margin:0 0 16px}p{max-width:34em;color:#b2c4d3;line-height:1.5;padding:0 24px}
a{color:#96eadc}span{font-size:15px;letter-spacing:.2em;color:#96eadc}</style>
<span>ECHO / AT HOME</span><h1>A moment to reconnect.</h1>
<p>Your display is ready. Waiting for the private connection to the Echo host.</p>
<p>This page retries automatically. <a href="/display">Try now</a></p></html>'''
        self.send_response(503)
        for key,value in {'Content-Type':'text/html; charset=utf-8','Content-Length':str(len(body)),
                          'Cache-Control':'no-store','Retry-After':'5',
                          'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"}.items():self.send_header(key,value)
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)

    def proxy(self):
        host=self.headers.get('Host',''); port=self.server.server_port
        if host not in {f'127.0.0.1:{port}',f'localhost:{port}'}: return self.error_reply(403,'Use the local display address')
        requested=urlsplit(self.path)
        if requested.scheme or requested.netloc or not requested.path.startswith(('/v1/','/assets/')) and requested.path not in {'/','/display','/display/video-player','/health'}:
            return self.error_reply(403,'Administration is available in the owner workspace')
        body=None
        if self.command not in {'GET','HEAD'}:
            if self.headers.get('Origin') not in {None,'http://'+host} or self.headers.get('X-Echo-Request')!='1': return self.error_reply(403,'Use the local Echo display')
            try:size=int(self.headers.get('Content-Length','0'))
            except ValueError:return self.error_reply(400,'Invalid request length')
            if not 0<=size<=16_000_000:return self.error_reply(413,'Request is too large')
            body=self.rfile.read(size)
        source=urlsplit(self.configuration['url']); base=f'{source.scheme}://{source.netloc}'
        path='/display' if self.path=='/' else self.path
        display_page=requested.path in {'/','/display'} and self.command in {'GET','HEAD'}
        headers={'Authorization':'Display '+self.configuration['credential'],'X-Echo-Request':'1','Origin':base}
        if self.camera is not None and re.fullmatch(r'/v1/display/camera(?:/(?:start|pulse|stop|off|focus|frame|meet))?',requested.path):
            return self.local_camera(requested.path,body,base,headers)
        if self.library is not None and requested.path.startswith('/v1/display/library'):
            return self.local_library(requested.path,base,headers)
        if self.video is not None and requested.path in {'/v1/display/video/output','/v1/display/video/player'}:
            return self.local_video(requested.path,body)
        if self.bluetooth is not None and requested.path=='/v1/display/bluetooth':
            if self.command!='GET':return self.error_reply(405,'Bluetooth setup uses the private owner configuration')
            try:
                profile,_=self.access_profile(base,headers)
                if profile['mode']!='household':return self.error_reply(403,'Bluetooth status is available to Household displays')
            except (OSError,urllib.error.URLError):return self.error_reply(503,'Display access is unavailable')
            raw=json.dumps(self.bluetooth.snapshot()).encode();self.send_response(200)
            for key,value in {'Content-Type':'application/json','Content-Length':str(len(raw)),'Cache-Control':'no-store'}.items():self.send_header(key,value)
            self.end_headers();self.wfile.write(raw);return
        if self.group_music is not None and requested.path in {'/v1/display/group-music','/v1/display/group-music/focus'}:
            return self.local_group_music(requested.path,body,base,headers)
        if self.screen is not None and requested.path=='/v1/display/screen':
            return self.local_screen(body)
        if self.voice is not None and requested.path=='/v1/display/local-voice':
            return self.local_voice(body,base,headers)
        if self.alerts is not None and requested.path=='/v1/display/alert-settings':
            return self.local_alerts(body,base,headers)
        if self.music is not None and requested.path.startswith('/v1/display/music/'):
            if not re.fullmatch(r'/v1/display/music/(?:now-playing|settings|control|focus|artwork/[a-f0-9]{64})',requested.path):return self.error_reply(404,'Unknown local music route')
            return self.local_music(requested.path,body,base,headers)
        for key in ('Content-Type','Range','Accept','X-Echo-Profile-Revision'):
            if self.headers.get(key): headers[key]=self.headers[key]
        request=urllib.request.Request(base+path,data=body,method=self.command,headers=headers)
        started=False
        try:
            try: response=self.opener.open(request,timeout=10 if display_page else 120)
            except urllib.error.HTTPError as error: response=error
            with response:
                if display_page and response.status>=500:return self.waiting_page()
                self.send_response(response.status)
                for key in ('Content-Type','Content-Length','Content-Range','Accept-Ranges','Content-Security-Policy','Referrer-Policy','X-Content-Type-Options'):
                    if response.headers.get(key):self.send_header(key,response.headers[key])
                self.send_header('Cache-Control','no-store'); self.send_header('X-Echo-Display-Bridge','1'); self.end_headers(); started=True
                if self.command!='HEAD':
                    while block:=response.read1(65536):
                        self.wfile.write(block)
                        self.wfile.flush()
        except (urllib.error.URLError,TimeoutError):
            if not started and display_page:return self.waiting_page()
            if not started: return self.error_reply(503,'Echo host unavailable. Check its address, connection, and pairing status.')
            self.close_connection=True
        except (BrokenPipeError,ConnectionResetError): pass

    do_GET=do_HEAD=do_POST=do_PUT=do_PATCH=do_DELETE=proxy


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--port',type=int,default=8790)
    parser.add_argument('--config',type=Path,default=Path.home()/'.config/echo-display/connection.json')
    args=parser.parse_args()
    if args.config.is_symlink(): raise SystemExit('Use a regular, private connection file')
    info=args.config.stat()
    if os.name=='posix' and (stat.S_IMODE(info.st_mode)&0o077 or info.st_uid!=os.geteuid()): raise SystemExit('Connection file must belong to this user with mode 600')
    config=json.loads(args.config.read_text()); validate_url(config['url'])
    Bridge.configuration=config
    Bridge.library=LocalLibrary()
    Bridge.opener=urllib.request.build_opener(NoRedirect,urllib.request.HTTPSHandler(context=ssl.create_default_context()),urllib.request.ProxyHandler({}))
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Bridge)
    Bridge.music=Spotify();Bridge.music.start()
    Bridge.group_music=GroupReceiver(args.config);Bridge.group_music.start()
    Bridge.screen=Screen()
    try:Bridge.screen.apply()
    except (OSError,subprocess.SubprocessError):pass  # X11 may start after the bridge.
    source=urlsplit(config['url']);base=f'{source.scheme}://{source.netloc}'
    def native_request(path,body=None,content_type="application/json",timeout=5):
        headers={'Authorization':'Display '+config['credential'],'Origin':base,'X-Echo-Request':'1','Content-Type':content_type}
        payload=body if isinstance(body,bytes) else json.dumps(body).encode() if body is not None else None
        request=urllib.request.Request(base+path,data=payload,headers=headers)
        with Bridge.opener.open(request,timeout=timeout) as response:
            raw=response.read(12_000_001)
            if len(raw)>12_000_000:raise ValueError('Native response exceeds its limit')
            return json.loads(raw)
    Bridge.bluetooth=BluetoothSession(native_request,Bridge.music);Bridge.bluetooth.start()
    Bridge.video=VideoSession(native_request,Bridge.music,Bridge.group_music,Bridge.screen);Bridge.video.start()
    Bridge.alerts=Alerts(native_request,Bridge.music);Bridge.alerts.start()
    Bridge.voice=Listener(native_request,Bridge.music,wake_screen=Bridge.screen.wake);Bridge.voice.start()
    Bridge.camera=LocalCamera(native_request,Bridge.music,Bridge.screen,Bridge.voice)
    print(f'Echo display bridge listening on loopback port {args.port}. Credentials stay outside the browser.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();Bridge.camera.close();Bridge.video.close();Bridge.bluetooth.close();Bridge.group_music.close();Bridge.voice.close();Bridge.alerts.close();Bridge.music.close()


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError):raise SystemExit('Display bridge could not start. Check its private configuration and pairing.') from None
