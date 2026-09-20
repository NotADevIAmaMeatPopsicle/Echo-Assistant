"""Synthetic PCM and local loopback requests; never opens ALSA or Spotify."""
from array import array
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock
import unittest

PI=Path(__file__).resolve().parents[1]/'deploy/pi';sys.path.insert(0,str(PI))
from spotify import Spotify,Unavailable,scaled_pcm


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.now=100.;self.devices=[{'id':'plughw:CARD=Sample','name':'Sample output'}]
        self.spawn=Mock(side_effect=AssertionError('Physical processes forbidden'))
        self.receiver=Spotify(self.tmp.name,clock=lambda:self.now,devices=lambda:self.devices,popen=self.spawn)
        self.receiver.binary.parent.mkdir(parents=True);self.receiver.binary.write_bytes(b'synthetic runtime')

    def config(self,**changes):return {**self.receiver.config,**changes}

    def event(self,kind,**extra):self.receiver.event(json.dumps({'key':self.receiver.key,'event':kind,**extra}))

    def test_explicit_output_and_disabled_default_survive_reload(self):
        r=self.receiver;self.assertFalse(r.config['enabled']);self.assertEqual(r.config['volume'],2)
        with self.assertRaises(ValueError):r.configure(self.config(enabled=True))
        with self.assertRaises(ValueError):r.configure(self.config(enabled=True,output='missing'))
        r.configure(self.config(enabled=True,output=self.devices[0]['id'],name='Kitchen Echo'))
        again=Spotify(self.tmp.name,devices=lambda:[],popen=self.spawn)
        with self.assertRaises(Unavailable):again.session()
        self.assertEqual(again.config['output'],self.devices[0]['id']);self.spawn.assert_not_called()
        self.assertEqual(again.config['name'],'Kitchen Echo')
        with self.assertRaises(ValueError):r.configure(self.config(volume=100))
        with self.assertRaises(ValueError):r.configure(self.config(name='name\ncommand'))

    def test_pcm_output_attenuation_mute_and_channel_order(self):
        raw=array('h',[32767,-32768,16000,-16000]).tobytes()
        self.assertEqual(list(array('h',scaled_pcm(raw,2))),[655,-655,320,-320])
        self.assertEqual(scaled_pcm(raw,0),b'\0'*8)
        self.assertEqual(list(array('h',scaled_pcm(raw,100))),[9830,-9830,4800,-4800])
        with self.assertRaises(ValueError):scaled_pcm(raw+b'x',2)

    def test_pause_closes_output_and_never_resumes_after_capture(self):
        r=self.receiver;r.process=Mock();r.process.poll.return_value=None;r.player=Mock();sink=r.player;r.key='k'*40
        self.event('playing',position_ms='20');self.assertFalse(r.silenced)
        r.focus('a'*32,True);self.assertTrue(r.silenced);sink.terminate.assert_called_once();self.assertIsNone(r.player)
        with self.assertRaises(Unavailable):r.control('play')
        self.event('playing',position_ms='30');self.assertTrue(r.silenced)
        r.focus('a'*32,False);self.assertTrue(r.silenced);self.assertNotIn('play',r.commands)
        r.control('play');self.assertEqual(r.commands[-1],'play')
        r.focus('a'*32,True);self.now+=16;self.assertFalse(r.held());self.assertTrue(r.silenced)

    def test_receiver_metadata_is_authenticated_and_transient(self):
        r=self.receiver;r.key='k'*40
        r.event(json.dumps({'key':'wrong','event':'track_changed','name':'must not show'}));self.assertEqual(r.track,{})
        self.event('track_changed',name='Sample track',artists='Sample artist',duration_ms='2000',uri='spotify:track:'+'A'*22,covers='https://untrusted.example/image\nhttps://i.scdn.co/image/'+'a'*40)
        self.event('playing',position_ms='200');self.now+=.5
        state=r.snapshot();self.assertEqual(state['position_ms'],700);self.assertTrue(state['artwork'].startswith('/v1/display/music/artwork/'))
        self.assertNotIn('cover',state);self.assertNotIn('key',state)
        with self.assertRaises(ValueError):r.artwork('b'*64)
        self.event('session_disconnected');self.assertNotIn('title',r.snapshot());self.assertFalse(r.path.exists())

    def test_duck_fades_eighty_percent_then_restores_without_transport_changes(self):
        r=self.receiver;r.config['volume']=2;r.status='playing';r.silenced=False
        r.duck('a'*32,True)
        self.assertGreater(r.output_level(1024),.4)
        self.assertAlmostEqual(r.output_level(5292),.4)
        raw=array('h',[16000,-16000]).tobytes()
        self.assertEqual(list(array('h',scaled_pcm(raw,r.output_level(1024)))),[64,-64])
        self.assertFalse(r.held());self.assertFalse(r.silenced);self.assertEqual(list(r.commands),[])
        r.duck('a'*32,False);self.assertEqual(r.output_level(5292),2)
        r.duck('a'*32,True);self.now+=16
        self.assertEqual(r.output_level(5292),2,'Expired voice lease must release ducking')
        r.duck('a'*32,True);r.pause();r.duck('a'*32,False)
        self.assertTrue(r.silenced);self.assertNotIn('play',r.commands)

    def test_commands_are_bounded_and_cannot_be_shell_commands(self):
        r=self.receiver;r.process=Mock();r.process.poll.return_value=None
        for action,value in [('volume',101),('seek',-1),('shuffle','true'),('play\nshutdown',None)]:
            with self.assertRaises(ValueError):r.control(action,value)
        for _ in range(16):r.control('next')
        with self.assertRaises(Unavailable):r.control('next')
        self.assertEqual(len(r.commands),16);self.spawn.assert_not_called()


class LocalAuthorizationTests(unittest.TestCase):
    def test_local_settings_require_live_pairing_and_same_origin(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from threading import Thread
        import urllib.request
        import httpx
        from bridge import Bridge
        valid=[True];upstream_calls=[]
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                upstream_calls.append((self.path,self.headers.get('Authorization')))
                raw=b'{}';self.send_response(200 if valid[0] else 401);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        with TemporaryDirectory() as home:
            upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
            class LocalBridge(Bridge):pass
            LocalBridge.configuration={'url':f'http://127.0.0.1:{upstream.server_port}/display','credential':'test-device'}
            LocalBridge.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            LocalBridge.music=Spotify(home,devices=lambda:[])
            bridge=ThreadingHTTPServer(('127.0.0.1',0),LocalBridge)
            threads=[Thread(target=s.serve_forever,daemon=True) for s in (upstream,bridge)]
            for t in threads:t.start()
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{bridge.server_port}',trust_env=False) as client:
                    route='/v1/display/music/settings';body={**LocalBridge.music.config,'name':'Sample Echo'}
                    self.assertTrue(client.get(route).json()['supported'])
                    self.assertEqual(client.put(route,json=body,headers={'Origin':'https://untrusted.example','X-Echo-Request':'1'}).status_code,403)
                    self.assertEqual(client.put(route,json=body,headers={'X-Echo-Request':'1'}).status_code,200)
                    self.assertEqual(LocalBridge.music.config['name'],'Sample Echo')
                    valid[0]=False;body['name']='Denied change'
                    self.assertEqual(client.put(route,json=body,headers={'X-Echo-Request':'1'}).status_code,401)
                    self.assertEqual(LocalBridge.music.config['name'],'Sample Echo')
                    self.assertTrue(all(p=='/v1/display/session' and token=='Display test-device' for p,token in upstream_calls))
            finally:
                for s in (upstream,bridge):s.shutdown();s.server_close()
                for t in threads:t.join(2)
