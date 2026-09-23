"""Synthetic Music Assistant transport; tests never address speakers or play audio."""
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import create_app
from backend.display_profiles import DisplayProfile
from backend.group_music import GroupMusic,GroupMusicConfig,GroupMusicUnavailable
from backend.linux_protection import LinuxProtector
from backend.settings import SettingsStore


class GroupMusicTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        key=self.root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600);self.protector=LinuxProtector(key)
        self.rows=[{'player_id':key,'name':key,'provider':'sendspin','available':True,'playback_state':'paused',
                    'supported_features':['pause','volume_set','volume_mute','set_members'],
                    'can_group_with':['sendspin'],'group_members':[],'synced_to':None} for key in ('deck','mini','hidden')]
        self.calls=[]
        def transport(request):
            self.assertEqual(request.headers['Authorization'],'Bearer synthetic-token')
            body=json.loads(request.content);self.calls.append(body)
            return httpx.Response(200,json=deepcopy(self.rows) if body['command']=='players/all' else True)
        self.transport=httpx.MockTransport(transport)
        self.music=GroupMusic(self.root,self.protector,transport=self.transport)
        self.config={'enabled':True,'url':'http://echo-music:8095','players':['deck','mini'],'max_volume':3}
        self.music.configure(self.config,'synthetic-token',0)

    def writes(self):return [r for r in self.calls if r['command']!='players/all']

    def test_encrypted_persistence_and_origin_change_never_reuses_token(self):
        self.assertNotIn(b'synthetic-token',self.music.path.read_bytes())
        self.assertNotIn('synthetic-token',json.dumps(self.music.settings()))
        loaded=GroupMusic(self.root,self.protector,transport=self.transport)
        self.assertEqual(loaded.snapshot()['status'],'available')
        with self.assertRaises(ValueError):loaded.configure({**self.config,'url':'http://127.0.0.1:8095'},None,1)
        with patch.object(Path,'replace',side_effect=OSError):
            with self.assertRaises(GroupMusicUnavailable):loaded.configure(self.config,None,1)
        self.assertEqual(loaded.settings()['revision'],1)

    def test_private_origins_only(self):
        for url in ('http://169.254.169.254','http://0.0.0.0','http://224.0.0.1','https://example.com','http://10.0.0.1/path','http://user@localhost','file:///tmp'):
            with self.subTest(url=url),self.assertRaises(ValidationError):GroupMusicConfig(url=url)
        for url in ('http://echo-music:8095','http://localhost:8095','http://192.168.10.4:8095','https://[fd00::5]'):
            self.assertEqual(GroupMusicConfig(url=url).url,url)

    def test_one_membership_dispatch_no_play_or_volume_change(self):
        snapshot=self.music.snapshot();self.assertEqual({p['id'] for p in snapshot['items']},{'deck','mini'})
        self.assertEqual(len(self.music.snapshot(discovery=True)['items']),3)
        self.music.members('deck',['mini'],1,snapshot['binding'])
        self.assertEqual(self.writes(),[{'message_id':'echo','command':'players/cmd/set_members','args':{
            'target_player':'deck','player_ids_to_add':['mini'],'player_ids_to_remove':[]}}])

    def test_stale_binding_and_revision_cannot_actuate(self):
        snapshot=self.music.snapshot();self.rows[1]['available']=False
        with self.assertRaises(HTTPException) as cm:self.music.members('deck',['mini'],1,snapshot['binding'])
        self.assertEqual(cm.exception.status_code,409)
        with self.assertRaises(HTTPException):self.music.control('play','deck',None,0)
        self.assertEqual(self.writes(),[])

    def test_unshared_reverse_membership_blocks_transport_and_grouping(self):
        self.rows[2]['synced_to']='deck'
        snapshot=self.music.snapshot();self.assertTrue(snapshot['items'][0]['blocked'])
        with self.assertRaises(PermissionError):self.music.control('play','deck',None,1)
        with self.assertRaises(PermissionError):self.music.members('deck',[],1,snapshot['binding'])
        self.assertEqual(self.writes(),[])

    def test_compatible_group_members_can_be_retained_or_removed_offline(self):
        self.rows[0]['group_members']=['deck','mini'];self.rows[1].update(synced_to='deck',group_members=['deck','mini'],available=False)
        snapshot=self.music.snapshot();self.music.members('deck',['mini'],1,snapshot['binding']);self.assertEqual(self.writes(),[])
        self.music.members('deck',[],1,snapshot['binding'])
        self.assertEqual(self.writes()[0]['args']['player_ids_to_remove'],['mini'])

    def test_incompatible_players_and_other_groups_are_not_moved(self):
        self.rows[0]['can_group_with']=[]
        with self.assertRaises(ValueError):self.music.members('deck',['mini'],1,self.music.snapshot()['binding'])
        self.rows[0]['can_group_with']=['sendspin'];self.rows[1]['synced_to']='hidden'
        with self.assertRaises(PermissionError):self.music.members('deck',['mini'],1,self.music.snapshot()['binding'])
        self.assertEqual(self.writes(),[])

    def test_volume_limit_validation_mode_and_no_request_retry(self):
        with self.assertRaises(ValueError):self.music.control('volume','deck',4,1)
        self.music.control('volume','deck',2,1);self.assertEqual(self.writes()[0]['args']['volume_level'],2)
        self.music.actions_enabled=False
        with self.assertRaises(PermissionError):self.music.control('play','deck',None,1)
        count=0
        def fail(request):
            nonlocal count;count+=1;raise httpx.ReadTimeout('private upstream details',request=request)
        self.music.transport=httpx.MockTransport(fail)
        with self.assertRaises(GroupMusicUnavailable) as cm:self.music.request('players/cmd/play',player_id='deck')
        self.assertNotIn('private upstream',str(cm.exception));self.assertEqual(count,1)

    def test_library_pause_preserves_track_when_transport_becomes_idle(self):
        player=self.rows[0]
        player.update(active_source='deck',playback_state='playing',supported_features=['volume_set'],
            current_media={'source_id':'deck','queue_item_id':'track-one','title':'Sample song',
                'artist':'Sample artist','duration':180,'elapsed_time':43})
        self.assertIn('pause',self.music.snapshot()['items'][0]['features'])
        self.music.control('pause','deck',None,1)
        self.assertEqual(self.writes()[-1]['command'],'player_queues/pause')
        self.assertEqual(self.writes()[-1]['args'],{'queue_id':'deck'})
        # Sendspin stops its transport for pause; the saved queue position remains.
        player['playback_state']='idle'
        item=self.music.snapshot()['items'][0]
        self.assertEqual((item['state'],item['title'],item['position_ms']),('paused','Sample song',43000))
        self.music.control('play','deck',None,1)
        self.assertEqual(self.writes()[-1]['command'],'player_queues/play')
        self.assertEqual(self.music.snapshot()['items'][0]['state'],'idle')
        self.assertEqual(self.music.snapshot()['items'][0]['title'],'Sample song')

    def test_pause_marker_does_not_follow_a_different_queue_item_or_source(self):
        player=self.rows[0]
        player.update(active_source='deck',playback_state='playing',supported_features=[],
            current_media={'source_id':'deck','queue_item_id':'track-one'})
        self.music.control('pause','deck',None,1)
        player['playback_state']='idle';player['current_media']['queue_item_id']='track-two'
        self.assertEqual(self.music.snapshot()['items'][0]['state'],'idle')
        player['active_source']='external'
        with self.assertRaises(ValueError):self.music.control('pause','deck',None,1)

    def test_redirects_and_malformed_inventory_fail_closed(self):
        calls=[]
        def redirect(request):calls.append(str(request.url));return httpx.Response(302,headers={'location':'https://example.com/'})
        self.music.transport=httpx.MockTransport(redirect)
        with self.assertRaises(GroupMusicUnavailable):self.music.snapshot()
        self.assertEqual(calls,['http://echo-music:8095/api'])
        self.music.transport=self.transport;self.rows[0]['supported_features']={'volume_set':'bad'}
        with self.assertRaises(GroupMusicUnavailable):self.music.snapshot()

    def test_owner_household_guest_and_anonymous_api_boundaries(self):
        app=create_app('owner-token-'*4,settings_store=SettingsStore(protector=self.protector))
        owner={'Authorization':'Bearer '+'owner-token-'*4}
        with TestClient(app) as client:
            app.state.group_music.transport=self.transport
            # Routes retain the installed store; configure that instance, not a replacement.
            app.state.group_music.configure(self.config,'synthetic-token',0)
            code=client.post('/v1/displays/pairing',headers=owner,json={'name':'Sample display'}).json()['code']
            paired=client.post('/v1/displays/enroll',json={'code':code}).json()
            display={'Authorization':'Display '+paired['credential']}
            self.assertEqual(client.get('/v1/music/groups').status_code,401)
            self.assertEqual(client.get('/v1/music/groups',headers=display).status_code,200)
            self.assertEqual(client.get('/v1/music/groups/discovery',headers=display).status_code,403)
            self.assertEqual(client.get('/v1/music/groups/settings',headers=display).status_code,403)
            r=client.put('/v1/displays/'+paired['id']+'/profile',headers=owner,json={'revision':0,'profile':DisplayProfile(mode='guest').model_dump()})
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(client.get('/v1/music/groups',headers=display).status_code,403)
            self.assertEqual(client.post('/v1/music/groups/control',headers=display,json={'revision':1,'player':'deck','action':'play'}).status_code,403)
            self.assertEqual(self.writes(),[])


if __name__=='__main__':unittest.main()
