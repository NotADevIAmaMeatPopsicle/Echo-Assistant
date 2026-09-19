"""Authenticated call signalling and framed PCM relay over the private HTTP bridge."""
import asyncio
from fastapi import Depends,HTTPException,Query,Request
from fastapi.responses import JSONResponse,StreamingResponse
from pydantic import BaseModel,ConfigDict,Field
from .intercom import IntercomConflict,IntercomDenied


class Session(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    client:str=Field(pattern=r'^(round|[a-f0-9]{32})$')

class Heartbeat(Session):
    enabled:bool
    busy:bool

class Call(Session):
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    target:str=Field(pattern=r'^(round|[a-f0-9]{32})$')
    revision:int=Field(ge=0)

class Mute(Session):
    muted:bool


def install(app,intercom,authorize):
    app.state.intercom=intercom
    @app.exception_handler(IntercomConflict)
    async def conflict(request,error):return JSONResponse({'detail':str(error)},status_code=409)
    @app.exception_handler(IntercomDenied)
    async def denied(request,error):return JSONResponse({'detail':str(error)},status_code=403)

    def endpoint(request,session):
        if session.startswith('display:'):return session.split(':',1)[1]
        if session=='device' and request.headers.get('x-echo-audio-receiver')=='round':return 'round'
        raise HTTPException(403,'Intercom audio requires a paired endpoint')

    @app.post('/v1/intercom/heartbeat')
    def heartbeat(body:Heartbeat,request:Request,session=Depends(authorize)):
        return intercom.heartbeat(endpoint(request,session),body.client,body.enabled,body.busy)

    @app.post('/v1/intercom/calls')
    def call(body:Call,request:Request,session=Depends(authorize)):
        return intercom.start(endpoint(request,session),body.client,body.id,body.target,body.revision)

    @app.post('/v1/intercom/calls/{identifier}/accept')
    def accept(identifier:str,body:Session,request:Request,session=Depends(authorize)):
        return intercom.accept(identifier,endpoint(request,session),body.client)

    @app.post('/v1/intercom/calls/{identifier}/end')
    def end(identifier:str,body:Session,request:Request,session=Depends(authorize)):
        return intercom.end(identifier,endpoint(request,session),body.client)

    @app.post('/v1/intercom/calls/{identifier}/mute')
    def mute(identifier:str,body:Mute,request:Request,session=Depends(authorize)):
        return intercom.mute(identifier,endpoint(request,session),body.client,body.muted)

    @app.post('/v1/intercom/calls/{identifier}/audio')
    async def upload(identifier:str,request:Request,client:str=Query(pattern=r'^(round|[a-f0-9]{32})$'),
                     sequence:int=Query(ge=0,le=0xffffffff),session=Depends(authorize)):
        receiver=endpoint(request,session)
        if request.headers.get('content-type')!='application/octet-stream':raise HTTPException(415,'Send PCM bytes')
        pcm=bytearray()
        async for block in request.stream():
            pcm.extend(block)
            if len(pcm)>6400:raise HTTPException(413,'Audio packet is too large')
        authorize(request)
        try:intercom.push(identifier,receiver,client,sequence,pcm)
        except (IntercomConflict,IntercomDenied):raise
        except ValueError as error:raise HTTPException(422,str(error)) from None
        return {'accepted':sequence}

    @app.get('/v1/intercom/calls/{identifier}/audio')
    def stream(identifier:str,request:Request,client:str=Query(pattern=r'^(round|[a-f0-9]{32})$'),session=Depends(authorize)):
        receiver=endpoint(request,session);marker=intercom.open_stream(identifier,receiver,client)
        async def frames():
            try:
                while not await request.is_disconnected():
                    authorize(request)
                    block=intercom.pull(identifier,receiver,client,marker)
                    if block:yield block
                    await asyncio.sleep(.02)
            except (IntercomConflict,IntercomDenied,HTTPException):return
            finally:intercom.close_stream(identifier,receiver,marker)
        return StreamingResponse(frames(),media_type='application/x-echo-pcm',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
