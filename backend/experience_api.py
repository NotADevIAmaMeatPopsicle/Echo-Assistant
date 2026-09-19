"""Selected-source display routes; owner-only source discovery and permissions."""
from datetime import date
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from .experiences import Sources, ExperienceUnavailable, ExperienceConflict
from .home import HomeUnavailable


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    sources: Sources


def install(app, experiences, authorize, owner):
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

    @app.get('/v1/display/agenda', dependencies=[Depends(authorize)])
    def agenda(start: str = Query(pattern=r'^\d{4}-\d{2}-\d{2}$'), days: int = Query(default=7, ge=1, le=31)):
        return call(lambda: experiences.agenda(start, days))

    @app.get('/v1/display/cameras/{identifier}/snapshot', dependencies=[Depends(authorize)])
    def snapshot(identifier: str, request: Request):
        image, mime = call(lambda: experiences.camera(identifier))
        authorize(request)  # A revoked display must not receive a just-fetched frame.
        return Response(image, media_type=mime)
