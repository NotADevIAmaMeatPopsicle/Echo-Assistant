"""Actual pinned SDK against a synthetic loopback server; PCM never leaves memory."""
import asyncio
import contextlib
from importlib.metadata import PackageNotFoundError,version
import struct
import unittest

from backend.group_music import GroupMusicConfig
from backend.round_group_music import RoundGroupMusic

try:SDK_AVAILABLE=version('aiosendspin')=='6.0.1'
except PackageNotFoundError:SDK_AVAILABLE=False


@unittest.skipUnless(SDK_AVAILABLE,'Optional Mini SDK runtime is not installed')
class MiniProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp import web
        self.web=web;self.messages=[];self.writes=[];self.ws=None;self.redirect_hits=0
        self.group=RoundGroupMusic(None,'020000000001',self.writes.append,autostart=False)
        self.group.receive('STATUS timed_audio=1')
        self.app=web.Application();self.app.router.add_get('/sendspin',self.handler)
        self.runner=web.AppRunner(self.app);await self.runner.setup()
        self.site=web.TCPSite(self.runner,'127.0.0.1',0);await self.site.start()
        port=self.site._server.sockets[0].getsockname()[1]
        self.config=GroupMusicConfig(enabled=True,round_enabled=True,url=f'http://127.0.0.1:{port}')
        self.task=None

    async def asyncTearDown(self):
        self.group.stopped.set()
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await self.task
        self.group.close();await self.runner.cleanup()

    async def handler(self,request):
        ws=self.web.WebSocketResponse();await ws.prepare(request);self.ws=ws
        async for message in ws:
            if message.type!=self.web.WSMsgType.TEXT:continue
            data=message.json();self.messages.append(data)
            if data['type']=='auth':
                self.assertEqual(data['token'],'synthetic-token');await ws.send_json({'type':'auth_ok'})
            elif data['type']=='client/hello':
                await ws.send_json({'type':'server/hello','payload':{'server_id':'synthetic','name':'Test Music',
                    'version':1,'active_roles':['player@v1','metadata@v1'],'connection_reason':'playback'}})
            elif data['type']=='client/time':
                tick=round(self.group.clock()*1e6)
                await ws.send_json({'type':'server/time','payload':{'client_transmitted':data['payload']['client_transmitted'],
                    'server_received':tick,'server_transmitted':tick}})
        return ws

    async def wait_until(self,predicate):
        for _ in range(150):
            if predicate():return
            self.group.sender.device_clock.quality_us=500;self.group.sender.device_clock.updated=self.group.clock()
            self.group.pump('armed')
            if self.group.sender.session and not self.group.sender.capacity:
                self.group.receive(f'EVENT group_ready={self.group.sender.session} capacity=256')
            await asyncio.sleep(.02)
        self.fail('Synthetic receiver did not reach the expected state: '+str(self.group.health()))

    async def test_handshake_timing_pcm_volume_metadata_and_clear(self):
        from aiosendspin.models import BinaryMessageType
        self.task=asyncio.create_task(self.group._connect(self.config,'synthetic-token'))
        await self.wait_until(lambda:self.group.state['server_clock'])
        hello=next(m for m in self.messages if m['type']=='client/hello')['payload']
        self.assertEqual(hello['supported_roles'],['player@v1','metadata@v1'])
        self.assertNotIn('controller@v1',hello['supported_roles'])
        self.assertEqual(hello['player@v1_support']['supported_formats'],[{'codec':'pcm','channels':1,'sample_rate':48000,'bit_depth':16}])
        await self.ws.send_json({'type':'server/command','payload':{'player':{'command':'volume','volume':100}}})
        await self.ws.send_json({'type':'server/state','payload':{'metadata':{'timestamp':round(self.group.clock()*1e6),'title':'Synthetic song','artist':'Fixture'}}})
        await self.ws.send_json({'type':'stream/start','payload':{'player':{'codec':'pcm','sample_rate':48000,'channels':1,'bit_depth':16}}})
        await self.wait_until(lambda:self.group.state['playing'])
        await self.ws.send_bytes(struct.pack('>Bq',BinaryMessageType.AUDIO_CHUNK.value,round(self.group.clock()*1e6)+700000)+b'\1\0'*256)
        await self.wait_until(lambda:self.group.sender.sent>0)
        self.assertEqual(self.group.sender.gain,2);self.assertEqual(self.group.title,'Synthetic song')
        self.assertTrue(any(w.startswith(b'RV1!\x04') for w in self.writes))
        await self.ws.send_json({'type':'stream/clear','payload':{}})
        await self.wait_until(lambda:not self.group.active)
        await self.ws.close();await asyncio.wait_for(self.task,3)
        self.assertFalse(self.group.state['connected']);self.assertFalse(self.group.pcm)

    async def test_redirect_does_not_forward_authentication(self):
        await self.runner.cleanup()
        async def redirect(_):raise self.web.HTTPFound('/elsewhere')
        async def elsewhere(_):self.redirect_hits+=1;return self.web.Response()
        app=self.web.Application();app.router.add_get('/sendspin',redirect);app.router.add_get('/elsewhere',elsewhere)
        self.runner=self.web.AppRunner(app);await self.runner.setup()
        self.site=self.web.TCPSite(self.runner,'127.0.0.1',0);await self.site.start()
        self.config.url=f'http://127.0.0.1:{self.site._server.sockets[0].getsockname()[1]}'
        await self.group._connect(self.config,'synthetic-token')
        self.assertEqual(self.redirect_hits,0);self.assertFalse(self.group.state['connected'])
        self.assertEqual(self.group.state['error'],'connection_unavailable')


if __name__=='__main__':unittest.main()
