"""Selected-source display routes; owner-only source discovery and permissions."""
from datetime import date
from functools import partial
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
import httpx
from pydantic import BaseModel, ConfigDict, Field
from .experiences import Sources, ExperienceUnavailable, ExperienceConflict
from .home import HomeUnavailable
from .calendar_events import CalendarEvent
from .conversation_request import run_conversation
from .camera_stream import CameraStream


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    sources: Sources


class CreateEvent(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=0)
    request_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    event:CalendarEvent


class DraftRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    text:str=Field(min_length=1,max_length=2000)
    timezone:str=Field(min_length=1,max_length=80)


def install(app, experiences, authorize, owner, writer=None, briefing=None, doorbells=None, drafts=None):
    @app.exception_handler(ExperienceUnavailable)
    async def unavailable(request, error): return JSONResponse({'detail': str(error)}, status_code=503)

    @app.exception_handler(ExperienceConflict)
    async def conflict(request, error): return JSONResponse({'detail': str(error)}, status_code=409)

    def call(callback):
        try: return callback()
        except ExperienceConflict: raise
        except HomeUnavailable as error: raise HTTPException(503, str(error)) from None
        except PermissionError as error: raise HTTPException(403, str(error)) from None
        except ValueError as error: raise HTTPException(422, str(error)) from None

    @app.get('/v1/display/source-settings', dependencies=[Depends(owner)])
    def settings():
        state = experiences.store.snapshot()
        try: inventory = experiences.discovery()
        except HomeUnavailable: inventory = {'status': 'unavailable', 'items': []}
        return {**state, **inventory}

    @app.put('/v1/display/source-settings', dependencies=[Depends(owner)])
    def select(body: Selection): return call(lambda: experiences.save_sources(body.sources.model_dump(), body.revision))

    @app.get('/v1/display/sources', dependencies=[Depends(authorize)])
    def sources(): return call(experiences.sources)

    @app.get('/v1/display/presence', dependencies=[Depends(authorize)])
    def presence(request: Request):
        result = call(experiences.presence)
        authorize(request)
        return result

    @app.get('/v1/display/doorbells',dependencies=[Depends(authorize)])
    def rings():
        if doorbells is None:raise HTTPException(503,'Doorbell observer unavailable')
        return call(doorbells.snapshot)

    @app.delete('/v1/display/doorbells/events/{identifier}',dependencies=[Depends(authorize)])
    def dismiss_ring(identifier:str):
        if doorbells is None:raise HTTPException(503,'Doorbell observer unavailable')
        return call(lambda:doorbells.dismiss(identifier))

    @app.get('/v1/display/agenda', dependencies=[Depends(authorize)])
    def agenda(start: str = Query(pattern=r'^\d{4}-\d{2}-\d{2}$'), days: int = Query(default=7, ge=1, le=31)):
        return call(lambda: experiences.agenda(start, days))

    @app.get('/v1/display/briefing',dependencies=[Depends(authorize)])
    def daily_briefing(timezone:str=Query(min_length=1,max_length=80)):
        if briefing is None:raise HTTPException(503,'Briefing unavailable')
        return call(lambda:briefing.get(timezone))

    @app.post('/v1/display/calendar/events')
    def create_event(body:CreateEvent,principal=Depends(authorize)):
        if writer is None:raise HTTPException(503,'Calendar creation unavailable')
        result=call(lambda:writer.create(body.event.model_dump(),body.revision,body.request_id,principal))
        if briefing:briefing.invalidate()
        return result

    @app.post('/v1/display/calendar/draft')
    async def draft_event(body:DraftRequest,request:Request,principal=Depends(authorize)):
        if drafts is None:raise HTTPException(503,'Calendar drafting unavailable')
        try:
            return await run_conversation(request,app.state.speech_stop,
                partial(drafts.respond,zone_name=body.timezone),body.text,principal)
        except ValueError as error:raise HTTPException(422,str(error)) from None

    @app.get('/v1/display/cameras/{identifier}/snapshot', dependencies=[Depends(authorize)])
    def snapshot(identifier: str, request: Request):
        image, mime = call(lambda: experiences.camera(identifier))
        authorize(request)  # A revoked display must not receive a just-fetched frame.
        return Response(image, media_type=mime)

    @app.get('/v1/display/cameras/{identifier}/stream', dependencies=[Depends(authorize)])
    async def stream(identifier: str, request: Request):
        relay = CameraStream(experiences, identifier, lambda: authorize(request))
        try: await relay.open()
        except PermissionError as error: raise HTTPException(403, str(error)) from None
        except (HomeUnavailable, httpx.HTTPError, ValueError, StopAsyncIteration, TimeoutError):
            raise HTTPException(503, 'Live camera stream unavailable. Try snapshots or check its Home Assistant integration.') from None
        return StreamingResponse(relay.body(), media_type='multipart/x-mixed-replace; boundary=echo-frame',
                                 background=BackgroundTask(relay.close))
