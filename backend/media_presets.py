"""Owner-curated HTTPS radio presets. Streams are opened by the display, not the host."""
import base64
import ipaddress
import json
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .experiences import ExperienceUnavailable,ExperienceConflict


class Station(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name:str=Field(min_length=1,max_length=80)
    url:str=Field(min_length=10,max_length=2048)

    @field_validator('name')
    @classmethod
    def name_text(cls,value):
        if not value.strip() or any(ord(c)<32 for c in value):raise ValueError('Choose a readable station name')
        return value.strip()

    @field_validator('url')
    @classmethod
    def stream_url(cls,value):
        url=urlsplit(value);host=(url.hostname or '').lower();port=url.port
        if url.scheme!='https' or not host or url.username is not None or url.password is not None or url.fragment:
            raise ValueError('Use a public HTTPS stream URL without embedded credentials')
        if any(ord(c)<=32 for c in value) or host in {'localhost'} or host.endswith(('.local','.localhost','.internal')):raise ValueError('Use a public HTTPS stream')
        try:
            address=ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host:raise ValueError('Use a public stream hostname')
        else:
            if not address.is_global:raise ValueError('Private network stream URLs are not supported')
        return value


class MediaSettings(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=0)
    stations:list[Station]=Field(default_factory=list,max_length=20)


class MediaPresets:
    def __init__(self,root,protector):
        self.path=Path(root)/'local/echo-media.json' if root else None
        self.protector,self.lock=protector,RLock();self.state=MediaSettings(revision=0);self.error=False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>100_000:raise ValueError()
                envelope=json.loads(self.path.read_text())
                if envelope['version']!=1:raise ValueError()
                self.state=MediaSettings.model_validate_json(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
            except (OSError,ValueError,RuntimeError,KeyError,TypeError):self.error=True

    def snapshot(self):
        with self.lock:
            if self.error:raise ExperienceUnavailable('Saved radio presets are unreadable. Existing storage is preserved.')
            return self.state.model_dump()

    def save(self,settings):
        with self.lock:
            self.snapshot();draft=MediaSettings.model_validate(settings)
            if draft.revision!=self.state.revision:raise ExperienceConflict('Radio presets changed. Reload before saving.')
            draft.revision+=1
            if self.path:
                try:
                    protected=self.protector.encrypt(draft.model_dump_json().encode())
                    self.path.parent.mkdir(parents=True,exist_ok=True)
                    temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(protected).decode()}));temporary.replace(self.path)
                except (OSError,RuntimeError):raise ExperienceUnavailable('Radio presets could not be saved.') from None
            self.state=draft;return self.snapshot()


def install(app,store,authorize,owner):
    from fastapi import Depends
    @app.get('/v1/display/media',dependencies=[Depends(authorize)])
    def presets():return store.snapshot()
    @app.put('/v1/display/media',dependencies=[Depends(owner)])
    def save(body:MediaSettings):return store.save(body.model_dump())
