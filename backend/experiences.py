"""Opt-in calendar and camera sources. Home Assistant credentials never reach a page."""
import base64
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .home import HomeUnavailable


class ExperienceUnavailable(RuntimeError): pass
class ExperienceConflict(ValueError): pass


class Sources(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    calendars: list[str] = Field(default_factory=list, max_length=12)
    cameras: list[str] = Field(default_factory=list, max_length=12)
    writable_calendars: list[str] = Field(default_factory=list, max_length=12)

    @field_validator('calendars', 'cameras', 'writable_calendars')
    @classmethod
    def identifiers(cls, values, info):
        domain = 'camera' if info.field_name == 'cameras' else 'calendar'
        if len(set(values)) != len(values) or any(not re.fullmatch(domain+r'\.[a-z0-9_]{1,128}', v) for v in values):
            raise ValueError('Choose unique sources from Home Assistant')
        return values

    @model_validator(mode='after')
    def selected_writers(self):
        if not set(self.writable_calendars)<=set(self.calendars):raise ValueError('Writable calendars must also be shared for reading')
        return self


class SourceStore:
    def __init__(self, root, protector):
        self.path = Path(root)/'local/echo-experiences.json' if root else None
        self.protector, self.lock = protector, RLock()
        self.sources, self.revision, self.error = Sources(), 0, False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size > 50_000: raise ValueError()
                envelope = json.loads(self.path.read_text())
                if envelope['version'] != 1: raise ValueError()
                doc = json.loads(protector.decrypt(base64.b64decode(envelope['protected'], validate=True)))
                if set(doc) != {'revision', 'sources'} or type(doc['revision']) is not int or doc['revision'] < 0: raise ValueError()
                self.sources = Sources.model_validate(doc['sources']); self.revision = doc['revision']
            except (OSError, ValueError, TypeError, KeyError, RuntimeError): self.error = True

    def snapshot(self):
        with self.lock:
            if self.error: raise ExperienceUnavailable('Saved display sources could not be read. The existing file is preserved.')
            return {'revision': self.revision, 'sources': self.sources.model_dump()}

    def save(self, sources, revision):
        with self.lock:
            self.snapshot()
            if self.revision != revision: raise ExperienceConflict('Display sources changed. Reload them before saving.')
            checked = Sources.model_validate(sources)
            draft = {'revision': self.revision+1, 'sources': checked.model_dump()}
            if self.path:
                try:
                    raw = self.protector.encrypt(json.dumps(draft).encode())
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.path.with_suffix('.tmp')
                    temporary.write_text(json.dumps({'version': 1, 'protected': base64.b64encode(raw).decode()}))
                    temporary.replace(self.path)
                except (OSError, RuntimeError): raise ExperienceUnavailable('Display sources could not be saved.') from None
            self.sources, self.revision = checked, draft['revision']
            return deepcopy(draft)


def temporal(value):
    """HA events use date for all-day entries, otherwise timezone-aware dateTime."""
    if not isinstance(value, dict): raise ValueError('Invalid calendar time')
    if 'dateTime' in value:
        dt = datetime.fromisoformat(value['dateTime'].replace('Z', '+00:00'))
        if dt.tzinfo is None: raise ValueError('Calendar times need a timezone')
        return dt.isoformat(), False, dt.timestamp()
    d = date.fromisoformat(value['date'])
    return d.isoformat(), True, datetime.combine(d, datetime.min.time(), timezone.utc).timestamp()


class Experiences:
    def __init__(self, home, store): self.home, self.store = home, store

    def discovery(self):
        if not self.home.config.enabled: return {'status': 'not_configured', 'items': []}
        states = self.home._request('GET', '/api/states')
        if not isinstance(states, list): raise HomeUnavailable('Home source inventory unavailable')
        items = []
        for state in states:
            if not isinstance(state, dict): continue
            identifier = state.get('entity_id', '')
            if not isinstance(identifier, str) or not re.fullmatch(r'(calendar|camera)\.[a-z0-9_]{1,128}', identifier): continue
            attrs = state.get('attributes') or {}
            name = attrs.get('friendly_name')
            items.append({'entity_id': identifier, 'kind': identifier.split('.')[0],
                          'name': name[:160] if isinstance(name, str) else identifier,
                          'can_create':identifier.startswith('calendar.') and type(attrs.get('supported_features')) is int and bool(attrs['supported_features']&1),
                          'available': state.get('state') not in {None, 'unknown', 'unavailable'}})
        return {'status': 'available', 'items': items[:256]}

    def save_sources(self, sources, revision):
        checked = Sources.model_validate(sources)
        selected = set(checked.calendars+checked.cameras)
        # Removing all sources remains possible when Home Assistant is offline.
        if selected:
            inventory=self.discovery()['items']
            known = {item['entity_id'] for item in inventory}
            if not selected <= known: raise ValueError('A selected source is no longer in Home Assistant')
            if not set(checked.writable_calendars)<={i['entity_id'] for i in inventory if i['can_create']}:
                raise ValueError('A writable calendar does not support event creation')
        return self.store.save(checked.model_dump(), revision)

    def sources(self):
        selected = self.store.snapshot()['sources']
        if not self.home.config.enabled: return {'status': 'not_configured', 'items': []}
        if not any(selected.values()): return {'status': 'not_selected', 'items': []}
        known = {item['entity_id']: item for item in self.discovery()['items']}
        items = []
        for kind in ('calendars','cameras'):
            ids=selected[kind]
            for identifier in ids:
                item=dict(known.get(identifier, {'entity_id': identifier, 'kind': kind[:-1], 'name': identifier, 'available': False}))
                item['writable']=identifier in selected['writable_calendars'] and item.get('can_create',False)
                items.append(item)
        return {'status': 'available', 'items': items, 'revision':self.store.snapshot()['revision']}

    def agenda(self, start, days=7):
        first = date.fromisoformat(start)
        if type(days) is not int or not 1 <= days <= 31: raise ValueError('Choose one to 31 days')
        # A one-day margin captures events across timezone boundaries. The page
        # groups instants in the viewer's zone and filters to its selected days.
        since = datetime.combine(first-timedelta(days=1), datetime.min.time(), timezone.utc)
        until = datetime.combine(first+timedelta(days=days+1), datetime.min.time(), timezone.utc)
        sources = self.sources()
        calendars = [s for s in sources['items'] if s['kind'] == 'calendar']
        events, failures = [], []
        for source in calendars:
            identifier = source['entity_id']
            try:
                raw = self.home._request('GET', '/api/calendars/'+identifier+'?'+urlencode({'start': since.isoformat(), 'end': until.isoformat()}))
                if not isinstance(raw, list): raise HomeUnavailable('Calendar returned no event list')
                for event in raw[:300]:
                    try:
                        began, all_day, sort = temporal(event['start']); ended, end_all_day, end_sort = temporal(event['end'])
                        if all_day != end_all_day or end_sort < sort: continue
                        summary = event.get('summary', 'Untitled event')
                        if not isinstance(summary, str): continue
                        key = hashlib.sha256((identifier+began+ended+summary).encode()).hexdigest()[:32]
                        events.append({'id': key, 'calendar': identifier, 'calendar_name': source['name'],
                                       'title': summary[:300], 'start': began, 'end': ended, 'all_day': all_day,
                                       'location': str(event.get('location') or '')[:300], '_sort': sort})
                    except (KeyError, ValueError, TypeError, AttributeError): continue
            except HomeUnavailable: failures.append(identifier)
        events.sort(key=lambda e: (e['_sort'], e['title']))
        events = events[:500]
        for e in events: e.pop('_sort')
        # Recheck permission after slow upstream calls, before returning data.
        current = set(self.store.snapshot()['sources']['calendars'])
        return {'status': sources['status'] if not calendars else 'partial' if failures else 'available',
                'events': [e for e in events if e['calendar'] in current],
                'unavailable': [identifier for identifier in failures if identifier in current], 'start': start, 'days': days}

    def camera(self, identifier):
        if identifier not in self.store.snapshot()['sources']['cameras']: raise PermissionError('Camera is not selected for displays')
        if not self.home.config.enabled: raise HomeUnavailable('Home integration is not configured')
        try:
            with httpx.Client(transport=self.home.transport, timeout=8, trust_env=False, follow_redirects=False) as client:
                with client.stream('GET', self.home.config.base_url+'/api/camera_proxy/'+identifier,
                                   headers={'Authorization': 'Bearer '+self.home.config.token}) as response:
                    response.raise_for_status()
                    mime = response.headers.get('content-type', '').split(';')[0].lower()
                    if mime not in {'image/jpeg', 'image/png', 'image/webp'}: raise ValueError()
                    chunks, size = [], 0
                    for block in response.iter_bytes(65536):
                        size += len(block)
                        if size > 5_000_000: raise ValueError()
                        chunks.append(block)
                    image = b''.join(chunks)
                    valid = (mime == 'image/jpeg' and image.startswith(b'\xff\xd8\xff') or
                             mime == 'image/png' and image.startswith(b'\x89PNG\r\n\x1a\n') or
                             mime == 'image/webp' and image.startswith(b'RIFF') and image[8:12] == b'WEBP')
                    if not valid: raise ValueError()
        except (httpx.HTTPError, ValueError): raise HomeUnavailable('Camera snapshot is unavailable') from None
        if identifier not in self.store.snapshot()['sources']['cameras']: raise PermissionError('Camera access was removed')
        return image, mime
