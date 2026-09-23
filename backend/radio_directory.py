"""Read-only public station discovery. Streams are opened by the listening browser."""
import random
import re
import time
from threading import RLock

import httpx
from fastapi import Depends, HTTPException, Query

from .media_presets import Station


class RadioDirectory:
    servers = ('https://de1.api.radio-browser.info', 'https://nl1.api.radio-browser.info')

    def __init__(self, transport=None, clock=time.monotonic):
        self.transport, self.clock = transport, clock
        self.cache, self.lock = {}, RLock()

    @staticmethod
    def clean(value, limit=100):
        return ''.join(c for c in value if ord(c) >= 32)[:limit] if isinstance(value, str) else ''

    def search(self, query='', country='', tag='', offset=0):
        query, country, tag = query.strip(), country.upper(), tag.strip()
        if (len(query) > 100 or len(tag) > 40 or not re.fullmatch(r'[A-Z]{2}|', country)
                or type(offset) is not int or not 0 <= offset <= 1000
                or any(ord(c) < 32 for c in query + tag)):
            raise ValueError('Choose a valid station search or country')
        key = query, country, tag, offset
        with self.lock:
            cached = self.cache.get(key)
            if cached and self.clock() - cached[0] < 300:
                return cached[1]
        params = {'limit': 30, 'offset': offset, 'hidebroken': 'true', 'is_https': 'true',
                  'order': 'clickcount', 'reverse': 'true'}
        if query: params['name'] = query
        if country: params['countrycode'] = country
        if tag: params['tag'] = tag
        servers = list(self.servers); random.shuffle(servers)
        for server in servers:
            try:
                with httpx.Client(transport=self.transport, trust_env=False, follow_redirects=False,
                                  timeout=httpx.Timeout(4, connect=2)) as client:
                    with client.stream('GET', server + '/json/stations/search', params=params,
                                       headers={'User-Agent': 'Echo-Assistant/0.27 (radio discovery)'}) as response:
                        response.raise_for_status(); raw = bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 1_000_000: raise ValueError('Directory response too large')
                import json
                values = json.loads(raw)
                if not isinstance(values, list): raise ValueError('Invalid directory response')
                items, seen = [], set()
                for value in values[:30]:
                    if not isinstance(value, dict) or value.get('hls') or value.get('lastcheckok') != 1:
                        continue
                    try:
                        station = Station(name=self.clean(value.get('name'), 80),
                                          url=value.get('url_resolved') or value.get('url'))
                    except ValueError:
                        continue
                    if station.url in seen: continue
                    seen.add(station.url)
                    items.append({**station.model_dump(), 'country': self.clean(value.get('country'), 80),
                                  'tags': self.clean(value.get('tags'), 120),
                                  'codec': self.clean(value.get('codec'), 12),
                                  'bitrate': value.get('bitrate') if type(value.get('bitrate')) is int else 0})
                result = {'items': items, 'offset': offset, 'next_offset': offset + len(values),
                          'more': len(values) >= 30 and offset < 1000, 'source': 'Radio Browser'}
                with self.lock:
                    if len(self.cache) >= 64: self.cache.pop(next(iter(self.cache)))
                    self.cache[key] = self.clock(), result
                return result
            except (httpx.HTTPError, ValueError, TypeError):
                continue
        raise RuntimeError('Station directory is unavailable. Your saved favorites still work; try again shortly.')


def install(app, authorize):
    directory = RadioDirectory()

    @app.get('/v1/radio/stations', dependencies=[Depends(authorize)])
    def stations(q: str = Query('', max_length=100), country: str = Query('', max_length=2),
                 tag: str = Query('', max_length=40), offset: int = Query(0, ge=0, le=1000)):
        try: return directory.search(q, country, tag, offset)
        except ValueError as error: raise HTTPException(422, str(error)) from None
        except RuntimeError as error: raise HTTPException(503, str(error)) from None

    return directory
