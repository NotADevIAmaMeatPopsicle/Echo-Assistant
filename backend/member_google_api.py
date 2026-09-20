"""Personal-only API for private Google linking and read-only source selection."""
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .experiences import ExperienceConflict
from .google_calendar import FlowClient, GoogleAccountLabel
from .home import HomeUnavailable


class ConnectPrivate(GoogleAccountLabel, FlowClient):
    pass


class SelectPrivate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    calendars: list[str] = Field(max_length=12)


def install(app, service, authorize):
    app.state.member_google = service

    def call(action):
        try:
            return action()
        except ExperienceConflict as error:
            raise HTTPException(409, str(error)) from None
        except HomeUnavailable as error:
            raise HTTPException(503, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    base = '/v1/member/calendar/google'

    @app.get(base)
    def settings(principal=Depends(authorize)):
        return call(lambda: service.settings(principal))

    @app.post(base + '/flows')
    def begin(body: ConnectPrivate, principal=Depends(authorize)):
        return call(lambda: service.begin(principal, body.label, body.client))

    @app.get(base + '/flows/{identifier}')
    def status(identifier: str, client: str = Query(pattern=r'^[a-f0-9]{64}$'), principal=Depends(authorize)):
        return call(lambda: service.flow_status(principal, identifier, client))

    @app.delete(base + '/flows/{identifier}')
    def cancel(identifier: str, body: FlowClient, principal=Depends(authorize)):
        return call(lambda: service.cancel(principal, identifier, body.client))

    @app.post(base + '/flows/{identifier}/finish')
    def finish(identifier: str, body: FlowClient, principal=Depends(authorize)):
        return call(lambda: service.finish(principal, identifier, body.client))

    @app.post(base + '/accounts/{identifier}/sync')
    def sync(identifier: str, principal=Depends(authorize)):
        return call(lambda: service.sync(principal, identifier))

    @app.delete(base + '/accounts/{identifier}')
    def disconnect(identifier: str, principal=Depends(authorize)):
        return call(lambda: service.disconnect(principal, identifier))

    @app.put(base + '/selection')
    def select(body: SelectPrivate, principal=Depends(authorize)):
        return call(lambda: service.select(principal, body.calendars, body.revision))

    return service
