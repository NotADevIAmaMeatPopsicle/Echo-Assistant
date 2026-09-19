"""Schedule API, shared by the large display and existing audio endpoints."""
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from .audio_destination import destination_for
from .schedules import ScheduleSpec,QuietHours,ScheduleUnavailable,ScheduleConflict


class Revision(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=0)

class Save(Revision):
    schedule:ScheduleSpec

class Quiet(Revision):
    quiet:QuietHours

class EventAction(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    action:Literal['dismiss','snooze']
    minutes:int=Field(default=5,ge=1,le=60)

class Notice(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    title:str=Field(min_length=1,max_length=80)
    message:str=Field(min_length=1,max_length=400)
    announce:bool=False


def install(app,store,authorize):
    @app.exception_handler(ScheduleUnavailable)
    async def unavailable(request,error): return JSONResponse({'detail':str(error)},status_code=503)

    @app.exception_handler(ScheduleConflict)
    async def conflict(request,error): return JSONResponse({'detail':str(error)},status_code=409)

    def change(call):
        try: return call()
        except ScheduleConflict: raise
        except KeyError: raise HTTPException(404,'Schedule not found') from None
        except ValueError as error: raise HTTPException(422,str(error)) from None

    @app.get('/v1/schedules',dependencies=[Depends(authorize)])
    def snapshot(): return store.snapshot()

    @app.post('/v1/notifications',dependencies=[Depends(authorize)])
    def notify(body:Notice,session=Depends(authorize)):return change(lambda:store.notify(body.title,body.message,body.announce,destination=destination_for(session)))

    @app.post('/v1/schedules',dependencies=[Depends(authorize)])
    def create(body:Save,session=Depends(authorize)): return change(lambda:store.save(body.schedule.model_dump(),body.revision,destination=destination_for(session)))

    @app.put('/v1/schedules/{identifier}',dependencies=[Depends(authorize)])
    def update(identifier:str,body:Save): return change(lambda:store.save(body.schedule.model_dump(),body.revision,identifier))

    @app.delete('/v1/schedules/{identifier}',dependencies=[Depends(authorize)])
    def delete(identifier:str,body:Revision):
        change(lambda:store.delete(identifier,body.revision)); return {'deleted':True}

    @app.put('/v1/schedule-preferences',dependencies=[Depends(authorize)])
    def preferences(body:Quiet):
        change(lambda:store.set_quiet(body.quiet.model_dump(),body.revision)); return store.snapshot()

    @app.post('/v1/schedule-events/{identifier}',dependencies=[Depends(authorize)])
    def event(identifier:str,body:EventAction):
        if not change(lambda:store.event_action(identifier,body.action,body.minutes)): raise HTTPException(404,'Notification not found')
        return store.snapshot()
