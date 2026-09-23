"""Opt-in Music Assistant player groups with owner-selected outputs."""
import base64
import hashlib
from ipaddress import ip_address,ip_network
import json
from pathlib import Path
import re
import time
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,field_validator


class GroupMusicUnavailable(RuntimeError):pass


class GroupMusicConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    enabled:bool=False
    url:str=Field(default='',max_length=200)
    players:list[str]=Field(default_factory=list,max_length=32)
    receivers:list[str]=Field(default_factory=list,max_length=32)
    max_volume:int=Field(default=30,ge=1,le=100)
    round_enabled:bool=False
    round_name:str=Field(default='Echo Mini',min_length=1,max_length=60)
    round_volume:int=Field(default=2,ge=0,le=20)
    round_latency_ms:int=Field(default=0,ge=-200,le=200)

    @field_validator('round_name')
    @classmethod
    def round_label(cls,value):
        if value!=value.strip() or any(ord(c)<32 for c in value):raise ValueError('Use a printable Mini player name without surrounding spaces')
        return value

    @field_validator('url')
    @classmethod
    def private_origin(cls,value):
        if not value:return value
        url=urlsplit(value)
        try:
            local=url.hostname in {'localhost','echo-music'} or any(ip_address(url.hostname or '') in ip_network(net) for net in
                ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8','100.64.0.0/10','::1/128','fc00::/7'))
            port=url.port
        except ValueError:raise ValueError('Use a private Music Assistant IP address or the echo-music container') from None
        if not local or url.scheme not in {'http','https'} or url.username is not None or url.password is not None or url.path not in {'','/'} or url.query or url.fragment or port==0:
            raise ValueError('Use a private Music Assistant origin without a path or credentials')
        return value.rstrip('/')

    @field_validator('players')
    @classmethod
    def identifiers(cls,value):
        if len(set(value))!=len(value) or any(not re.fullmatch(r'[A-Za-z0-9_:.-]{1,160}',v) for v in value):raise ValueError('Choose unique Music Assistant players')
        return value

    @field_validator('receivers')
    @classmethod
    def receiver_ids(cls,value):
        if len(set(value))!=len(value) or any(not re.fullmatch(r'[a-f0-9]{32}',v) for v in value):raise ValueError('Choose paired displays once')
        return value


class GroupMusic:
    def __init__(self,root,protector,*,transport=None,enabled=True):
        self.path=Path(root)/'local/echo-group-music.json' if root else None
        self.protector,self.transport,self.actions_enabled=protector,transport,enabled
        self.lock=RLock();self.config=GroupMusicConfig();self.token='';self.setup_token='';self.revision=0;self.error=False
        self.paused_queues={}
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size>100_000:raise ValueError()
                envelope=json.loads(self.path.read_text(encoding='utf-8'))
                if envelope['version']!=1:raise ValueError()
                saved=json.loads(protector.decrypt(base64.b64decode(envelope['protected'],validate=True)))
                self.config=GroupMusicConfig.model_validate(saved['config']);self.token=saved['token'];self.revision=saved['revision']
                self.setup_token=saved.get('setup_token','')
                if not isinstance(self.setup_token,str) or len(self.setup_token)>4096:raise ValueError()
                if not isinstance(self.token,str) or len(self.token)>4096 or type(self.revision) is not int or self.revision<0:raise ValueError()
            except (OSError,ValueError,KeyError,TypeError,RuntimeError):self.error=True

    def settings(self):
        with self.lock:
            if self.error:raise GroupMusicUnavailable('Saved grouped-music settings are unreadable; the original file was preserved')
            return {'config':self.config.model_dump(),'revision':self.revision,'token_saved':bool(self.token),'setup_token_saved':bool(self.setup_token)}

    def configure(self,config,token,revision,setup_token=None):
        config=GroupMusicConfig.model_validate(config)
        with self.lock:
            self.settings()
            if revision!=self.revision:raise HTTPException(409,'Grouped-music settings changed. Reload before saving.')
            secret=self.token if token is None else token
            setup_secret=(self.setup_token if config.url==self.config.url else '') if setup_token is None else setup_token
            if config.enabled and (not config.url or not secret):raise ValueError('Set the private server URL and an access token before enabling grouped music')
            if config.url!=self.config.url and self.token and token is None:raise ValueError('Enter the token for the new server; saved credentials are not forwarded to a different origin')
            if self.path:
                raw=self.protector.encrypt(json.dumps({'config':config.model_dump(),'token':secret,'setup_token':setup_secret,'revision':self.revision+1}).encode())
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.path.with_suffix('.new')
                try:
                    temporary.write_text(json.dumps({'version':1,'protected':base64.b64encode(raw).decode()}),encoding='utf-8');temporary.replace(self.path)
                except OSError:raise GroupMusicUnavailable('Grouped-music settings could not be saved') from None
            self.config,self.token,self.setup_token=config,secret,setup_secret;self.revision+=1
            return self.settings()

    def request(self,command,*,_timeout=15,_setup=False,**args):
        if not self.config.enabled:raise GroupMusicUnavailable('Connect Music Assistant in Settings to use grouped music')
        if _setup and command not in {'config/providers/setup','config/providers/reconfigure','config/flows/get','config/flows/submit','config/flows/abort'}:raise ValueError('This command cannot use provider setup credentials')
        if _setup and not self.setup_token:raise GroupMusicUnavailable('Add a Music Assistant provider-setup token in Settings → Music Assistant to connect Spotify')
        try:
            with httpx.Client(transport=self.transport,trust_env=False,follow_redirects=False,timeout=httpx.Timeout(_timeout,connect=4)) as client:
                with client.stream('POST',self.config.url+'/api',headers={'Authorization':'Bearer '+(self.setup_token if _setup else self.token)},
                    json={'message_id':'echo','command':command,'args':args}) as response:
                    if response.status_code in {401,403}:raise GroupMusicUnavailable('Music Assistant rejected this token or its player permissions')
                    if response.status_code==503:raise GroupMusicUnavailable('Music Assistant is unavailable or needs its first-run setup')
                    response.raise_for_status();content=bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        # Episode APIs return full show archives with descriptions in one response.
                        limit=16_000_000 if command=='music/podcasts/podcast_episodes' else 2_000_000
                        if len(content)>limit:raise ValueError()
                    return json.loads(content)
        except (httpx.HTTPError,ValueError):raise GroupMusicUnavailable('Music Assistant could not confirm the request. Check its current state before trying again.') from None

    def inventory(self):
        items=self.request('players/all')
        if not isinstance(items,list) or len(items)>512:raise GroupMusicUnavailable('Invalid Music Assistant player inventory')
        rows={}
        for item in items:
            if not isinstance(item,dict) or not re.fullmatch(r'[A-Za-z0-9_:.-]{1,160}',str(item.get('player_id',''))):
                raise GroupMusicUnavailable('Invalid Music Assistant player inventory')
            row=dict(item)
            for key in ('group_members','supported_features','can_group_with'):
                value=row.get(key) or []
                if not isinstance(value,list) or len(value)>512 or any(not isinstance(v,str) or len(v)>160 for v in value):
                    raise GroupMusicUnavailable('Invalid Music Assistant player capabilities')
                row[key]=value
            for key in ('synced_to','active_group','provider'):
                if row.get(key) is not None and not isinstance(row[key],str):raise GroupMusicUnavailable('Invalid Music Assistant group')
            if row['player_id'] in rows:raise GroupMusicUnavailable('Ambiguous Music Assistant player inventory')
            rows[row['player_id']]=row
        return rows

    @staticmethod
    def related(identifier,items):
        found=set();todo=[identifier]
        while todo:
            item=todo.pop()
            if item in found:continue
            found.add(item);row=items.get(item,{})
            todo.extend(x for x in [row.get('synced_to'),row.get('active_group'),*row.get('group_members',[])] if isinstance(x,str) and x not in found)
            # A provider may describe membership on only one side of the relationship.
            todo.extend(key for key,value in items.items() if key not in found and
                (value.get('synced_to')==item or value.get('active_group')==item or item in value.get('group_members',[])))
        return found

    def allowed(self,identifier,items,*,require_available=True):
        if identifier not in self.config.players:raise PermissionError('This player is not shared with Echo')
        row=items.get(identifier)
        if not row or (require_available and row.get('available') is not True):raise GroupMusicUnavailable('This player is unavailable')
        if not self.related(identifier,items)<=set(self.config.players):raise PermissionError('This group includes an output not shared with Echo. Change its membership in Music Assistant first.')
        return row

    def binding(self,rows,allowed):
        return hashlib.sha256(json.dumps({k:{field:v.get(field) for field in ('provider','available','synced_to','active_group','group_members','can_group_with','supported_features')} for k,v in rows.items() if k in allowed},sort_keys=True).encode()).hexdigest()

    @staticmethod
    def queue_item(identifier,row):
        """Only control this player's own active library queue, never another source."""
        media=row.get('current_media') or {}
        if (isinstance(media,dict) and row.get('active_source')==identifier
                and media.get('source_id')==identifier and isinstance(media.get('queue_item_id'),str)):
            return media['queue_item_id']
        return None

    def snapshot(self,discovery=False):
        with self.lock:
            settings=self.settings()
            if not self.config.enabled:return {'status':'not_configured','items':[],'revision':self.revision,'max_volume':self.config.max_volume}
            rows=self.inventory();allowed=set(rows) if discovery else set(self.config.players);items=[]
            for identifier,row in rows.items():
                if identifier not in allowed:continue
                media=row.get('current_media') or {}
                if not isinstance(media,dict):media={}
                art=re.fullmatch(r'/imageproxy/([a-f0-9]{64})',urlsplit(str(media.get('image_url') or '')).path)
                duration=media.get('duration') or 0
                elapsed=media.get('elapsed_time') or 0
                updated=media.get('elapsed_time_last_updated') or time.time()
                state=str(row.get('playback_state',row.get('state','unknown')))[:30]
                queue_item=self.queue_item(identifier,row)
                paused=self.paused_queues.get(identifier)
                if paused and (paused[0]!=queue_item or (state=='playing' and time.monotonic()-paused[1]>3)):
                    self.paused_queues.pop(identifier,None);paused=None
                if paused and state in {'idle','stopped'}:state='paused'
                playing=state=='playing'
                features=list(row.get('supported_features',[]))
                if queue_item and 'pause' not in features:features.append('pause')
                if not isinstance(duration,(int,float)):duration=0
                if not isinstance(elapsed,(int,float)):elapsed=0
                if not isinstance(updated,(int,float)):updated=time.time()
                items.append({'id':identifier,'name':str(row.get('display_name') or row.get('name') or identifier)[:120],
                    'provider':str(row.get('provider') or '')[:120],'available':row.get('available') is True,
                    'state':state,'queue_playback':bool(queue_item),
                    'volume':row.get('volume_level') if type(row.get('volume_level')) is int else None,'muted':row.get('volume_muted') is True,
                    'features':features,'members':[x for x in row.get('group_members',[]) if x in allowed and x!=identifier],
                    'leader':row.get('synced_to') if row.get('synced_to') in allowed else None,
                    'in_group':bool(row.get('synced_to') or row.get('active_group')),
                    'blocked':not self.related(identifier,rows)<=allowed,
                    'compatible':[key for key,child in rows.items() if key!=identifier and key in allowed and
                        (key in row.get('can_group_with',[]) or child.get('provider') in row.get('can_group_with',[]))],
                    'title':str(media.get('title') or '')[:200],'artist':str(media.get('artist') or '')[:200],
                    'album':str(media.get('album') or '')[:200],
                    'artwork':f'/v1/music/groups/artwork/{identifier}/{art[1]}' if art else '',
                    'duration_ms':max(0,int(duration*1000)),
                    'position_ms':max(0,int((elapsed+(max(0,time.time()-updated) if playing else 0))*1000))})
            binding=self.binding(rows,allowed)
            return {'status':'available','items':items,'revision':settings['revision'],'binding':binding,'max_volume':self.config.max_volume}

    def control(self,action,identifier,value,revision):
        with self.lock:
            self.settings()
            if not self.actions_enabled:raise PermissionError('Music control is disabled on the validation host')
            if revision!=self.revision:raise HTTPException(409,'Music permissions changed. Reload before controlling a player.')
            rows=self.inventory();player=self.allowed(identifier,rows)
            features=player.get('supported_features',[])
            queue_item=self.queue_item(identifier,player)
            if action in {'play','pause','stop','next','previous'} and value is None:
                if action=='pause' and 'pause' not in features and not queue_item:raise ValueError('This player does not support pause')
                # Queue pause saves resume_pos even when Sendspin closes its audio stream.
                if queue_item:
                    args={'queue_id':identifier};command='player_queues/'+action
                else:
                    args={'player_id':identifier};command='players/cmd/'+action
            elif action=='volume' and type(value) is int and 0<=value<=self.config.max_volume:
                if 'volume_set' not in features:raise ValueError('This player does not support volume control')
                command='players/cmd/volume_set';args={'player_id':identifier,'volume_level':value}
            elif action=='mute' and type(value) is bool:
                if 'volume_mute' not in features:raise ValueError('This player does not support mute')
                command='players/cmd/volume_mute';args={'player_id':identifier,'muted':value}
            else:raise ValueError('Unsupported music command or volume above the owner limit')
            self.request(command,**args)
            if action=='pause' and queue_item:self.paused_queues[identifier]=(queue_item,time.monotonic())
            elif action in {'play','stop','next','previous'}:self.paused_queues.pop(identifier,None)
            return {'status':'accepted','text':'Music Assistant accepted the command. The displayed state refreshes shortly.'}

    def members(self,leader,members,revision,binding):
        with self.lock:
            self.settings()
            if not self.actions_enabled:raise PermissionError('Grouping is disabled on the validation host')
            if revision!=self.revision:raise HTTPException(409,'Music permissions changed. Reload before grouping.')
            rows=self.inventory()
            if self.binding(rows,set(self.config.players))!=binding:raise HTTPException(409,'Player membership or availability changed. Review the group again.')
            target=self.allowed(leader,rows)
            if 'set_members' not in target.get('supported_features',[]):raise ValueError('This output does not support grouping')
            if target.get('synced_to') or target.get('active_group'):raise ValueError('Choose the group leader, not one of its members')
            if leader in members or len(members)!=len(set(members)):raise ValueError('Choose each additional output once')
            current=set(target.get('group_members',[]))-{leader}
            for member in members:
                child=self.allowed(member,rows,require_available=member not in current)
                if child.get('synced_to') not in (None,leader) or child.get('active_group'):raise ValueError('Remove the player from its current group before moving it')
                if not child.get('synced_to') and set(child.get('group_members',[]))-{member,leader}:raise ValueError('This member is already leading another group')
                if member not in target.get('can_group_with',[]) and child.get('provider') not in target.get('can_group_with',[]):raise ValueError('These players do not advertise compatible grouping')
            add=set(members)-current;remove=current-set(members)
            if add or remove:self.request('players/cmd/set_members',target_player=leader,player_ids_to_add=sorted(add),player_ids_to_remove=sorted(remove))
            return {'status':'accepted','text':'Group membership was sent to Music Assistant. Review the refreshed player list.'}


class ConfigureGroupMusic(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=0)
    config:GroupMusicConfig
    token:str|None=Field(default=None,max_length=4096)
    setup_token:str|None=Field(default=None,max_length=4096)

    @field_validator('token','setup_token')
    @classmethod
    def token_format(cls,value):
        if value is not None and any(ord(c)<33 or ord(c)>126 for c in value):raise ValueError('Paste a token without whitespace')
        return value


class MusicControl(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=0)
    player:str=Field(min_length=1,max_length=160)
    action:Literal['play','pause','stop','next','previous','volume','mute']
    value:int|bool|None=None


class MusicMembers(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=0)
    binding:str=Field(pattern=r'^[a-f0-9]{64}$')
    leader:str=Field(min_length=1,max_length=160)
    members:list[str]=Field(max_length=31)


def install(app,music,authorize,owner,displays=None):
    app.state.group_music=music
    def call(fn):
        try:return fn()
        except GroupMusicUnavailable as error:raise HTTPException(503,str(error)) from None
        except PermissionError as error:raise HTTPException(403,str(error)) from None
        except ValueError as error:raise HTTPException(422,str(error)) from None
    @app.get('/v1/music/groups/settings',dependencies=[Depends(owner)])
    def settings():return call(music.settings)
    @app.put('/v1/music/groups/settings',dependencies=[Depends(owner)])
    def configure(body:ConfigureGroupMusic):
        if displays is not None and not set(body.config.receivers)<={d['id'] for d in displays.snapshot() if d['profile']['mode']=='household'}:
            raise HTTPException(422,'Choose currently paired Household displays as native receivers')
        return call(lambda:music.configure(body.config.model_dump(),body.token,body.revision,body.setup_token))
    @app.get('/v1/music/groups/discovery',dependencies=[Depends(owner)])
    def discover():return call(lambda:music.snapshot(discovery=True))
    @app.get('/v1/music/groups',dependencies=[Depends(authorize)])
    def groups():return call(music.snapshot)
    @app.get('/v1/music/groups/artwork/{identifier}/{digest}',dependencies=[Depends(authorize)])
    def artwork(identifier:str,digest:str):
        from fastapi import Response
        if not re.fullmatch(r'[A-Za-z0-9_:.-]{1,160}',identifier) or not re.fullmatch(r'[a-f0-9]{64}',digest):raise HTTPException(404,'Artwork unavailable')
        def load():
            with music.lock:
                music.settings();row=music.allowed(identifier,music.inventory());revision=music.revision
                path='/imageproxy/'+digest
                if urlsplit(str((row.get('current_media') or {}).get('image_url') or '')).path!=path:raise HTTPException(404,'Artwork changed')
                origin,token=music.config.url,music.token
            try:
                with httpx.Client(timeout=5,trust_env=False,follow_redirects=False,transport=music.transport) as client:
                    with client.stream('GET',origin+path+'?size=512&fmt=jpg',headers={'Authorization':'Bearer '+token}) as response:
                        response.raise_for_status();raw=bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw)>2_000_000:raise ValueError()
                if not raw.startswith(b'\xff\xd8'):raise ValueError()
            except (httpx.HTTPError,ValueError):raise HTTPException(502,'Artwork unavailable') from None
            with music.lock:
                if music.revision!=revision or identifier not in music.config.players:raise HTTPException(403,'Output access changed')
            return Response(bytes(raw),media_type='image/jpeg',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
        return call(load)
    @app.post('/v1/music/groups/control',dependencies=[Depends(authorize)])
    def control(body:MusicControl):return call(lambda:music.control(body.action,body.player,body.value,body.revision))
    @app.post('/v1/music/groups/members',dependencies=[Depends(authorize)])
    def members(body:MusicMembers):return call(lambda:music.members(body.leader,body.members,body.revision,body.binding))
    from .group_stream import install as install_stream
    install_stream(app,music,authorize)
    from .music_library import install as install_library
    install_library(app,music,authorize,call)
    from .spotify_account import install as install_spotify
    install_spotify(app,music,authorize,owner,call)
