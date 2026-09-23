"""Pi audio client for Echo's private player relay. Requires the pinned optional runtime."""
import argparse
import asyncio
import contextlib
import json
import logging
from pathlib import Path
import signal
import time
from urllib.parse import urlsplit

from grouped import atomic,private_json,worker_volume
from kiosk import validate_url
from spotify import validate_config


async def run(config,connection,status_path):
    import aiohttp
    from aiosendspin.client import SendspinClient
    from aiosendspin.models.player import ClientHelloPlayerSupport,SupportedAudioFormat
    from aiosendspin.models.types import Roles,AudioCodec,PlayerCommand
    from sendspin.audio_devices import AudioDevice
    from sendspin.audio_connector import AudioStreamHandler

    validate_url(connection['url']);source=urlsplit(connection['url']);origin=source.scheme+'://'+source.netloc
    credential=connection['credential'];display_id=credential.split('.',1)[0]
    if len(display_id)!=32 or any(c not in '0123456789abcdef' for c in display_id):raise ValueError('Invalid display pairing')
    url=('wss' if source.scheme=='https' else 'ws')+'://'+source.netloc+'/v1/music/groups/stream'
    stopped=asyncio.Event();loop=asyncio.get_running_loop()
    for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,stopped.set)
    # No discovery, hardware-volume backend, MPRIS controller, recording or direct
    # Music Assistant token lives on the Pi. Only its existing display credential.
    headers={'Authorization':'Display '+credential,'Origin':origin,'X-Echo-Request':'1'}
    trace=aiohttp.TraceConfig()
    async def no_redirect(*_):raise RuntimeError('Redirected audio connection rejected')
    trace.on_request_redirect.append(no_redirect)
    device=AudioDevice(index=None,name=config['output'],output_channels=2,sample_rate=48000,is_default=False,alsa_device_name=config['output'])
    state={'phase':'connecting','volume':config['volume'],'clock_synchronized':False,'chunks':0}
    # Observe the pinned player's output state rather than equating network
    # packets with audible playback. These counters contain no audio or titles.
    import sendspin.audio_connector as connector
    base_player=connector.AudioPlayer
    class ObservedPlayer(base_player):
        def set_format(self,audio_format,device):
            import sounddevice
            from sendspin.audio import SOUNDDEVICE_DTYPE_MAP
            fmt=audio_format.pcm_format
            self._format=fmt;self._close_stream()
            self._stream_started=False;self._first_real_chunk=True
            self._stream=sounddevice.RawOutputStream(samplerate=fmt.sample_rate,
                channels=fmt.channels,dtype=SOUNDDEVICE_DTYPE_MAP[fmt.bit_depth],
                blocksize=4800,callback=self._audio_callback,latency=.5,device=device.device_id)
            self._output_latency_us=int(self._stream.latency*1_000_000)
            state['output_latency_ms']=round(self._stream.latency*1000)
        def _audio_callback(self,outdata,frames,timing,status):
            if status.output_underflow:
                # PortAudio/Pulse may report an underrun while starting. The
                # SDK clears all future audio on that flag, repeatedly moving
                # a mid-stream join back to the server's prebuffer horizon.
                # Keep timestamped PCM: normal late-frame gating and clock
                # correction already catch up without restarting the stream.
                state['output_underruns']=state.get('output_underruns',0)+1
                status=type(status)()
            return super()._audio_callback(outdata,frames,timing,status)
        def submit(self,timestamp,payload):
            super().submit(timestamp,payload)
            state['decoded_chunks']=state.get('decoded_chunks',0)+1
            state['output_active']=bool(self._stream and self._stream.active)
            state['buffered_chunks']=self._queue.qsize()
            state['scheduled_ahead_ms']=round((self._compute_client_time(timestamp)-self._now_us())/1000)
            state['pcm_peak']=max((abs(x) for x in memoryview(payload).cast('h')[::16]),default=0)
            state['playout_state']=str(self._playback_state)
            state['start_ahead_ms']=round(((self._scheduled_start_loop_time_us or self._now_us())-self._now_us())/1000)
            state['output_gain']=self.volume
            state['output_muted']=self.muted
    connector.AudioPlayer=ObservedPlayer
    class EchoAudio(AudioStreamHandler):
        factor=0.;target=0.;focus_muted=True
        def effective(self):
            if self._audio_worker:self._audio_worker.set_volume(worker_volume(self.volume,self.factor),muted=self.muted or self.focus_muted)
        def set_volume(self,volume,*,muted):
            super().set_volume(max(0,min(config['volume'],int(volume))),muted=muted);self.effective()
        def _start_audio_worker(self,client):
            super()._start_audio_worker(client);self.effective()
        def _on_audio_chunk(self,*args):
            state['chunks']+=1;super()._on_audio_chunk(*args)
    async with aiohttp.ClientSession(headers=headers,trust_env=False,trace_configs=[trace]) as session, aiohttp.ClientSession(trust_env=False) as local:
        backoff=1
        while not stopped.is_set():
            def event(name):state['phase']='playing' if name=='start' else 'ready'
            handler=EchoAudio(audio_device=device,volume=config['volume'],muted=False,on_event=event)
            client=SendspinClient(client_id='echo-'+display_id,client_name=config['name'],roles=[Roles.PLAYER],session=session,
                player_support=ClientHelloPlayerSupport(supported_formats=[SupportedAudioFormat(codec=c,channels=2,sample_rate=48000,bit_depth=16) for c in (AudioCodec.FLAC,AudioCodec.PCM)],
                    buffer_capacity=4_000_000,supported_commands=[PlayerCommand.VOLUME,PlayerCommand.MUTE]),
                initial_volume=config['volume'],initial_muted=False,required_lead_time_ms=350,min_buffer_ms=350)
            disconnected=asyncio.Event();client.add_disconnect_listener(disconnected.set)
            def command(payload):
                p=payload.player
                if p is None:return
                if p.command==PlayerCommand.VOLUME and p.volume is not None:handler.set_volume(p.volume,muted=handler.muted)
                elif p.command==PlayerCommand.MUTE and p.mute is not None:handler.set_volume(handler.volume,muted=p.mute)
            client.add_server_command_listener(command);handler.attach_client(client)
            tasks=[]
            try:
                state.update(phase='connecting',clock_synchronized=False,error=None);atomic(status_path,{**state,'at':time.time()})
                await client.connect(url);state['phase']='ready';backoff=1
                async def focus():
                    last_save=0
                    while True:
                        try:
                            async with local.get('http://127.0.0.1:8790/v1/display/group-music/focus',timeout=aiohttp.ClientTimeout(total=1),allow_redirects=False) as response:
                                response.raise_for_status();value=await response.json()
                                if any(type(value.get(k)) is not bool for k in ('held','ducked','other_music')):raise ValueError()
                            handler.focus_muted=value['held'] or value['other_music'];handler.target=.2 if value['ducked'] else 1.
                        except (aiohttp.ClientError,TimeoutError,ValueError):handler.focus_muted=True;handler.target=0.
                        # Fade over roughly 120 ms. Only this endpoint changes level.
                        for _ in range(4):
                            handler.factor+=max(-.417,min(.417,handler.target-handler.factor));handler.effective()
                            await asyncio.sleep(.05)
                        if time.monotonic()-last_save>1:
                            state['worker_alive']=bool(handler._audio_worker and handler._audio_worker.is_running())
                            state.update(volume=handler.volume,clock_synchronized=client.is_time_synchronized(),muted_for_focus=handler.focus_muted,ducking=handler.target==.2)
                            atomic(status_path,{**state,'at':time.time()});last_save=time.monotonic()
                tasks=[asyncio.create_task(focus()),asyncio.create_task(disconnected.wait()),asyncio.create_task(stopped.wait())]
                await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            except (aiohttp.ClientError,TimeoutError,OSError,ValueError,RuntimeError) as error:
                state.update(phase='unavailable',error=type(error).__name__)
            finally:
                for task in tasks:task.cancel()
                if tasks:await asyncio.gather(*tasks,return_exceptions=True)
                await handler.shutdown()
                with contextlib.suppress(Exception):await client.disconnect()
                state.update(phase='disabled' if stopped.is_set() else 'reconnecting',clock_synchronized=False)
                atomic(status_path,{**state,'at':time.time()})
            if not stopped.is_set():
                with contextlib.suppress(TimeoutError):await asyncio.wait_for(stopped.wait(),backoff)
                backoff=min(30,backoff*2)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('config','connection','status'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();logging.disable(logging.CRITICAL)
    try:
        config=validate_config(private_json(args.config))
        if config['enabled']:asyncio.run(run(config,private_json(args.connection),args.status))
    except (OSError,ValueError,KeyError,RuntimeError):raise SystemExit('Grouped music is unavailable. Check private pairing and its selected output.') from None
