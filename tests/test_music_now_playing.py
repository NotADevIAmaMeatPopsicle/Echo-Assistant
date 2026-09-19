import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock,patch
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.display_auth import allowed
from backend.lifecycle import Lifecycle
from backend.music import Music
from backend.music_commands import request,take,wire_command
from backend.music_now_playing import publish,snapshot,state_path,cover_url,track_url,Artwork


class NowPlayingTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.state={'status':'paused','title':'Private current title','artist':'An artist','album':'A record',
            'position_ms':3000,'duration_ms':120000,'cover':'https://i.scdn.co/image/'+'a'*40,
            'uri':'spotify:track:'+'b'*22,'shuffle':False,'repeat':'off','volume':50,
            'capabilities':['seek','volume','shuffle','repeat']}

    def test_current_state_expires_and_does_not_enter_diagnostics(self):
        publish(self.root,self.state);current=snapshot(self.root)
        self.assertEqual(current['title'],self.state['title']);self.assertTrue(current['artwork'].startswith('/v1/music/artwork/'))
        music=Music(self.root);music.title=self.state['title'];self.assertNotIn(self.state['title'],json.dumps(music.health()))
        with patch('backend.music_now_playing.time.time',return_value=time.time()+10):self.assertFalse(snapshot(self.root)['available'])
        music.close();self.assertFalse(state_path(self.root).exists())

    def test_progress_freezes_when_paused_and_advances_when_playing(self):
        with patch('backend.music_now_playing.time.time',return_value=100):publish(self.root,self.state)
        with patch('backend.music_now_playing.time.time',return_value=102):self.assertEqual(snapshot(self.root)['position_ms'],3000)
        with patch('backend.music_now_playing.time.time',return_value=100):publish(self.root,{**self.state,'status':'playing'})
        with patch('backend.music_now_playing.time.time',return_value=102):self.assertEqual(snapshot(self.root)['position_ms'],5000)

    def test_only_fixed_spotify_cover_and_track_urls_are_accepted(self):
        for value in ('https://localhost/x','https://i.scdn.co.evil/image/'+'a'*40,'http://i.scdn.co/image/'+'a'*40,
                      'https://i.scdn.co/image/'+'a'*40+'?token=x','https://user@i.scdn.co/image/'+'a'*40):
            self.assertEqual(cover_url(value),'')
        self.assertEqual(track_url('spotify:local:private-file'),'')
        with patch('urllib.request.build_opener') as network:
            with self.assertRaises(KeyError):Artwork().get(self.root,'a'*64)
            network.assert_not_called()

    def test_extended_commands_are_typed_bounded_and_generation_bound(self):
        for action,value in [('seek',-1),('volume',101),('volume',True),('seek','100'),('repeat','injected\nplay'),('shuffle',1),('play',2)]:
            with self.assertRaises(ValueError):wire_command(action,value)
        with Lifecycle(self.root) as lifecycle:
            (self.root/'local/voice-status.json').write_text(json.dumps({'updated_at':time.time(),'status':'armed','music':{'status':'paused'}}))
            publish(self.root,self.state)
            for action,value,expected in [('seek',42000,'seek 42000'),('volume',3,'volume 3'),('shuffle',True,'shuffle true'),('repeat','track','repeat track')]:
                request(self.root,action,value);self.assertEqual(take(self.root,lifecycle.identity),expected)
            with self.assertRaises(ValueError):request(self.root,'seek',130000)
            publish(self.root,{**self.state,'capabilities':[]})
            with self.assertRaises(ValueError):request(self.root,'volume',3)

    def test_cover_is_decoded_sanitized_cached_and_invalidated_on_track_change(self):
        from PIL import Image
        source=io.BytesIO();Image.new('RGB',(12,12),'blue').save(source,format='PNG')
        publish(self.root,self.state);key=snapshot(self.root)['artwork'].rsplit('/',1)[1]
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.headers.get_content_type.return_value='image/png';response.read.return_value=source.getvalue()
        with patch('urllib.request.build_opener') as network:
            network.return_value.open.return_value=response;art=Artwork()
            cover=art.get(self.root,key);self.assertTrue(cover.startswith(b'\xff\xd8'))
            self.assertEqual(art.get(self.root,key),cover);self.assertEqual(network.return_value.open.call_count,1)
            publish(self.root,{**self.state,'cover':''})
            with self.assertRaises(KeyError):art.get(self.root,key)
            self.assertIsNone(art.content)

    def test_event_metadata_and_remote_playback_changes_are_forwarded(self):
        music=Music(self.root);music.status='playing'
        events=[{'event':'receiver_ready','ui_version':'2'},
                {'event':'track_changed','name':'Song','artists':'Artist','album':'Album','covers':self.state['cover'],'uri':self.state['uri'],'duration_ms':'120000'},
                {'event':'seeked','position_ms':'42000'}, {'event':'shuffle_changed','shuffle':'true'},
                {'event':'repeat_changed','repeat':'true','repeat_track':'true'},{'event':'volume_changed','volume':'32768'}]
        music.socket=Mock();music.socket.recvfrom.side_effect=[(json.dumps({**e,'key':music.key}).encode(),None) for e in events]+[BlockingIOError()]
        music.poll();state=snapshot(self.root)
        self.assertEqual(state['title'],'Song');self.assertEqual(state['album'],'Album');self.assertEqual(state['repeat'],'track')
        self.assertTrue(state['shuffle']);self.assertEqual(state['volume'],50);self.assertGreaterEqual(state['position_ms'],42000)
        self.assertIn('seek',state['capabilities'])
        music.process=Mock(stdin=io.BytesIO());music.process.poll.return_value=None;music.command('seek 45000')
        self.assertEqual(music.process.stdin.getvalue(),b'seek 45000\n')

    def test_api_is_authenticated_and_validation_never_actuates(self):
        app=create_app('a'*40,runtime_root=self.root,deployment_mode='validation')
        with TestClient(app,base_url='http://127.0.0.1') as client:
            self.assertEqual(client.get('/v1/music/now-playing').status_code,401)
            headers={'Authorization':'Bearer '+'a'*40}
            publish(self.root,self.state)
            self.assertEqual(client.get('/v1/music/now-playing',headers=headers).json()['album'],'A record')
            self.assertEqual(client.post('/v1/music/control',headers=headers,json={'action':'shuffle','value':True}).status_code,409)
            self.assertEqual(client.post('/v1/music/control',headers=headers,json={'action':'seek','value':.5}).status_code,422)
        self.assertTrue(allowed('GET','/v1/music/now-playing'));self.assertTrue(allowed('GET','/v1/music/artwork/'+'a'*64))
        self.assertFalse(allowed('GET','/v1/music/artwork/https://elsewhere'))


if __name__=='__main__':unittest.main()
