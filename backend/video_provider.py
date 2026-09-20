"""Encrypted owner selection of one ordinary YouTube video; no provider calls."""
import base64
import json
from pathlib import Path
import re
from threading import RLock

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .experiences import ExperienceConflict
from .members import PersonalPrincipal


MAX_FILE_BYTES = 32_768
MAX_PLAIN_BYTES = 16_384


class VideoUnavailable(RuntimeError):
    pass


class VideoSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    revision: int = Field(ge=0)
    enabled: bool = False
    video_id: str = Field(default='', max_length=11)
    allowed_display_ids: list[str] = Field(default_factory=list, max_length=32)

    @field_validator('video_id')
    @classmethod
    def youtube_id(cls, value):
        if value and not re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
            raise ValueError('Use an exact 11-character YouTube video ID, without a URL or spaces.')
        return value

    @field_validator('allowed_display_ids')
    @classmethod
    def display_ids(cls, values):
        if len(set(values)) != len(values) or any(not re.fullmatch(r'[a-f0-9]{32}', value) for value in values):
            raise ValueError('Choose unique paired display identifiers.')
        return values

    @model_validator(mode='after')
    def selected_video(self):
        if self.enabled and not self.video_id:
            raise ValueError('Select a YouTube video before enabling video playback.')
        return self


class VideoStore:
    def __init__(self, root, protector):
        self.path = Path(root) / 'local/echo-video.json' if root else None
        self.protector, self.lock = protector, RLock()
        self.state = VideoSettings(revision=0)
        self.error = False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError()
                envelope = json.loads(self.path.read_text(encoding='utf-8'))
                if set(envelope) != {'version', 'protected'} or envelope['version'] != 1:
                    raise ValueError()
                raw = protector.decrypt(base64.b64decode(envelope['protected'], validate=True))
                if len(raw) > MAX_PLAIN_BYTES:
                    raise ValueError()
                self.state = VideoSettings.model_validate(json.loads(raw))
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                self.error = True

    def snapshot(self):
        with self.lock:
            if self.error:
                raise VideoUnavailable('Saved video settings are unreadable. Existing storage is preserved.')
            return self.state.model_dump()

    def save(self, body):
        checked = VideoSettings.model_validate(body)
        with self.lock:
            current = self.snapshot()
            if checked.revision != current['revision']:
                raise ExperienceConflict('Video settings changed. Reload before saving.')
            candidate = checked.model_copy(deep=True, update={'revision': checked.revision + 1})
            raw = json.dumps(candidate.model_dump()).encode()
            if len(raw) > MAX_PLAIN_BYTES:
                raise VideoUnavailable('Video settings exceed the storage limit.')
            if self.path:
                try:
                    encoded = json.dumps({'version': 1, 'protected': base64.b64encode(self.protector.encrypt(raw)).decode()})
                    if len(encoded.encode()) > MAX_FILE_BYTES:
                        raise ValueError()
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.path.with_suffix('.tmp')
                    temporary.write_text(encoded, encoding='utf-8')
                    temporary.replace(self.path)
                except (OSError, ValueError, RuntimeError):
                    raise VideoUnavailable('Video settings could not be saved. Previous settings are unchanged.') from None
            self.state = candidate
            return self.snapshot()


class VideoProvider:
    def __init__(self, store, displays):
        self.store, self.displays = store, displays

    def settings(self):
        with self.displays.lock, self.store.lock:
            self.displays.require()
            return {'provider': 'youtube', **self.store.snapshot()}

    def configure(self, body):
        checked = VideoSettings.model_validate(body)
        with self.displays.lock, self.store.lock:
            self.displays.require()
            # This is the configured device profile. A personal session on an
            # otherwise Household display is denied separately by snapshot().
            devices = {device['id']: device for device in self.displays.snapshot()}
            for identifier in checked.allowed_display_ids:
                device = devices.get(identifier)
                if not device or device['profile'].get('mode') != 'household' or device['profile'].get('personal'):
                    raise ValueError('Select only currently paired Household displays.')
            return {'provider': 'youtube', **self.store.save(checked)}

    def snapshot(self, principal):
        with self.displays.lock, self.store.lock:
            self.displays.require()
            state = self.store.snapshot()
            profile_revision = 0
            # PersonalPrincipal subclasses str; check it before string routing.
            if isinstance(principal, PersonalPrincipal):
                reason = 'personal_not_allowed'
            elif principal == 'round':
                reason = 'mini_not_allowed'
            elif isinstance(principal, str) and principal.startswith('display:'):
                current = self.displays.profile_for(principal)
                profile_revision = current['profile_revision']
                profile = current['profile']
                if profile.get('personal'):
                    reason = 'personal_not_allowed'
                elif profile.get('mode') != 'household':
                    reason = 'guest_not_allowed'
                elif principal[8:] not in state['allowed_display_ids']:
                    reason = 'display_not_allowed'
                else:
                    reason = 'allowed'
            else:
                # Only the app's authorize dependency supplies owner principals.
                # The native Pi consumer must require reason == 'allowed'.
                reason = 'owner_preview'
            permitted = reason in {'allowed', 'owner_preview'}
            if permitted and not state['enabled']:
                reason = 'disabled'
            available = permitted and state['enabled']
            result = {'provider': 'youtube', 'revision': state['revision'], 'profile_revision': profile_revision,
                      'available': available, 'reason': reason}
            if available:
                result.update(video_id=state['video_id'], watch_url='https://www.youtube.com/watch?v=' + state['video_id'])
            return result


def install(app, service, authorize, owner):
    app.state.video_provider = service

    def call(action):
        try:
            return action()
        except ExperienceConflict as error:
            raise HTTPException(409, str(error)) from None
        except VideoUnavailable as error:
            raise HTTPException(503, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get('/v1/display/video/settings', dependencies=[Depends(owner)])
    def settings():
        return call(service.settings)

    @app.put('/v1/display/video/settings', dependencies=[Depends(owner)])
    def configure(body: VideoSettings):
        return call(lambda: service.configure(body))

    @app.get('/v1/display/video')
    def selection(principal=Depends(authorize)):
        return call(lambda: service.snapshot(principal))

    return service
