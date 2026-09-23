"""Selection boundaries with a synthetic library; never stream or play sound."""
from copy import deepcopy
from concurrent.futures import Future
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.display_profiles import DisplayProfile
from backend.group_music import GroupMusic, GroupMusicUnavailable
from backend.music_library import MusicLibrary, LibraryRequest, LibraryPlay
from backend.linux_protection import LinuxProtector
from backend.settings import SettingsStore


class MusicLibraryTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.now=100
        self.rows=[{'player_id':p,'available':True,'provider':'sendspin','group_members':[],
                    'supported_features':[],'can_group_with':[]} for p in ('deck','mini','private')]
        self.track={'media_type':'track','name':'Synthetic song','uri':'library://track/123',
                    'available':True,'artists':[{'name':'Sample artist'}],
                    'metadata':{'private':'not returned'},'provider_mappings':[{'url':'secret://not-returned'}]}
        self.search={'tracks':[self.track]};self.queue=[{'queue_item_id':'stable-item','name':'Synthetic song','available':True}]
        def transport(request):
            body=json.loads(request.content);self.calls.append(body);cmd=body['command']
            result={'players/all':self.rows,'music/search':self.search,
                    'music/browse':[{'media_type':'folder','name':'Sample library','path':'library://tracks'}],
                    'player_queues/get':{'queue_id':'deck','items':60,'current_item':{'queue_item_id':'stable-item'}},
                    'player_queues/items':self.queue}.get(cmd,True)
            return httpx.Response(200,json=deepcopy(result))
        self.transport=httpx.MockTransport(transport)
        self.music=GroupMusic(None,None,transport=self.transport)
        self.config={'enabled':True,'url':'http://echo-music:8095','players':['deck','mini']}
        self.music.configure(self.config,'synthetic',0)
        self.library=MusicLibrary(self.music,clock=lambda:self.now)
        self.addCleanup(self.library.episode_pool.shutdown, wait=True)

    def shelves(self):
        playlists=[{'media_type':'playlist','name':name,'uri':'spotify://playlist/'+str(i)} for i,name in enumerate(
            ['Weekend','3. Focus','1. Favorites','2. Quiet','Walking'])]
        shows=[{'media_type':'podcast','item_id':str(i),'provider':'spotify-test','uri':'spotify-test://podcast/'+str(i),'name':name}
               for i,name in enumerate(['Alpha show','Beta show'])]
        browse={'root':[{'provider':'spotify','path':'spotify-test://'}],
                'spotify-test://':[{'item_id':key,'path':'spotify-test://'+key} for key in ['playlists','podcasts']],
                'spotify-test://playlists':playlists,'spotify-test://podcasts':shows}
        original=self.music.request
        def request(command,**args):
            if command=='music/browse':return deepcopy(browse[args['path']])
            return original(command,**args)
        self.music.request=request
        return shows

    def cached_episodes(self,show,episodes):
        future=Future();future.set_result(episodes)
        self.library.episode_jobs[(self.music.revision,show['provider'],show['item_id'])]=(self.now+300,future)

    def test_numbered_playlist_shelf_and_on_demand_rest(self):
        self.shelves()
        body=LibraryRequest(player='deck',source='spotify',collection='playlists')
        first=self.library.listing(body,'owner')
        self.assertEqual([r['name'] for r in first['items']],['1. Favorites','2. Quiet','3. Focus'])
        self.assertTrue(first['more']);self.assertEqual(first['next_offset'],3)
        rest=self.library.listing(body.model_copy(update={'offset':3}),'owner')
        self.assertEqual([r['name'] for r in rest['items']],['Walking','Weekend'])
        self.assertFalse(rest['more']);self.assertEqual(self.mutations(),[])

    def test_podcast_latest_order_new_feed_and_scoped_episode_play(self):
        shows=self.shelves()
        def episode(title,date,done=False):
            return {'media_type':'podcast_episode','name':title,'uri':'spotify://podcast_episode/'+title,
                    'metadata':{'release_date':date},'fully_played':done,'podcast':{'name':'Sample show'}}
        self.cached_episodes(shows[0],[episode('older','2026-08-01T00:00:00+00:00')])
        self.cached_episodes(shows[1],[episode('newest','2026-09-22T00:00:00+00:00'),episode('completed','2026-09-20',True)])
        body=LibraryRequest(player='deck',source='spotify',collection='podcasts',sort='latest')
        shows_result=self.library.listing(body,'owner')
        self.assertEqual([r['name'] for r in shows_result['items']],['Beta show','Alpha show'])
        self.assertEqual(shows_result['items'][0]['latest_episode'],'newest')
        selection=shows_result['items'][0]['selection']
        with self.assertRaises(HTTPException):self.library.listing(body.model_copy(update={'selection':selection}),'other')
        episodes=self.library.listing(body.model_copy(update={'selection':selection}),'owner')
        self.assertEqual(len(episodes['items']),2)
        feed=self.library.listing(body.model_copy(update={'collection':'new_episodes'}),'owner')
        self.assertEqual([r['name'] for r in feed['items']],['newest','older'])
        self.assertNotIn('spotify://',json.dumps(feed));self.assertEqual(self.mutations(),[])
        self.library.play(LibraryPlay(player='deck',selection=feed['items'][0]['selection']),'owner')
        self.assertEqual(self.mutations()[0]['args']['media'],'spotify://podcast_episode/newest')

    def test_episode_loading_failure_and_unknown_dates_remain_explicit(self):
        shows=self.shelves();pending=Future();failed=Future();failed.set_exception(RuntimeError('provider secret'))
        for show,future in zip(shows,[pending,failed]):
            self.library.episode_jobs[(self.music.revision,show['provider'],show['item_id'])]=(self.now+300,future)
        body=LibraryRequest(player='deck',source='spotify',collection='podcasts',sort='latest')
        result=self.library.listing(body,'owner')
        self.assertTrue(result['pending']);self.assertEqual(result['unavailable_shows'],1)
        self.assertEqual(len(result['items']),2);self.assertNotIn('secret',json.dumps(result))
        pending.set_result([])
        self.assertFalse(self.library.listing(body,'owner')['pending'])

    def select(self):
        return self.library.listing(LibraryRequest(player='deck',view='search',query='sample'),'owner')['items'][0]['selection']

    def mutations(self):
        return [c for c in self.calls if c['command'] in {'player_queues/play_media','player_queues/play_index'}]

    def test_browsing_is_silent_and_uris_are_not_exposed(self):
        result=self.library.listing(LibraryRequest(player='deck',view='search',query='sample'),'owner')
        serialized=json.dumps(result)
        self.assertNotIn('library://',serialized);self.assertNotIn('secret',serialized)
        self.assertEqual(result['items'][0]['artist'],'Sample artist');self.assertEqual(self.mutations(),[])
        self.assertEqual(self.calls[-1]['args']['media_types'],['track','album','playlist','radio'])

    def test_spotify_search_filters_provider(self):
        self.library.listing(LibraryRequest(player='deck',view='search',query='sample',source='spotify'),'owner')
        self.assertEqual(self.calls[-1]['args']['providers'],['spotify'])
        self.assertEqual(self.mutations(),[])

    def test_selection_is_bound_to_principal_destination_and_expiry(self):
        choice=self.select()
        for principal,player in [('other','deck'),('owner','mini')]:
            with self.assertRaises(HTTPException):self.library.play(LibraryPlay(player=player,selection=choice),principal)
        self.now+=601
        with self.assertRaises(HTTPException):self.library.play(LibraryPlay(player='deck',selection=choice),'owner')
        self.assertEqual(self.mutations(),[])

    def test_membership_permission_and_validation_changes_deny_play(self):
        choice=self.select();self.rows[0]['group_members']=['mini']
        with self.assertRaises(HTTPException):self.library.play(LibraryPlay(player='deck',selection=choice),'owner')
        self.rows[0]['group_members']=[];self.music.configure(self.config,None,1)
        with self.assertRaises(HTTPException):self.library.play(LibraryPlay(player='deck',selection=choice),'owner')
        choice=self.select();self.music.actions_enabled=False
        with self.assertRaises(PermissionError):self.library.play(LibraryPlay(player='deck',selection=choice),'owner')
        self.music.actions_enabled=True;self.rows[2]['synced_to']='deck'
        with self.assertRaises(PermissionError):self.library.play(LibraryPlay(player='deck',selection=choice),'owner')
        self.assertEqual(self.mutations(),[])

    def test_explicit_play_once_and_uncertain_response_not_retried(self):
        choice=self.select();body=LibraryPlay(player='deck',selection=choice)
        self.library.play(body,'owner')
        self.assertEqual(self.mutations()[0]['args'],{'queue_id':'deck','media':'library://track/123','option':'replace'})
        with self.assertRaises(HTTPException):self.library.play(body,'owner')
        self.assertEqual(len(self.mutations()),1)
        choice=self.select();original=self.music.request
        def fail(command,**args):
            if command=='player_queues/play_media':raise GroupMusicUnavailable('Uncertain response')
            return original(command,**args)
        with patch.object(self.music,'request',side_effect=fail):
            with self.assertRaises(GroupMusicUnavailable):self.library.play(LibraryPlay(player='deck',selection=choice),'owner')
        with self.assertRaises(HTTPException):self.library.play(LibraryPlay(player='deck',selection=choice),'owner')

    def test_queue_uses_stable_item_id_and_folder_is_not_playable(self):
        result=self.library.listing(LibraryRequest(player='deck',view='queue',offset=50),'owner')
        self.assertTrue(result['items'][0]['current']);self.assertTrue(result['more'])
        self.assertEqual(self.calls[-1]['args'],{'queue_id':'deck','limit':50,'offset':50})
        self.library.play(LibraryPlay(player='deck',selection=result['items'][0]['selection']),'owner')
        self.assertEqual(self.mutations()[0]['args'],{'queue_id':'deck','index':'stable-item'})
        folder=self.library.listing(LibraryRequest(player='deck'),'owner')['items'][0]['selection']
        with self.assertRaises(ValueError):self.library.play(LibraryPlay(player='deck',selection=folder),'owner')
        self.library.listing(LibraryRequest(player='deck',selection=folder),'owner')
        self.assertEqual(self.calls[-1]['args']['path'],'library://tracks')

    def test_malformed_and_unavailable_items_are_not_playable(self):
        self.track['available']=False
        self.assertIsNone(self.select())
        self.search={'tracks':'bad'}
        with self.assertRaises(GroupMusicUnavailable):self.select()
        self.rows[0]['synced_to']='mini'
        with self.assertRaises(ValueError):self.library.listing(LibraryRequest(player='deck'),'owner')
        self.assertEqual(self.mutations(),[])

    def test_display_api_and_guest_boundary(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        key=Path(temporary.name)/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
        token='synthetic-owner-'*3;app=create_app(token,settings_store=SettingsStore(protector=LinuxProtector(key)));owner={'Authorization':'Bearer '+token}
        with TestClient(app) as client:
            app.state.group_music.transport=self.transport
            app.state.group_music.configure(self.config,'synthetic',0)
            code=client.post('/v1/displays/pairing',headers=owner,json={'name':'Sample Deck'}).json()['code']
            device=client.post('/v1/displays/enroll',json={'code':code}).json();display={'Authorization':'Display '+device['credential']}
            body={'player':'deck','view':'search','query':'sample'}
            self.assertEqual(client.post('/v1/music/groups/library',json=body).status_code,401)
            result=client.post('/v1/music/groups/library',headers=display,json=body);self.assertEqual(result.status_code,200,result.text)
            selection=result.json()['items'][0]['selection']
            guest=client.put('/v1/displays/'+device['id']+'/profile',headers=owner,json={'revision':0,'profile':DisplayProfile(mode='guest').model_dump()})
            self.assertEqual(guest.status_code,200,guest.text)
            self.assertEqual(client.post('/v1/music/groups/library',headers=display,json=body).status_code,403)
            self.assertEqual(client.post('/v1/music/groups/library/play',headers=display,json={'player':'deck','selection':selection}).status_code,403)
            self.assertEqual(self.mutations(),[])


if __name__=='__main__':unittest.main()
