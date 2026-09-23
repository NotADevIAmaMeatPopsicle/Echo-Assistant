"""Bounded library and queue selection through the configured Music Assistant."""
import secrets
import time
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .group_music import GroupMusicUnavailable


class LibraryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    player: str = Field(min_length=1, max_length=160)
    view: Literal['browse', 'search', 'queue'] = 'browse'
    source: Literal['all', 'spotify'] = 'all'
    selection: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    query: str = Field(default='', max_length=120)
    offset: int = Field(default=0, ge=0, le=10000)
    collection: Literal['library', 'playlists', 'podcasts', 'new_episodes'] = 'library'
    sort: Literal['name', 'latest'] = 'name'


class LibraryPlay(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    player: str = Field(min_length=1, max_length=160)
    selection: str = Field(pattern=r'^[a-f0-9]{32}$')


class MusicLibrary:
    """Keep provider URIs and queue identifiers on the host, scoped to a reader."""
    playable = {'track', 'album', 'playlist', 'radio', 'podcast_episode'}

    def __init__(self, music, clock=time.monotonic):
        self.music, self.clock = music, clock
        self.choices = {}
        self.episode_jobs = {}
        self.episode_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='echo-podcasts')

    def context(self, player):
        self.music.settings()
        rows = self.music.inventory()
        current = self.music.allowed(player, rows)
        if current.get('synced_to') or current.get('active_group'):
            raise ValueError('Choose the group leader to select its music')
        return self.music.binding(rows, set(self.music.config.players))

    def prune(self):
        now = self.clock()
        self.choices = {key: value for key, value in self.choices.items() if value['expires'] > now}

    def remember(self, principal, player, binding, kind, value):
        while len(self.choices) >= 1024:
            self.choices.pop(next(iter(self.choices)))
        key = secrets.token_hex(16)
        self.choices[key] = dict(principal=principal, player=player, binding=binding,
                                 revision=self.music.revision, kind=kind, value=value,
                                 expires=self.clock() + 600)
        return key

    def choice(self, principal, player, selection, binding):
        self.prune()
        value = self.choices.get(selection)
        if not value or value['principal'] != principal or value['player'] != player:
            raise HTTPException(409, 'This music selection expired. Browse again.')
        if value['revision'] != self.music.revision or value['binding'] != binding:
            raise HTTPException(409, 'Outputs or permissions changed. Review the music destination again.')
        return value

    @staticmethod
    def text(value, limit=200):
        return value[:limit] if isinstance(value, str) else ''

    def row(self, item, principal, player, binding, *, queue=False):
        if not isinstance(item, dict):
            raise GroupMusicUnavailable('Music Assistant returned an invalid library item')
        media = item.get('media_item') if queue else item
        media = media if isinstance(media, dict) else {}
        kind = 'queue' if queue else item.get('media_type')
        if kind not in self.playable | {'folder', 'queue', 'podcast'}:
            return None
        value = item.get('queue_item_id') if queue else item.get('path' if kind == 'folder' else 'uri')
        if not isinstance(value, str) or not value or len(value) > 2048 or any(ord(c) < 32 for c in value):
            return None
        artists = media.get('artists') or []
        if not isinstance(artists, list): artists = []
        available = item.get('available', True) is not False
        if kind == 'podcast':
            if not isinstance(item.get('item_id'), str) or not isinstance(item.get('provider'), str):
                return None
            value = {'item_id': item['item_id'], 'provider': item['provider']}
        return {'selection': self.remember(principal, player, binding, kind, value) if available else None,
                'name': self.text(item.get('name')) or 'Untitled', 'kind': kind, 'available': available,
                'artist': ', '.join(self.text(a.get('name'), 80) for a in artists[:4] if isinstance(a, dict)),
                'duration': item.get('duration') if type(item.get('duration')) is int else None,
                'release_date': self.release_date(item),
                'latest_episode': self.text(item.get('latest_episode')),
                'podcast': self.text((item.get('podcast') or {}).get('name')),
                'publisher': self.text(item.get('publisher'))}

    @staticmethod
    def release_date(item):
        value = (item.get('metadata') or {}).get('release_date')
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError, AttributeError):
            return None

    def load_episodes(self, podcast):
        raw = self.music.request('music/podcasts/podcast_episodes',
                                 item_id=podcast['item_id'],
                                 provider_instance_id_or_domain=podcast['provider'],
                                 _timeout=40)
        if not isinstance(raw, list):
            raise GroupMusicUnavailable('The podcast episode list is unavailable')
        # Retain a compact recent window, not long descriptions or private provider mappings.
        episodes = []
        for item in raw:
            if not isinstance(item, dict) or item.get('media_type') != 'podcast_episode':
                continue
            episodes.append({**{key: item.get(key) for key in
                ('name', 'uri', 'media_type', 'duration', 'fully_played')},
                'available': item.get('available', True),
                'podcast': {'name': (item.get('podcast') or {}).get('name', '')},
                'metadata': {'release_date': self.release_date(item)}})
        episodes.sort(key=lambda x: self.release_date(x) or '', reverse=True)
        return episodes[:200]

    def episodes(self, podcast):
        now = self.clock()
        self.episode_jobs = {k: v for k, v in self.episode_jobs.items()
                             if not v[1].done() or v[0] > now}
        key = (self.music.revision, podcast['provider'], podcast['item_id'])
        if key not in self.episode_jobs:
            if len(self.episode_jobs) >= 64:
                return [], False, True
            self.episode_jobs[key] = (now + 300, self.episode_pool.submit(self.load_episodes, dict(podcast)))
        future = self.episode_jobs[key][1]
        if not future.done():
            return [], True, False
        try:
            return future.result(), False, False
        except Exception:
            return [], False, True

    def spotify_collection(self, collection, player):
        roots = self.music.request('music/browse', path='root', player_id=player)
        if not isinstance(roots, list):
            raise GroupMusicUnavailable('Spotify library is unavailable')
        providers = [r for r in roots if isinstance(r, dict) and r.get('provider') == 'spotify']
        if not providers:
            return []
        folders = self.music.request('music/browse', path=providers[0]['path'], player_id=player)
        folder = next((r for r in folders if r.get('item_id') == collection), None)
        if not folder:
            return []
        raw = self.music.request('music/browse', path=folder['path'], player_id=player)
        if not isinstance(raw, list):
            raise GroupMusicUnavailable('Spotify library is unavailable')
        kind = 'playlist' if collection == 'playlists' else 'podcast'
        return [r for r in raw if isinstance(r, dict) and r.get('media_type') == kind]

    def shelf(self, body, principal, binding):
        if body.source != 'spotify' or body.view != 'browse' or body.query:
            raise ValueError('Choose a Spotify library collection')
        pending, failed, limited = False, 0, False
        if body.selection:
            selected = self.choice(principal, body.player, body.selection, binding)
            if selected['kind'] != 'podcast':
                raise ValueError('Choose a podcast to see its episodes')
            raw, pending, error = self.episodes(selected['value'])
            failed = int(error)
        else:
            collection = 'podcasts' if body.collection == 'new_episodes' else body.collection
            raw = self.spotify_collection(collection, body.player)
            if collection == 'playlists':
                def priority(item):
                    match = re.match(r'^\s*([123])\s*[.)]\s*', item.get('name', ''))
                    return (int(match[1]) if match else 4, item.get('name', '').casefold())
                raw.sort(key=priority)
            else:
                raw.sort(key=lambda r: r.get('name', '').casefold())
                if body.sort == 'latest' or body.collection == 'new_episodes':
                    shows, raw = raw, []
                    limited = len(shows) > 64
                    for show in shows[:64]:
                        episodes, loading, error = self.episodes(show)
                        pending |= loading
                        failed += int(error)
                        if body.collection == 'new_episodes':
                            raw.extend(e for e in episodes if not e.get('fully_played') and self.release_date(e))
                        else:
                            latest = episodes[0] if episodes else {}
                            raw.append({**show, 'metadata': {'release_date': self.release_date(latest)},
                                        'latest_episode': latest.get('name', '')})
                    raw.sort(key=lambda r: self.release_date(r) or '', reverse=True)
        if body.collection == 'new_episodes':
            raw = list({r['uri']: r for r in raw}.values())
        total = len(raw)
        # The first shelf is deliberately small. Further playlists are fetched on demand.
        size = 3 if body.collection == 'playlists' and body.offset == 0 else 50
        items = [self.row(r, principal, body.player, binding) for r in raw[body.offset:body.offset + size]]
        return {'items': [r for r in items if r], 'view': body.view, 'collection': body.collection,
                'offset': body.offset, 'total': total, 'more': body.offset + size < total,
                'next_offset': body.offset + size, 'pending': pending, 'unavailable_shows': failed,
                'truncated': limited}

    def listing(self, body, principal):
        with self.music.lock:
            binding = self.context(body.player)
            self.prune()
            if body.collection != 'library':
                return self.shelf(body, principal, binding)
            if body.view == 'queue':
                if body.selection or body.query: raise ValueError('Queue browsing does not accept a search or folder')
                state = self.music.request('player_queues/get', queue_id=body.player)
                if not isinstance(state, dict) or state.get('queue_id') != body.player:
                    raise GroupMusicUnavailable('The selected player has no Music Assistant queue')
                raw = self.music.request('player_queues/items', queue_id=body.player, limit=50, offset=body.offset)
                total = state.get('items') if type(state.get('items')) is int else 0
                current = (state.get('current_item') or {}).get('queue_item_id')
            elif body.view == 'search':
                if body.selection or body.offset: raise ValueError('Search does not accept a folder or offset')
                query = body.query.strip()
                if not query or any(ord(c) < 32 for c in query): raise ValueError('Enter a song, album, artist or playlist name')
                found = self.music.request('music/search', search_query=query,
                                          media_types=['track', 'album', 'playlist', 'radio'], limit=16,
                                          **({'providers': ['spotify']} if body.source == 'spotify' else {}))
                if not isinstance(found, dict): raise GroupMusicUnavailable('Invalid Music Assistant search response')
                raw = []
                for key in ('tracks', 'albums', 'playlists', 'radio'):
                    values = found.get(key, [])
                    if not isinstance(values, list): raise GroupMusicUnavailable('Invalid Music Assistant search response')
                    raw.extend(values[:16])
                total = len(raw); current = None
            else:
                if body.query or body.offset: raise ValueError('Folder browsing does not accept a search or offset')
                path = 'root'
                if body.selection:
                    selected = self.choice(principal, body.player, body.selection, binding)
                    if selected['kind'] == 'podcast':
                        return self.shelf(body.model_copy(update={'collection': 'podcasts', 'source': 'spotify'}), principal, binding)
                    if selected['kind'] != 'folder': raise ValueError('Choose a music folder')
                    path = selected['value']
                raw = self.music.request('music/browse', path=path, player_id=body.player)
                if path == 'root' and body.source == 'spotify' and isinstance(raw, list):
                    raw = [r for r in raw if r.get('provider') == 'spotify']
                    if len(raw) == 1:
                        raw = self.music.request('music/browse', path=raw[0]['path'], player_id=body.player)
                total = len(raw) if isinstance(raw, list) else 0; current = None
            if not isinstance(raw, list): raise GroupMusicUnavailable('Invalid Music Assistant library response')
            items = []
            for item in raw[:100]:
                row = self.row(item, principal, body.player, binding, queue=body.view == 'queue')
                if row:
                    row['current'] = bool(current and item.get('queue_item_id') == current)
                    items.append(row)
            return {'items': items, 'view': body.view, 'offset': body.offset, 'total': total,
                    'more': body.view == 'queue' and body.offset + len(raw) < total,
                    'truncated': body.view == 'browse' and total > 100}

    def play(self, body, principal):
        with self.music.lock:
            if not self.music.actions_enabled: raise PermissionError('Music playback is disabled on the validation host')
            binding = self.context(body.player)
            selected = self.choice(principal, body.player, body.selection, binding)
            if selected['kind'] not in self.playable | {'queue'}: raise ValueError('Choose a playable item')
            # Consume before dispatch: a lost response must not start the same request twice.
            self.choices.pop(body.selection)
            if selected['kind'] == 'queue':
                self.music.request('player_queues/play_index', queue_id=body.player, index=selected['value'])
            else:
                self.music.request('player_queues/play_media', queue_id=body.player,
                                   media=selected['value'], option='replace')
            return {'status': 'accepted', 'text': 'Playback requested on the selected output. Check its refreshed state.'}


def install(app, music, authorize, call):
    library = MusicLibrary(music)
    app.state.music_library = library

    @app.post('/v1/music/groups/library')
    def listing(body: LibraryRequest, principal=Depends(authorize)):
        return call(lambda: library.listing(body, principal))

    @app.post('/v1/music/groups/library/play')
    def play(body: LibraryPlay, principal=Depends(authorize)):
        return call(lambda: library.play(body, principal))
