import sys,unittest,json,os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlsplit,parse_qs,urlencode
from unittest.mock import Mock
import httpx
from fastapi import HTTPException,FastAPI
from fastapi.testclient import TestClient
from backend.radio_directory import RadioDirectory,install as install_radio
from backend.spotify_account import SpotifyAccount,SetupValues,install as install_spotify
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from local_library import LocalLibrary,byte_range
from bridge import Bridge

class MediaLibraryTests(unittest.TestCase):
 def test_directory_sanitizes_caches_and_retries(self):
  calls=[]
  def transport(r):
   calls.append(r)
   if len(calls)==1:return httpx.Response(503)
   values=[{'name':'Jazz','url_resolved':'https://radio.example/live','hls':0,'lastcheckok':1},
           {'name':'Private','url':'https://127.0.0.1/audio','lastcheckok':1},
           {'name':'HLS','url':'https://radio.example/hls','hls':1,'lastcheckok':1},
           {'name':'Unverified','url':'https://radio.example/no'}]
   return httpx.Response(200,json=values)
  d=RadioDirectory(httpx.MockTransport(transport));result=d.search('Jazz','US','jazz')
  self.assertEqual([i['name'] for i in result['items']],['Jazz']);d.search('Jazz','US','jazz');self.assertEqual(len(calls),2)
  self.assertEqual(calls[-1].url.params['countrycode'],'US')
  with self.assertRaises(ValueError):d.search(country='XYZ')
 def test_directory_auth(self):
  app=FastAPI()
  def deny():raise HTTPException(401)
  install_radio(app,deny)
  with TestClient(app) as client:self.assertEqual(client.get('/v1/radio/stations').status_code,401)
 def test_library_playlists_ranges_and_changed_files(self):
  with TemporaryDirectory() as tmp:
   lib=LocalLibrary(tmp);folder=lib.root/'Album';folder.mkdir();song=folder/'Song.mp3';song.write_bytes(b'0123456789')
   playlist=lib.root/'Favorites.m3u';playlist.write_text('#EXTM3U\nAlbum/Song.mp3\n../../outside.mp3\nhttps://outside.test/a.mp3\n')
   snap=lib.scan();self.assertEqual(len(snap['tracks']),1);self.assertEqual(snap['playlists'][0]['missing'],2)
   key=snap['tracks'][0]['id'];self.assertEqual(snap['playlists'][0]['tracks'],[key])
   stream,size,kind=lib.open_track(key)
   with stream:self.assertEqual(stream.read(),b'0123456789')
   self.assertEqual(byte_range('bytes=2-5',size),(2,5,True));self.assertEqual(byte_range('bytes=-3',size),(7,9,True))
   for bad in ['bytes=10-','bytes=-0','bytes=4-2','bytes=0-1,3-4','other']:
    with self.assertRaises(ValueError):byte_range(bad,size)
   with self.assertRaises(FileNotFoundError):lib.open_track('../outside.mp3')
   song.write_bytes(b'changed');
   with self.assertRaises(FileNotFoundError):lib.open_track(key)
   old=snap['revision'];playlist.write_text('');self.assertNotEqual(lib.scan(force=True)['revision'],old)
 def test_symlinks_never_indexed(self):
  with TemporaryDirectory() as tmp:
   lib=LocalLibrary(tmp);outside=Path(tmp)/'private.mp3';outside.write_bytes(b'private')
   try:(lib.root/'leak.mp3').symlink_to(outside)
   except OSError:self.skipTest('Symlink creation unavailable')
   self.assertEqual(lib.scan()['tracks'],[])
 def test_local_bridge_range_head_and_guest_boundary(self):
  with TemporaryDirectory() as tmp:
   lib=LocalLibrary(tmp);(lib.root/'Song.mp3').write_bytes(b'0123456789');key=lib.scan()['tracks'][0]['id']
   access={'mode':'household'}
   class TestBridge(Bridge):
    library=lib
    configuration={'url':'https://example.test/display','credential':'test'}
    def access_profile(self,*a):return access,0
    def log_message(self,*a):pass
   server=ThreadingHTTPServer(('127.0.0.1',0),TestBridge);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}',trust_env=False) as c:
     path='/v1/display/library/stream/'+key
     self.assertEqual(c.get('/v1/display/library').json()['tracks'][0]['id'],key)
     r=c.get(path,headers={'Range':'bytes=2-5'});self.assertEqual((r.status_code,r.content),(206,b'2345'))
     self.assertEqual(c.head(path).headers['content-length'],'10')
     self.assertEqual(c.get(path,headers={'Range':'bytes=12-'}).status_code,416)
     access['mode']='guest';self.assertEqual(c.get(path).status_code,403)
   finally:server.shutdown();server.server_close();thread.join(2)

