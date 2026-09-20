"""Mini sessions in memory: never connects to a real server or audio device."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from backend.group_music import GroupMusic,GroupMusicConfig,GroupMusicUnavailable
from backend.round_group_music import RoundGroupMusic,ForegroundWire,canonical_player,player_identity


class RoundGroupTests(unittest.TestCase):
    def setUp(self):
        self.now=100.;self.writes=[]
        self.group=RoundGroupMusic(None,'02:00:00:00:00:01',self.writes.append,clock=lambda:self.now,autostart=False)

    def connected(self):
        self.group.receive('STATUS timed_audio=1')
        self.group.publish(phase='ready',connected=True,server_clock=True)
        self.group.sender.device_clock.quality_us=500;self.group.sender.device_clock.updated=self.now
        self.group.pump('armed');self.writes.clear()

    def start(self):
        self.group.stream('start');self.group.audio(b'\1\0'*256,round(self.now*1e6)+500000)
        self.group.pump('armed');self.assertTrue(self.group.active)

    def test_defaults_and_names_do_not_enable_player(self):
        self.assertFalse(GroupMusicConfig().round_enabled)
        self.assertEqual(GroupMusicConfig().round_volume,2)
        for data in ({'round_volume':21},{'round_volume':True},{'round_latency_ms':201},{'round_name':'Bad\nName'}):
            with self.assertRaises(ValidationError):GroupMusicConfig(**data)
        self.group.pump('armed');self.assertEqual(self.writes,[])
        self.group.receive('STATUS timed_audio=1');self.group.pump('armed');self.assertEqual(self.writes,[])
        self.assertEqual(player_identity('02-00-00-00-00-01'),self.group.identity)
        with self.assertRaises(ValueError):player_identity('not-a-device')

    def test_foreground_commands_stop_first_and_discard_held_audio(self):
        self.connected();wire=ForegroundWire(SimpleNamespace(write=self.writes.append),self.group)
        for command in (b'WAKE 10\n',b'AUDIO_BEGIN 12 V 96000\n',b'VOICE_THINKING\n',b'CHIME\n',
                        b'CALL_STATE abc incoming 1 0 Kitchen\n',b'VOICE_OFF\n'):
            self.group.pump('armed');self.start();session=self.group.sender.session
            wire.write(command)
            self.assertEqual(self.writes[-2:], [f'GROUP_STOP {session}\n'.encode(),command])
            self.group.audio(b'\0'*512,round(self.now*1e6)+600000)
            self.group.pump('listening');self.assertFalse(self.group.active);self.assertFalse(self.group.pcm)
        self.group.pump('armed');self.assertFalse(self.group.active)
        self.start();session=self.group.sender.session
        wire.write(b'VOICE_PING\nCALL_STATE - idle 1 0 -\n')
        self.assertEqual(self.group.sender.session,session)

    def test_focus_priority_server_expiry_and_new_audio_resume(self):
        self.connected();self.start()
        self.group.pump('armed',spotify_busy=True);self.assertFalse(self.group.active);self.assertFalse(self.group.selected)
        self.group.audio(b'\0'*512,round(self.now*1e6)+500000)
        self.group.pump('armed');self.assertFalse(self.group.active)
        self.start();self.group.pump('armed',calls_busy=True);self.assertFalse(self.group.active)
        self.group.pump('armed');self.start();self.now+=2.1
        self.group.pump('armed');self.assertFalse(self.group.active)

    def test_clear_disconnect_bounds_gain_and_content_free_status(self):
        self.connected();self.start();self.group.publish(volume=100,ceiling=2)
        self.group.pump('armed');self.assertEqual(self.group.sender.gain,2)
        self.group.publish(muted=True);self.group.pump('armed');self.assertEqual(self.group.sender.gain,0)
        self.group.stream('clear');self.group.pump('armed');self.assertFalse(self.group.active)
        self.group.title='PRIVATE TITLE';self.group.artist='PRIVATE ARTIST'
        for i in range(150):self.group.audio(b'\0'*8192,round(self.now*1e6)+500000)
        self.assertLessEqual(self.group.buffered,196608);self.assertLessEqual(len(self.group.pcm),64)
        self.assertGreater(self.group.dropped,0);self.assertNotIn('PRIVATE',json.dumps(self.group.health()))
        self.group.stream('disconnect');self.group.pump('armed');self.assertFalse(self.group.active);self.assertFalse(self.group.pcm)

    def test_wire_rejection_does_not_take_down_voice_or_retry_old_pcm(self):
        self.connected();self.start();self.group.receive('ERROR group_invalid')
        self.assertFalse(self.group.active);self.assertEqual(self.group.errors,1)
        self.group.pump('armed');self.assertFalse(self.group.active)
        self.now+=2.1;self.group.publish(connected=True,server_clock=True);self.group.pump('armed')
        self.assertFalse(self.group.active)

    def test_controls_resolve_protocol_and_enforce_all_shared_outputs(self):
        rows=[{'player_id':'actual-mini','provider':'universal_player','available':True,'playback_state':'playing',
               'supported_features':[],'group_members':[],
               'output_protocols':[{'protocol_domain':'sendspin','output_protocol_id':self.group.identity}]}]
        writes=[]
        def transport(request):
            body=json.loads(request.content)
            if body['command']=='players/all':return httpx.Response(200,json=deepcopy(rows))
            writes.append(body);return httpx.Response(200,json=True)
        music=GroupMusic(None,None,transport=httpx.MockTransport(transport))
        music.configure({'enabled':True,'round_enabled':True,'url':'http://echo-music:8095','players':['actual-mini']},'synthetic-token',0)
        self.group.loader=lambda:music
        self.assertEqual(self.group.control('toggle')[0],'accepted')
        self.assertEqual(writes[-1]['command'],'players/cmd/stop');self.assertEqual(writes[-1]['args'],{'player_id':'actual-mini'})
        rows[0]['group_members']=['not-shared']
        self.assertEqual(self.group.control('next')[0],'unavailable');self.assertEqual(len(writes),1)
        rows[0]['group_members']=[];rows[0]['output_protocols']=[];rows[0]['name']='Echo Mini'
        self.assertEqual(self.group.control('play')[0],'unavailable');self.assertEqual(len(writes),1)
        with self.assertRaises(GroupMusicUnavailable):canonical_player({'one':rows[0]},self.group.identity)


class RoundMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_opt_in_missing_runtime_and_revocation(self):
        music=GroupMusic(None,None)
        group=RoundGroupMusic(None,'020000000001',lambda _:None,loader=lambda:music,autostart=False)
        group.receive('STATUS timed_audio=1')
        monitor=asyncio.create_task(group._monitor())
        try:
            await asyncio.sleep(.1);self.assertEqual(group.state['phase'],'disabled')
            music.configure({'enabled':True,'round_enabled':True,'url':'http://echo-music:8095'},'synthetic-token',0)
            with patch('backend.round_group_music.version',return_value='wrong-version'):
                await asyncio.sleep(.6);self.assertEqual(group.state['phase'],'runtime_required')
            async def fake_connect(*_):
                group.publish(connected=True,server_clock=True)
                await asyncio.Future()
            with patch('backend.round_group_music.version',return_value='6.0.1'),patch.dict('sys.modules',{'aiohttp':SimpleNamespace()}),patch.object(group,'_connect',fake_connect):
                await asyncio.sleep(.6);self.assertTrue(group.state['connected'])
                music.configure({**music.config.model_dump(),'round_enabled':False},None,1)
                await asyncio.sleep(.6);self.assertFalse(group.state['connected']);self.assertEqual(group.state['phase'],'disabled')
        finally:
            group.stopped.set();await monitor


if __name__=='__main__':unittest.main()
