"""Authenticated, player-only Sendspin relay; no new publicly reachable music port."""
import asyncio
import contextlib
import json
from urllib.parse import urlsplit,urlunsplit

from fastapi import HTTPException,Request,WebSocket,WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException


class NoRedirect(connect):
    def process_redirect(self,exc):return exc


def player_message(raw,identifier,*,hello=False):
    if not isinstance(raw,str) or len(raw.encode())>16384:raise ValueError('Expected a bounded player message')
    value=json.loads(raw)
    if not isinstance(value,dict) or set(value)!={'type','payload'} or not isinstance(value['payload'],dict):raise ValueError('Invalid player message')
    kind,payload=value['type'],value['payload']
    if hello:
        if kind!='client/hello' or payload.get('client_id')!=identifier or payload.get('supported_roles')!=['player@v1']:
            raise ValueError('This connection is restricted to its paired audio player')
        if payload.get('version')!=1 or not isinstance(payload.get('player@v1_support'),dict):raise ValueError('Unsupported player hello')
        if any(key.endswith('_support') and key!='player@v1_support' for key in payload):raise ValueError('Unexpected role support')
    elif kind=='client/state':
        if set(payload)-{'player','state'}:raise ValueError('Only player state is allowed')
    elif kind=='client/time':
        if set(payload)-{'client_transmitted'}:raise ValueError('Invalid timing request')
    elif kind=='client/goodbye':
        if set(payload)-{'reason'}:raise ValueError('Invalid disconnect request')
    elif kind=='stream/request-format':
        if set(payload)-{'player'}:raise ValueError('Only player format is allowed')
    else:raise ValueError('Controller commands and audio uploads are not supported here')
    return raw


class GroupStreams:
    def __init__(self,music,authorize,connector=NoRedirect):
        self.music,self.authorize,self.connector=music,authorize,connector
        self.active=set()

    def permission(self,request):
        principal=self.authorize(request)
        if not principal.startswith('display:'):raise PermissionError('A paired native display is required')
        identifier=principal[8:]
        with self.music.lock:
            self.music.settings()
            if not self.music.actions_enabled or not self.music.config.enabled or identifier not in self.music.config.receivers:
                raise PermissionError('The owner has not enabled this native music receiver')
            return identifier,self.music.config.url,self.music.token

    async def handle(self,ws):
        # Reuse the display credential and guest policy. Cookies alone never enroll
        # a new receiver, and the regular owner's cookie cannot impersonate one.
        scope={**ws.scope,'type':'http','method':'GET','scheme':'https' if ws.url.scheme=='wss' else 'http'}
        request=Request(scope)
        identifier=None;tasks=[];claimed=False
        try:
            if not ws.headers.get('authorization','').startswith('Display '):raise PermissionError()
            identifier,origin,token=await asyncio.to_thread(self.permission,request)
            if identifier in self.active or len(self.active)>=32:raise PermissionError()
            self.active.add(identifier)
            claimed=True
            await ws.accept()
            player_id='echo-'+identifier
            hello=player_message(await asyncio.wait_for(ws.receive_text(),8),player_id,hello=True)
            source=urlsplit(origin);url=urlunsplit(('wss' if source.scheme=='https' else 'ws',source.netloc,'/sendspin','',''))
            async with self.connector(url,proxy=None,open_timeout=10,close_timeout=2,max_size=2_000_000,max_queue=8) as remote:
                await remote.send(json.dumps({'type':'auth','token':token,'client_id':player_id}))
                result=json.loads(await asyncio.wait_for(remote.recv(),10))
                if result!={'type':'auth_ok'}:raise PermissionError()
                await remote.send(hello)
                async def upload():
                    while True:await remote.send(player_message(await ws.receive_text(),player_id))
                async def download():
                    async for value in remote:
                        if isinstance(value,bytes):
                            if not value or value[0] not in range(4,8):raise ValueError('Only audio frames may reach this player')
                            await ws.send_bytes(value)
                        else:await ws.send_text(value)
                async def watch():
                    while True:
                        await asyncio.sleep(.5)
                        current=await asyncio.to_thread(self.permission,request)
                        if current!=(identifier,origin,token):raise PermissionError('Receiver permission changed')
                tasks=[asyncio.create_task(fn()) for fn in (upload,download,watch)]
                await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
        except (HTTPException,PermissionError,ValueError,KeyError,OSError,TimeoutError,WebSocketDisconnect,WebSocketException,RuntimeError):
            pass  # Never include account tokens, device identities or stream data in logs.
        finally:
            for task in tasks:task.cancel()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
            if claimed:self.active.discard(identifier)
            with contextlib.suppress(RuntimeError,WebSocketDisconnect):await ws.close(code=1008)


def install(app,music,authorize):
    streams=GroupStreams(music,authorize);app.state.group_streams=streams
    @app.websocket('/v1/music/groups/stream')
    async def stream(socket:WebSocket):await streams.handle(socket)