class SpotifyFlowTests(unittest.TestCase):
 def setUp(self):
  self.now=100;self.id='a'*32;self.sent=[]
  def transport(r):self.sent.append(r);return httpx.Response(200,text='ok')
  self.music=SimpleNamespace(revision=1,config=SimpleNamespace(url='http://echo-music:8095'),transport=httpx.MockTransport(transport),request=Mock())
  self.account=SpotifyAccount(self.music,clock=lambda:self.now)
  self.url='https://accounts.spotify.com/authorize?'+urlencode({'redirect_uri':'https://music-assistant.io/callback','state':'http://echo-music:8095/setup_flow/callback/'+self.id,'code_challenge':'test','client_id':'public'})
  self.step={'type':'external','flow_id':self.id,'step_id':'authenticate','url':self.url,'entries':[]}
  self.music.request.return_value=self.step
  self.f=dict(origin='https://echo.example',revision=1,expires=1300,id=self.id,step=self.step,nonce=None,callback_step=None,used=False,error=None,busy=False)
  self.account.flow=self.f
 def test_callback_is_bound_one_use_and_pkce_preserved(self):
  output=self.account.get();params=parse_qs(urlsplit(output['url']).query)
  self.assertEqual(params['code_challenge'],['test']);self.assertEqual(params['redirect_uri'],['https://music-assistant.io/callback'])
  self.assertNotIn('echo-music',output['url'])
  with self.assertRaises(HTTPException):self.account.callback('wrong',{'code':'test-code'})
  self.account.callback(self.f['nonce'],{'code':'test-code','evil':'ignored'})
  self.assertEqual(self.sent[0].url.path,'/setup_flow/callback/'+self.id);self.assertEqual(dict(self.sent[0].url.params),{'code':'test-code'})
  with self.assertRaises(HTTPException):self.account.callback(self.f['nonce'],{'code':'again'})
  self.assertEqual(len(self.sent),1)
 def test_expiry_server_change_and_step_change_block_callback(self):
  self.account.get();self.music.revision=2
  with self.assertRaises(HTTPException):self.account.callback(self.f['nonce'],{'code':'x'})
  self.music.revision=1;self.now=1301
  with self.assertRaises(HTTPException):self.account.get()
  self.now=100;self.music.request.return_value={'type':'form'}
  with self.assertRaises(HTTPException):self.account.callback(self.f['nonce'],{'code':'x'})
  self.assertFalse(self.sent)
 def test_manual_playback_step_keeps_clickable_signin_link(self):
  self.f['step']={'type':'form','step_id':'playback_browser','description':'[try again](https://accounts.spotify.com/authorize?response_type=code&scope=streaming)','entries':[]}
  out=self.account.safe_step(self.f)
  self.assertEqual(out['url'],'https://accounts.spotify.com/authorize?response_type=code&scope=streaming')
  self.assertNotIn('https://',out['description'])
 def test_finished_flow_remains_complete_after_provider_removes_session(self):
  self.f['step']={'type':'finish','step_id':'finish','title':'Connected'}
  self.music.request.side_effect=AssertionError('Finished provider flow must not be polled')
  self.assertEqual(self.account.get()['type'],'finish')
  self.account.abort();self.assertIsNone(self.account.flow)
 def test_setup_requires_owner_and_display_cannot_start_it(self):
  app=FastAPI()
  def owner():raise HTTPException(403)
  install_spotify(app,self.music,lambda:'display:test',owner,lambda fn:fn())
  with TestClient(app) as c:
   self.assertEqual(c.post('/v1/music/spotify/setup',json={}).status_code,403)
   self.assertEqual(c.get('/v1/music/spotify/setup').status_code,403)
   self.assertEqual(c.post('/v1/music/spotify/setup/step',json={'step':'x','values':{}}).status_code,403)
 def test_secret_values_not_returned_and_unknown_fields_rejected(self):
  self.f['step']={'type':'form','step_id':'playback','entries':[{'key':'playback_callback_url','type':'string','value':'secret-code'}, {'key':'refresh_token','value':'secret-token'}]}
  result=self.account.safe_step(self.f);self.assertNotIn('secret',json.dumps(result));self.assertEqual(len(result['entries']),1)
  with self.assertRaises(ValueError):self.account.submit(SetupValues(step='playback',values={'refresh_token':'bad'}))
  with self.assertRaises(HTTPException):self.account.submit(SetupValues(step='old',values={}))

if __name__=='__main__':unittest.main()
