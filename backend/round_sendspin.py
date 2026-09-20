"""Pinned Sendspin SDK connection for the Mini; imported only after opt-in."""
import asyncio
import contextlib
from urllib.parse import urlsplit,urlunsplit


async def connect(receiver,config,token):
    import aiohttp
    from aiosendspin.client import SendspinClient
    from aiosendspin.models.player import ClientHelloPlayerSupport,SupportedAudioFormat
    from aiosendspin.models.types import Roles,AudioCodec,PlayerCommand,PlayerStateType

    class Clock:
        def now_us(self):return round(receiver.clock()*1_000_000)
    trace=aiohttp.TraceConfig()
    async def no_redirect(*_):raise RuntimeError('Audio redirects are disabled')
    trace.on_request_redirect.append(no_redirect)
    origin=urlsplit(config.url);url=urlunsplit(('wss' if origin.scheme=='https' else 'ws',origin.netloc,'/sendspin','',''))
    async with aiohttp.ClientSession(trust_env=False,trace_configs=[trace],timeout=aiohttp.ClientTimeout(total=10)) as session:
        client=SendspinClient(client_id=receiver.identity,client_name=config.round_name,roles=[Roles.PLAYER,Roles.METADATA],
            session=session,clock=Clock(),initial_volume=config.round_volume,initial_muted=False,
            required_lead_time_ms=500,min_buffer_ms=500,
            player_support=ClientHelloPlayerSupport(supported_formats=[SupportedAudioFormat(codec=AudioCodec.PCM,channels=1,sample_rate=48000,bit_depth=16)],
                buffer_capacity=196608,supported_commands=[PlayerCommand.VOLUME,PlayerCommand.MUTE]))
        disconnected=asyncio.Event();client.add_disconnect_listener(disconnected.set)
        client.add_stream_start_listener(lambda message:receiver.stream('start') if message.payload.player is not None else None)
        client.add_stream_clear_listener(lambda roles:receiver.stream('clear') if roles is None or 'player' in roles else None)
        client.add_stream_end_listener(lambda roles:receiver.stream('end') if roles is None or 'player' in roles else None)
        def audio(timestamp,pcm,format):
            # 6.0.1 passes AudioFormat containing pcm_format, despite the older
            # callback docstring describing PCMFormat directly. Only raw PCM is
            # advertised; compressed bytes must never enter the firmware queue.
            f=format.pcm_format
            if format.codec!=AudioCodec.PCM or (f.sample_rate,f.channels,f.bit_depth)!=(48000,1,16):
                receiver.publish(error='audio_format');disconnected.set();return
            if client.is_time_synchronized():receiver.audio(pcm,round(client.compute_play_time(timestamp)))
        client.add_audio_chunk_listener(audio)
        def metadata(payload):
            value=payload.metadata
            if value is None:return
            with receiver.lock:
                for key in ('title','artist'):
                    text=getattr(value,key,None)
                    if isinstance(text,str) or text is None:setattr(receiver,key,(text or '')[:200])
        client.add_metadata_listener(metadata)
        volume=config.round_volume;muted=False
        def command(payload):
            nonlocal volume,muted
            p=payload.player
            if p is None:return
            if p.command==PlayerCommand.VOLUME and p.volume is not None:volume=max(0,min(config.round_volume,p.volume))
            elif p.command==PlayerCommand.MUTE and p.mute is not None:muted=p.mute
            receiver.publish(volume=volume,muted=muted)
        client.add_server_command_listener(command)
        try:
            async with session.ws_connect(url,heartbeat=30,max_msg_size=2_000_000) as ws:
                await ws.send_json({'type':'auth','token':token,'client_id':receiver.identity})
                response=await asyncio.wait_for(ws.receive_json(),10)
                if response!={'type':'auth_ok'}:raise PermissionError('Music Assistant authentication failed')
                await client.attach_websocket(ws)
                last_report=None
                while not receiver.stopped.is_set() and not disconnected.is_set():
                    synchronized=client.is_time_synchronized()
                    receiver.publish(phase='ready',connected=True,server_clock=synchronized,error=None)
                    with receiver.lock:
                        ready=receiver.sender.device_clock.ready
                    report=(volume,muted,ready)
                    if report!=last_report:
                        await client.send_player_state(state=PlayerStateType.SYNCHRONIZED if ready else PlayerStateType.ERROR,
                                                       volume=volume,muted=muted)
                        last_report=report
                    await asyncio.sleep(.2)
        finally:
            with contextlib.suppress(Exception):await asyncio.wait_for(client.disconnect(),2)
