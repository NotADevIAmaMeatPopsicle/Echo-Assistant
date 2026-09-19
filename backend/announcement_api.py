"""Authenticated announcement senders and receiver-scoped delivery routes."""
from threading import Lock
import time
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .announcements import AnnouncementUnavailable, AnnouncementConflict, RoomPolicy
from .display_voice import wave_bytes
from .speech import synthesize_checked


class Send(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    title:str=Field(min_length=1,max_length=80)
    message:str=Field(min_length=1,max_length=400)
    targets:list[str]=Field(min_length=1,max_length=33)
    revision:int=Field(ge=0)
    issued_at:float=Field(gt=0,allow_inf_nan=False)


class Configure(RoomPolicy):
    revision:int=Field(ge=0)


class Receiver(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    client:str=Field(pattern=r'^(round|[a-f0-9]{32})$')


class Heartbeat(Receiver):
    ready:bool
    busy:bool


class Claim(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    claim:str=Field(pattern=r'^[a-f0-9]{64}$')


class Receipt(Claim):
    status:Literal['played','cancelled','failed']


def install(app,store,settings,authorize,owner,synthesizer=synthesize_checked):
    synth_lock=Lock();audio_cache={};app.state.announcements=store

    @app.exception_handler(AnnouncementUnavailable)
    async def unavailable(request,error):return JSONResponse({'detail':str(error)},status_code=503)
    @app.exception_handler(AnnouncementConflict)
    async def conflict(request,error):return JSONResponse({'detail':str(error)},status_code=409)

    def run(callback):
        try:return callback()
        except AnnouncementConflict:raise
        except PermissionError as error:raise HTTPException(403,str(error)) from None
        except KeyError:raise HTTPException(404,'Announcement not found') from None
        except ValueError as error:raise HTTPException(422,str(error)) from None

    def endpoint(request,session):
        if session.startswith('display:'):return session.split(':',1)[1]
        if session=='device' and request.headers.get('x-echo-audio-receiver')=='round':return 'round'
        raise HTTPException(403,'Receiving audio requires a paired display or the round audio bridge')

    @app.get('/v1/audio/rooms')
    def rooms(session=Depends(authorize)):
        result=store.catalog()
        if session.startswith('display:'):result['items']=[i for i in result['items'] if i['enabled'] or i['calls_enabled']]
        return result

    @app.put('/v1/audio/rooms',dependencies=[Depends(owner)])
    def configure(body:Configure):return run(lambda:store.configure([e.model_dump() for e in body.endpoints],body.revision))

    @app.get('/v1/audio/messages')
    def messages(session=Depends(authorize)):return store.reports(session)

    @app.post('/v1/audio/messages')
    def send(body:Send,session=Depends(authorize)):
        return run(lambda:store.send(body.id,session,body.title,body.message,body.targets,body.revision,body.issued_at))

    @app.delete('/v1/audio/messages/{identifier}')
    def cancel(identifier:str,session=Depends(authorize)):return run(lambda:store.cancel(identifier,session))

    @app.post('/v1/audio/receiver')
    def heartbeat(body:Heartbeat,request:Request,session=Depends(authorize)):
        identifier=endpoint(request,session);store.heartbeat(identifier,body.client,body.ready,body.busy)
        return store.inbox(identifier,body.client)

    @app.get('/v1/audio/inbox')
    def inbox(request:Request,client:str=Query(pattern=r'^(round|[a-f0-9]{32})$'),session=Depends(authorize)):
        return store.inbox(endpoint(request,session),client)

    @app.post('/v1/audio/inbox/{identifier}/claim')
    def claim(identifier:str,body:Receiver,request:Request,session=Depends(authorize)):
        return run(lambda:store.claim(endpoint(request,session),identifier,body.client))

    @app.post('/v1/audio/inbox/{identifier}/audio')
    def audio(identifier:str,body:Claim,request:Request,session=Depends(authorize)):
        receiver=endpoint(request,session);text=run(lambda:store.text(receiver,identifier,body.claim))
        if not synth_lock.acquire(timeout=75):raise HTTPException(503,'The speech engine is busy')
        try:
            # One synthesis serves a multi-room announcement. Only transient audio
            # lives here, bounded to four messages and five minutes.
            for key in list(audio_cache):
                if time.monotonic()-audio_cache[key][0]>300:del audio_cache[key]
            cached=audio_cache.get(identifier)
            if cached and cached[1]==text:audio=cached[2]
            else:
                pcm,metrics=synthesizer(text,settings=settings.snapshot()[0])
                if metrics.get('sample_rate')!=48000 or not pcm or len(pcm)%2 or len(pcm)>48000*2*60:raise ValueError()
                audio=wave_bytes(pcm,48000)
                if len(audio_cache)>=4:del audio_cache[next(iter(audio_cache))]
                audio_cache[identifier]=(time.monotonic(),text,audio)
        except (RuntimeError,ValueError,TimeoutError,OSError):raise HTTPException(503,'Announcement speech could not be generated') from None
        finally:synth_lock.release()
        authorize(request);run(lambda:store.text(receiver,identifier,body.claim))
        return Response(audio,media_type='audio/wav',headers={'Cache-Control':'no-store'})

    @app.post('/v1/audio/inbox/{identifier}/receipt')
    def receipt(identifier:str,body:Receipt,request:Request,session=Depends(authorize)):
        return run(lambda:store.receipt(endpoint(request,session),identifier,body.claim,body.status))
