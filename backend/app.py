"""Loopback device API and Echo app. Cloud conversation requires explicit settings."""
import os
from pathlib import Path
import secrets
from functools import partial
from threading import Lock, Event, Thread
from typing import Literal
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ConfigDict, StrictInt, StrictBool, StrictStr
from .core import Assistant, TimerStorageUnavailable
from .home import HomeBridge, HomeConfig, HomeUnavailable
from .home_catalog import HomeCatalog
from .home_lights import RoomLights
from .home_speakers import HomeSpeakers
from .home_access import HomeAccessStore, HomeAccessUnavailable
from .home_policy import apply_policy, validate_policy
from .home_actions import HomeActions, ActionRequest
from .home_sync import sync_home_policy
from .voice_status import voice_status
from .speech import voices as speech_voices
from .speech import synthesize_checked
from .tts_catalog import catalog as tts_catalog, validate_selection, selected_status
from .settings import EchoSettings, SettingsStore, SettingsUpdate, SettingsUnavailable
from .agent import EchoAgent, Provider, ProviderUnavailable
from .conversation_request import run_conversation
from .conversation_activity import Conversations, ConversationBusy
from .routines import RoutineStore, Routines, RoutineStep, RoutineUnavailable, RoutineConflict, routine_request
from .http_headers import BrowserHeadersMiddleware
from .web_auth import BrowserAuth
from .speech_restart import SpeechRestart
from .memory import MemoryStore, MemoryUnavailable, memory_request
from .lookup import lookup_request
from .agent_runtime import RuntimeUnavailable
from .agent_apply import AgentApply
from .music_commands import request as request_music
from .speaker_check import SpeakerCheck
from .whisper import available as whisper_available
from .research_tasks import ResearchTasks
from .household import HouseholdStore, HouseholdUnavailable, HouseholdConflict
from .schedules import ScheduleStore,ScheduleUnavailable
from .schedule_api import install as install_schedules
from .audio_destination import destination_for
from .display_alerts import DisplayAlerts, install as install_display_alerts
from .household_commands import parse as household_request
from .display_auth import Displays,DisplayStorageUnavailable
from .display_profiles import DisplayProfile,GuestSettings,ProfileAgent,home_view
from .round_profile import RoundProfile,RoundProfileUnavailable
from .round_home import RoundHome
from .experiences import SourceStore, Experiences
from .experience_api import install as install_experiences
from .calendar_events import CalendarWriter
from .daily_briefing import DailyBriefing, briefing_request
from .calendar_drafts import CalendarDrafts, draft_request
from .doorbells import Doorbells
from .announcements import Announcements, AnnouncementUnavailable
from .announcement_api import install as install_announcements
from .group_music import GroupMusic,install as install_group_music
from .intercom import Intercom
from .intercom_api import install as install_intercom
from .photos import Photos
from .photo_api import install as install_photos
from .media_presets import MediaPresets, install as install_media
from .display_voice import DisplayVoice, install as install_display_voice
from . import __version__

def create_app(token: str, home: HomeBridge | None = None, runtime_root: Path | None = None,
               *, settings_store=None, provider=None, home_catalog=None, home_access_store=None,
               deployment_mode='device', home_tools_token=None):
    if deployment_mode not in {'device','validation'}: raise ValueError('Invalid deployment mode')
    if len(token) < 32:
        raise ValueError("A local API token of at least 32 characters is required")
    @asynccontextmanager
    async def lifespan(app):
        scheduler_stop=Event()
        def run_schedules():
            while not scheduler_stop.is_set():
                try: schedules.tick(); app.state.schedule_error=False
                except ScheduleUnavailable: app.state.schedule_error=True
                scheduler_stop.wait(1)
        scheduler_thread=Thread(target=run_schedules,name='echo-schedules',daemon=True)
        scheduler_thread.start()
        def watch_doorbells():
            while not scheduler_stop.is_set():
                doorbells.tick()
                scheduler_stop.wait(1.5)
        doorbell_thread=Thread(target=watch_doorbells,name='echo-doorbells',daemon=True)
        doorbell_thread.start()
        try: yield
        finally:
            scheduler_stop.set(); scheduler_thread.join(timeout=3)
            doorbell_thread.join(timeout=4)
            app.state.speech_stop.set()
            display_voice.close()
            research.close()
            from .neural_speech import close
            close()
    app = FastAPI(title="Round Voice", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.speech_stop = Event()
    assistant = Assistant(storage=runtime_root/'local/timers.json' if runtime_root else None)
    home = home or HomeBridge(HomeConfig())
    store = settings_store or SettingsStore(runtime_root)
    household = HouseholdStore(runtime_root, store.protector)
    schedules = ScheduleStore(runtime_root,store.protector)
    memory = MemoryStore(runtime_root, store.protector)
    echo = EchoAgent(store, provider, memory)
    echo.household = household
    echo.local_assistant = assistant
    research = ResearchTasks(store)
    conversations = Conversations()
    catalog = home_catalog or HomeCatalog(home)
    if home_tools_token is not None and len(home_tools_token) < 32: raise ValueError('Invalid home tools credential')
    access = home_access_store or HomeAccessStore(runtime_root, store.protector,
        (lambda policy: None) if home_tools_token else sync_home_policy)
    if home_tools_token: access.ensure_applied()
    echo.home_access = access
    room_lights = RoomLights(home,catalog,access)
    speakers = HomeSpeakers(home,catalog,runtime_root,store.protector)
    actions = HomeActions(home, access, enabled=deployment_mode=='device')
    echo.home_actions = actions
    routines = Routines(RoutineStore(runtime_root,store.protector),actions)
    echo.routines = routines
    auth = BrowserAuth(token)
    round_profile=RoundProfile(runtime_root,store.protector)
    displays = Displays(runtime_root,store.protector,round_profile=round_profile)
    round_home=RoundHome(home,catalog,actions,displays,round_profile)
    guest_echo=EchoAgent(GuestSettings(store),echo.provider,MemoryStore(None,store.protector))
    from .guest_home import GuestHome
    profiled_echo=ProfileAgent(echo,guest_echo,displays,GuestHome(catalog,actions,displays))
    speech_restart = SpeechRestart(runtime_root)
    speaker_check = SpeakerCheck(runtime_root)
    agent_apply = AgentApply(runtime_root, store)
    voice_check_lock = Lock()
    def authorize(request:Request):
        header=request.headers.get('authorization','')
        if request.headers.get('x-echo-endpoint'):
            auth.bearer(request)
            if request.headers['x-echo-endpoint']!='round':raise HTTPException(403,'Unknown host endpoint')
            return round_profile.authorize(request)
        if header.startswith('Display '): return displays.authorize(request)
        if header.startswith('Bearer ') or request.cookies.get('echo_session'): return auth.authorize(request)
        if request.cookies.get('echo_display_session'): return displays.authorize(request)
        return auth.authorize(request)
    def owner(request:Request):
        principal=authorize(request)
        if principal=='round' or principal.startswith('display:'): raise HTTPException(403,'Open the owner workspace to manage displays')
    install_group_music(app,GroupMusic(runtime_root,store.protector,enabled=deployment_mode=='device'),authorize,owner,displays)
    install_schedules(app,schedules,authorize)
    install_display_alerts(app,DisplayAlerts(assistant,schedules),authorize)
    announcements=Announcements(runtime_root,store.protector,displays,schedules,
        lambda:voice_status(runtime_root) if runtime_root else {'status':'disconnected'})
    install_announcements(app,announcements,store,authorize,owner)
    install_intercom(app,Intercom(announcements),authorize)
    experiences = Experiences(home, SourceStore(runtime_root, store.protector))
    doorbells=Doorbells(experiences,runtime_root,store.protector)
    briefing=DailyBriefing(experiences,home,schedules,household)
    echo.briefing=briefing
    echo.calendar_drafts=CalendarDrafts(store,echo.provider,experiences,schedules)
    install_experiences(app, experiences, authorize, owner,
        CalendarWriter(experiences,runtime_root,store.protector,enabled=deployment_mode=='device'),briefing,doorbells,echo.calendar_drafts,displays)
    install_photos(app, Photos(runtime_root, store.protector), authorize, owner)
    install_media(app, MediaPresets(runtime_root, store.protector), authorize, owner)
    display_voice=DisplayVoice(runtime_root,store,profiled_echo)
    install_display_voice(app,display_voice,authorize,conversations,app.state.speech_stop,enable_home=deployment_mode=='device',profile_state=displays.profile_for)
    hosts = ['127.0.0.1', 'localhost', 'testserver'] if runtime_root is None else ['127.0.0.1', 'localhost']
    if os.environ.get('ECHO_CONTAINER') == '1': hosts += ['api', 'echo-api']
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    web = Path(__file__).resolve().parents[1]/'web'
    app.mount('/assets', StaticFiles(directory=web), name='assets')

    app.add_middleware(BrowserHeadersMiddleware)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI's default includes submitted input, which may be an API key.
        return JSONResponse(status_code=422, content={'detail': 'Invalid settings or request. Check field values and limits.'})

    @app.exception_handler(SettingsUnavailable)
    async def settings_error(request, error):
        return JSONResponse(status_code=503, content={'detail': str(error)})

    @app.get('/')
    @app.get('/settings')
    @app.get('/devices')
    @app.get('/routines')
    @app.get('/tasks')
    def ui(): return FileResponse(web/'index.html')

    @app.get('/display')
    def smart_display(): return FileResponse(web/'display/index.html')

    @app.exception_handler(DisplayStorageUnavailable)
    async def display_storage_error(request,error): return JSONResponse({'detail':str(error)},status_code=503)

    @app.exception_handler(RoundProfileUnavailable)
    async def round_profile_error(request,error):return JSONResponse({'detail':str(error)},status_code=503)

    class PairDisplay(BaseModel):
        model_config=ConfigDict(extra='forbid')
        name:str=Field(min_length=1,max_length=60)

    class EnrollDisplay(BaseModel):
        model_config=ConfigDict(extra='forbid')
        code:str=Field(min_length=32,max_length=64)

    class SetDisplayProfile(BaseModel):
        model_config=ConfigDict(extra='forbid',strict=True)
        revision:int=Field(ge=0)
        profile:DisplayProfile

    @app.put('/v1/displays/{identifier}/profile',dependencies=[Depends(owner)])
    def set_display_profile(identifier:str,body:SetDisplayProfile):
        # A profile change must not race a household tool call already in progress.
        principal='display:'+identifier
        if conversations.snapshot(principal).get('active'):
            conversations.clear(principal)
            raise HTTPException(409,'The active request is stopping. Save display access again when it has finished.')
        profile=body.profile.model_dump()
        previous=displays.profile_for(principal)
        validate_guest_profile(profile,previous)
        result=displays.save_profile(identifier,profile,body.revision)
        echo.clear(principal);guest_echo.clear(principal);conversations.clear(principal)
        return result

    def validate_guest_profile(profile,previous):
        if profile['mode']=='guest':
            old=previous['profile']['home_devices']
            added={entity:grant for entity,grant in profile['home_devices'].items() if old.get(entity)!=grant and not (old.get(entity)=='control' and grant=='read')}
            try:permitted=apply_policy(catalog.snapshot(),access.snapshot()['policy'])['devices'] if added else []
            except HomeUnavailable as error:raise HTTPException(503,'Home devices are unavailable. Try again before granting new access.') from error
            known={i['entity_id']:i['access'] for i in permitted}
            for entity,grant in added.items():
                if known.get(entity) not in ({'control'} if grant=='control' else {'read','control'}):
                    raise HTTPException(422,'Grant the requested device access on Devices before sharing it with a guest')
            sources=experiences.store.snapshot()['sources']
            if any(not set(profile[key])<=set(sources[key]) for key in ('calendars','cameras','presence_sensors')):
                raise HTTPException(422,'Share sources in Display settings before assigning them to a guest')
    @app.get('/v1/round/profile')
    def mini_access(principal=Depends(authorize)):
        if principal.startswith('display:'):raise HTTPException(403,'Open the owner workspace to manage Echo Mini')
        status=voice_status(runtime_root) if runtime_root else {}
        ready=status.get('status') not in {None,'connecting','disconnected'} and status.get('access_profile',{}).get('firmware',False)
        return {**round_profile.snapshot(),'firmware_ready':bool(ready)}

    @app.put('/v1/round/profile',dependencies=[Depends(owner)])
    def save_mini_access(body:SetDisplayProfile):
        with round_profile.lock:
            if conversations.snapshot('round').get('active'):
                conversations.clear('round');raise HTTPException(409,'The Mini request is stopping. Save access when it finishes.')
            profile=body.profile.model_dump();previous=round_profile.snapshot()
            if profile['mode']=='guest' and previous['profile']['mode']!='guest' and not mini_access('device')['firmware_ready']:
                raise HTTPException(409,'Connect Echo Mini with the current profile-aware firmware before enabling Guest mode.')
            validate_guest_profile(profile,previous)
            result=round_profile.save(profile,body.revision)
        echo.clear('round');guest_echo.clear('round');conversations.clear('round')
        return result

    @app.get('/v1/displays',dependencies=[Depends(owner)])
    def paired_displays(): return {'items':displays.snapshot()}

    @app.post('/v1/displays/pairing',dependencies=[Depends(owner)])
    def pair_display(body:PairDisplay):
        try:return displays.pairing(body.name)
        except ValueError as error:raise HTTPException(422,str(error)) from None

    @app.post('/v1/displays/enroll')
    def enroll_display(body:EnrollDisplay): return displays.enroll(body.code)

    @app.delete('/v1/displays/{identifier}',dependencies=[Depends(owner)])
    def revoke_display(identifier:str):
        if not displays.revoke(identifier): raise HTTPException(404,'Display not found')
        return {'revoked':True}

    @app.post('/v1/displays/session')
    def display_session(request:Request):
        auth.same_origin(request)
        session=displays.new_session(request.headers.get('authorization',''))
        response=JSONResponse({'authenticated':True,'role':'display'})
        response.set_cookie('echo_display_session',session,httponly=True,samesite='strict',max_age=8*3600)
        response.delete_cookie('echo_session'); return response

    @app.get('/v1/display/session')
    def current_display_session(session=Depends(authorize)):
        return {'role':'display' if session=='round' or session.startswith('display:') else 'owner',
                'receiver_id':session.split(':',1)[1] if session.startswith('display:') else None,
                **displays.profile_for(session)}

    @app.get('/v1/household', dependencies=[Depends(authorize)])
    def household_state(): return household.snapshot()

    class HouseholdCreate(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        revision: int = Field(ge=0)
        kind: Literal['shopping', 'tasks', 'notes']
        text: str = Field(min_length=1, max_length=500)

    class HouseholdEdit(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        revision: int = Field(ge=0)
        text: str | None = Field(default=None, min_length=1, max_length=500)
        done: bool | None = None
        position: int | None = Field(default=None,ge=0,le=199)

    class HouseholdDelete(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)
        revision: int = Field(ge=0)

    @app.exception_handler(HouseholdUnavailable)
    async def household_unavailable(request, error):
        return JSONResponse(status_code=503, content={'detail': str(error)})

    @app.exception_handler(HouseholdConflict)
    async def household_conflict(request, error):
        return JSONResponse(status_code=409, content={'detail': str(error)})

    def household_change(**values):
        try: return household.change(**values)
        except HouseholdConflict: raise
        except KeyError: raise HTTPException(404, 'This item no longer exists') from None
        except ValueError: raise HTTPException(422, 'Check the item text, category, and list capacity') from None

    @app.post('/v1/household', dependencies=[Depends(authorize)])
    def household_add(body: HouseholdCreate):
        return household_change(**body.model_dump())

    @app.patch('/v1/household/{identifier}', dependencies=[Depends(authorize)])
    def household_edit(identifier: str, body: HouseholdEdit):
        if body.text is None and body.done is None and body.position is None:
            raise HTTPException(422, 'Choose a change to make')
        return household_change(identifier=identifier, **body.model_dump())

    @app.delete('/v1/household/{identifier}', dependencies=[Depends(authorize)])
    def household_delete(identifier: str, body: HouseholdDelete):
        return household_change(identifier=identifier, delete=True, revision=body.revision)

    @app.post('/v1/ui/ticket', dependencies=[Depends(auth.bearer)])
    def ticket(): return {'ticket': auth.ticket()}

    class LoginRequest(BaseModel):
        ticket: str = Field(min_length=32, max_length=64)

    @app.post('/v1/ui/session')
    def login(body: LoginRequest, request: Request):
        auth.same_origin(request)
        session = auth.exchange(body.ticket)
        response = JSONResponse({'authenticated': True})
        response.set_cookie('echo_session', session, httponly=True, samesite='strict', max_age=8*3600)
        return response

    @app.delete('/v1/ui/session', dependencies=[Depends(authorize)])
    def logout(request: Request):
        session = request.cookies.get('echo_session', '')
        conversations.clear(session); research.clear(session); echo.clear(session); auth.logout(session)
        response = JSONResponse({'authenticated': False})
        response.delete_cookie('echo_session')
        return response

    @app.exception_handler(TimerStorageUnavailable)
    async def timer_storage_error(request, error):
        return JSONResponse(status_code=503, content={'detail': str(error)})

    class TextRequest(BaseModel):
        calendar_review: StrictBool = False
        text: str = Field(min_length=1, max_length=1200)
        lookup: bool = False
        allow_home_actions: bool = False

    class MemoryRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        text: str = Field(min_length=1,max_length=600)

    class TimerRequest(BaseModel):
        seconds: int = Field(strict=True, ge=1, le=86400)
        label: str = Field(default="Timer", min_length=1, max_length=80)

    class HomeAction(BaseModel):
        action: str = Field(min_length=1, max_length=40)
        value: float | bool | str | None = None
        unit: str | None = None

    class MusicAction(BaseModel):
        model_config = ConfigDict(extra='forbid')
        action: Literal['play','pause','toggle','next','previous','seek','volume','shuffle','repeat']
        value: StrictInt | StrictBool | StrictStr | None = None

    from .music_now_playing import snapshot as music_snapshot, Artwork
    artwork=Artwork()

    @app.get('/v1/display/music/now-playing',dependencies=[Depends(authorize)])
    @app.get('/v1/display/music/settings',dependencies=[Depends(authorize)])
    def display_music_unavailable():
        # A Pi loopback bridge provides these locally. Never fall back to a
        # different room's receiver when this browser has no audio adapter.
        return {'supported':False,'available':False,'status':'not_installed','capabilities':[]}

    @app.get('/v1/music/now-playing',dependencies=[Depends(authorize)])
    def music_now_playing():return JSONResponse(music_snapshot(runtime_root),headers={'Cache-Control':'no-store'})

    @app.get('/v1/music/artwork/{key}',dependencies=[Depends(authorize)])
    def music_artwork(key:str):
        import re
        if not re.fullmatch('[a-f0-9]{64}',key):raise HTTPException(404,'Cover unavailable')
        try:return Response(artwork.get(runtime_root,key),media_type='image/jpeg',headers={'Cache-Control':'no-store'})
        except (OSError,ValueError,KeyError):raise HTTPException(404,'Cover unavailable') from None

    @app.post('/v1/music/control',dependencies=[Depends(authorize)])
    def music_control(command:MusicAction):
        if deployment_mode=='validation':raise HTTPException(409,'Playback is disabled on the validation host')
        try:return request_music(runtime_root,command.action,command.value)
        except (ValueError,OSError) as error:raise HTTPException(409,str(error)) from None

    class HomeAccessRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        revision: str = Field(pattern=r'^[a-f0-9]{64}$')
        policy: dict

    @app.exception_handler(HomeAccessUnavailable)
    async def home_access_error(request, error):
        return JSONResponse(status_code=503, content={'detail': str(error)})

    @app.get('/v1/home/devices', dependencies=[Depends(authorize)])
    def home_devices():
        saved = access.snapshot()
        try:
            raw = catalog.snapshot()
            result = apply_policy(raw, saved['policy'], management=True)
            return {**result, **saved, 'ha_areas': raw['areas']}
        except HomeUnavailable as error:
            raise HTTPException(503, str(error)) from None

    @app.put('/v1/home/access', dependencies=[Depends(authorize)])
    def home_access(request: HomeAccessRequest):
        try:
            policy = validate_policy(request.policy)
            # Rules for previously seen devices may be retained when HA removes an
            # entity; new entries must have a current, actual HA entity binding.
            known = set(access.snapshot()['policy']['devices'])
            known.update(d['entity_id'] for d in catalog.snapshot()['devices'])
            if set(policy['devices']) - known: raise ValueError('Refresh the inventory before assigning a new device.')
            return access.update(policy, request.revision)
        except HomeUnavailable as error:
            raise HTTPException(503, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.post('/v1/home/access/retry', dependencies=[Depends(authorize)])
    def retry_home_access():
        access.ensure_applied()
        return access.snapshot()

    @app.get('/v1/display/home',dependencies=[Depends(authorize)])
    def display_home(session=Depends(authorize)):
        try:
            saved=access.snapshot()
            return {**home_view(apply_policy(catalog.snapshot(),saved['policy']),displays.profile_for(session)['profile']),'revision':saved['revision']}
        except HomeUnavailable as error: raise HTTPException(503,str(error)) from None

    class DisplayHomeAction(BaseModel):
        model_config=ConfigDict(extra='forbid',strict=True)
        revision:str=Field(pattern=r'^[a-f0-9]{64}$')
        entity_id:str
        action:str
        value:float|int|bool|str|dict[str,float]|None=None
        unit:Literal['°C','°F']|None=None

    @app.post('/v1/display/home/control',dependencies=[Depends(authorize)])
    def display_home_action(body:DisplayHomeAction,session=Depends(authorize)):
        profile=displays.profile_for(session)['profile']
        if profile['mode']=='guest' and profile['home_devices'].get(body.entity_id)!='control':
            raise HTTPException(403,'This device is not shared for guest control')
        if deployment_mode!='device': raise HTTPException(409,'Home actions are disabled in validation mode')
        if access.snapshot()['revision']!=body.revision: raise HTTPException(409,'Device permissions changed. Refresh before trying again.')
        try:
            with actions.scope(True,body.revision) as scope:
                command=ActionRequest(request_id=scope.id,**body.model_dump(exclude={'revision'}))
                result=actions.execute(command)
                if result['status']=='denied': raise HTTPException(403,result.get('error','Device control is not allowed'))
                return {**result,'text':{'complete':'The device reports the requested state.','accepted':'Command accepted; physical state is not confirmed.','unconfirmed':'The device did not confirm the change. Check its current state before retrying.','unavailable':'The device is unavailable.'}.get(result['status'],'Device request is busy.')}
        except ValueError as error: raise HTTPException(422,str(error)) from None

    @app.get("/health")
    def health():
        voice = voice_status(runtime_root) if runtime_root else {"status": "disconnected", "phrases": ["hey echo", "okay echo"]}
        connected = voice["status"] not in {"disconnected", "connecting"}
        waiting = voice['status'] == 'connecting'
        volume = voice.get('device', {}).get('volume')
        return {"product": "round-voice", "version": __version__, "status": "ready",
                'deployment_mode':deployment_mode,
                "speech_to_text": ('local_whisper' if voice.get('engine') == 'whisper-base.en-local' else 'local_vosk') if connected else 'waiting_for_device' if waiting else "not_configured", "text_to_speech": selected_status(store.snapshot()[0],runtime_root),
                "conversation": echo.status()['status'], "timers": "unavailable" if assistant.storage_error else "ready", "device_transport": (voice.get('transport', 'usb') + "_connected") if connected else (voice.get('transport', 'usb') + '_waiting') if waiting else "not_connected",
                "wake_word": voice["status"], "wake_phrases": voice["phrases"],
                "speaker_muted": (str(volume) == '0') if connected and volume is not None else None,
                "speech_worker": voice.get('speech_worker','unavailable') if connected else 'unavailable',
                "music_wake": voice.get('music_wake', 'unavailable') if connected else 'unavailable',
                "home_assistant": "configured" if home.config.enabled else "optional_not_configured",
                "spotify_connect": voice.get('music', {}).get('status', 'not_connected') if connected else 'not_connected'}

    @app.get("/v1/voice", dependencies=[Depends(authorize)])
    def voice_state():
        return voice_status(runtime_root) if runtime_root else {"status": "disconnected", "phrases": ["hey echo", "okay echo"]}

    @app.get("/v1/home", dependencies=[Depends(authorize)])
    def home_state(connection:Request,session=Depends(authorize)):
        if session=='round':
            return mini_control(connection,round_home.snapshot,household_home)
        profile=displays.profile_for(session)['profile']
        if profile['mode']=='guest':
            # Legacy room/speaker shortcuts have global bindings. Guests use the
            # filtered individual-device controls instead of those broad endpoints.
            devices={}
            if home.config.entities.get('weather') in profile['home_devices']:
                try:
                    permitted=home_view(apply_policy(catalog.snapshot(),access.snapshot()['policy']),displays.profile_for(session)['profile'])
                    weather=next((i for i in permitted['devices'] if i['entity_id']==home.config.entities['weather']),None)
                    if weather:devices['weather']={'status':'available' if weather['available'] else 'unavailable','state':weather['state'],
                        'attributes':{k:v for k,v in weather['attributes'].items() if k in {'temperature','temperature_unit','humidity'}}}
                except HomeUnavailable:pass
            return {'status':'available','devices':devices,'lights':{'status':'restricted','rooms':[]},
                    'speakers':{'status':'restricted','choices':[]}}
        return household_home()

    def household_home():
        result = home.snapshot()
        try: result['lights'] = room_lights.snapshot()
        except (HomeUnavailable,HomeAccessUnavailable): result['lights'] = {'status':'unavailable','rooms':[]}
        try:
            result['speakers']=speakers.snapshot()
            result['devices']['soundbar']=result['speakers']['device']
        except HomeUnavailable:
            result['speakers']={'status':'unavailable','choices':[]}
            result['devices']['soundbar']={'status':'unavailable'}
        return result

    def mini_control(connection,guest,household):
        # Recheck inside the same lock as profile writes. A queued request cannot
        # inherit household permissions when the owner changes its profile.
        with round_profile.lock:
            authorize(connection)
            try:return (guest if round_profile.snapshot()['profile']['mode']=='guest' else household)()
            except ValueError as error:raise HTTPException(409,str(error)) from None
            except HomeUnavailable as error:raise HTTPException(503,str(error)) from None

    class SpeakerSelection(BaseModel):
        model_config=ConfigDict(extra='forbid')
        index: int=Field(ge=0,le=31,strict=True)
        revision: str=Field(pattern=r'^[a-f0-9]{64}$')

    class SpeakerAction(BaseModel):
        model_config=ConfigDict(extra='forbid')
        action: Literal['up','down','mute','unmute','play','pause','on','off']
        binding: str=Field(pattern=r'^[a-f0-9]{64}$')

    @app.post('/v1/home/speakers/select',dependencies=[Depends(authorize)])
    def select_speaker(request:SpeakerSelection,connection:Request,session=Depends(authorize)):
        if session=='round':return mini_control(connection,lambda:round_home.select(request.index,request.revision),lambda:speakers.select(request.index,request.revision))
        try:return speakers.select(request.index,request.revision)
        except ValueError as error:raise HTTPException(409,str(error)) from None
        except HomeUnavailable as error:raise HTTPException(503,str(error)) from None

    @app.post('/v1/home/speakers/control',dependencies=[Depends(authorize)])
    def control_speaker(request:SpeakerAction,connection:Request,session=Depends(authorize)):
        if session=='round':return mini_control(connection,lambda:round_home.speaker(request.action,request.binding),lambda:speakers.action(request.action,request.binding))
        try:return speakers.action(request.action,request.binding)
        except ValueError as error:raise HTTPException(409,str(error)) from None
        except HomeUnavailable as error:raise HTTPException(503,str(error)) from None

    class RoomAction(BaseModel):
        model_config = ConfigDict(extra='forbid')
        action: Literal['turn_on','turn_off']
        revision: str = Field(pattern=r'^[a-f0-9]{64}$')

    @app.post('/v1/home/lights/{entity}/actions', dependencies=[Depends(authorize)])
    def light_action(entity: str, request: RoomAction):
        if deployment_mode=='validation': raise HTTPException(409,'Light controls are disabled on the validation host')
        try: return room_lights.light_action(entity,request.action,request.revision)
        except ValueError as error: raise HTTPException(409,str(error)) from None
        except HomeUnavailable as error: raise HTTPException(503,str(error)) from None

    @app.post('/v1/home/rooms/{room}/actions', dependencies=[Depends(authorize)])
    def room_action(room: str, request: RoomAction,connection:Request,session=Depends(authorize)):
        if session=='round':return mini_control(connection,lambda:round_home.room(room,request.action,request.revision),lambda:room_lights.action(room,request.action,request.revision))
        try: return room_lights.action(room,request.action,request.revision)
        except ValueError as error: raise HTTPException(409,str(error)) from None
        except HomeUnavailable as error: raise HTTPException(503,str(error)) from None

    if home_tools_token:
        def authorize_home_tools(request: Request):
            if not secrets.compare_digest(request.headers.get('authorization',''),'Bearer '+home_tools_token):
                raise HTTPException(401,'Home tool credential required')

        @app.get('/internal/home/devices', dependencies=[Depends(authorize_home_tools)])
        def agent_home_devices(domain: str = '', area: str = ''):
            try:
                current=apply_policy(catalog.snapshot(),access.snapshot()['policy'])
                current['devices']=[d for d in current['devices'] if (not domain or d['domain']==domain)
                    and (not area or (d['area'] or '').casefold()==area.casefold())]
                items=current['devices']
                current['areas']=sorted({d['area'] for d in items if d['area']})
                current['counts']={'total':len(items),'available':sum(d['available'] for d in items),
                    'unavailable':sum(not d['available'] for d in items),'without_area':sum(d['area'] is None for d in items)}
                return current
            except HomeUnavailable as error: raise HTTPException(503,str(error)) from None

        @app.get('/internal/home/state', dependencies=[Depends(authorize_home_tools)])
        def agent_home_state(entity_id: str):
            devices=agent_home_devices()['devices']
            item=next((d for d in devices if d['entity_id']==entity_id),None)
            if item is None: raise HTTPException(404,'Home device unavailable')
            return item

        @app.post('/internal/home/action', dependencies=[Depends(authorize_home_tools)])
        def agent_home_action(command: ActionRequest):
            return actions.execute(command)

    @app.post("/v1/home/{device}/actions", dependencies=[Depends(authorize)])
    def home_action(device: str, request: HomeAction,connection:Request,session=Depends(authorize)):
        if deployment_mode == 'validation': raise HTTPException(409,'Device actions are off in this validation instance')
        if session=='round':return mini_control(connection,lambda:round_home.action(device,request.action,request.value,request.unit),lambda:home.act(device,request.action,request.value,request.unit))
        try:
            return home.act(device, request.action, request.value, request.unit)
        except HomeUnavailable as error:
            raise HTTPException(503, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/v1/state")
    def state(request:Request,session=Depends(authorize)):
        result={"timers": assistant.timer_states()+schedules.timer_states(), "capabilities": ["clock", "timer", "schedules"]}
        if displays.profile_for(session)['profile']['mode']=='guest':
            result['timers']=[t for t in result['timers'] if t['destination']==session]
        if session in {'device','round'}:
            for timer in result['timers']:
                if timer['destination']!='round': timer['notified']=True
        if session in {'device','round'} and displays.profile_for(session)['profile']['mode']!='guest' and request.headers.get('x-echo-audio-receiver')=='round':
            try:result['audio_inbox']=announcements.inbox('round','round')
            except AnnouncementUnavailable:result['audio_inbox']={'enabled':False,'ready':False,'status':'unavailable','items':[],'active':[]}
        return result

    def research_reply(text,session):
        import re
        query=text.strip().lower().rstrip('.!?')
        if query in {'what did you find','research status','stop research','cancel research'}:
            jobs=research.list(session)
            if jobs:
                latest=jobs[0]
                if query in {'stop research','cancel research'}:
                    research.stop(session,latest['id']);answer='I’ve requested a stop for that research.'
                elif latest['active']:answer='I’m still researching. You can follow progress on Tasks.'
                else:answer=(latest.get('result') or {}).get('text','That research was stopped.')[:900]
                return {'status':'complete','capability':'research','text':answer}
        if re.match(r'\s*(?:please\s+)?(?:research\b|look into\b|compare\b)',text,re.I):
            task=research.start(session,text)
            return {'status':'complete','capability':'research','text':'I’ll look into that. The report and sources will appear on the Tasks page.','task_id':task['id']}
        return None

    @app.post("/v1/text")
    async def text(request: TextRequest, connection: Request, session=Depends(authorize)):
        if session=='round':
            with round_profile.lock:
                authorize(connection)
                if round_profile.snapshot()['profile']['mode']=='household':
                    research_result=research_reply(request.text,'device')
                    if research_result is not None:return research_result
                try:activity=conversations.begin(session)
                except ConversationBusy as error:raise HTTPException(409,str(error)) from None
                before=round_profile.snapshot()
            result=await run_conversation(connection,app.state.speech_stop,
                partial(profiled_echo.respond,allow_home_actions=deployment_mode=='device',progress=activity.progress,calendar_review=request.calendar_review),
                request.text,session,request.lookup,activity=activity)
            authorize(connection)
            if round_profile.snapshot()!=before:raise HTTPException(409,'Mini access changed during the reply')
            return result
        try:
            research_result=research_reply(request.text,session)
            if research_result is not None:return research_result
            if routine_request(request.text) or household_request(request.text) or briefing_request(request.text) or draft_request(request.text):
                return await run_conversation(connection,app.state.speech_stop,
                    partial(echo.respond,allow_home_actions=deployment_mode=='device',calendar_review=request.calendar_review),request.text,session,request.lookup)
            if deployment_mode == 'validation' or memory_request(request.text) or request.lookup or lookup_request(request.text):
                return await run_conversation(connection,app.state.speech_stop,echo.respond,request.text,session,request.lookup)
            # Home/timer actions already accepted cannot be undone by disconnect.
            context_token, previous = echo.context(session)
            timer_context = previous[-1].get('local_result') if previous else None
            response = await run_in_threadpool(home.answer, request.text)
            if response is None:
                response = await run_in_threadpool(assistant.respond, request.text, timer_context=timer_context, destination=destination_for(session))
            if response['capability'] == 'conversation':
                return await run_conversation(connection, app.state.speech_stop,
                    partial(echo.respond,allow_home_actions=True), request.text, session,request.lookup)
            echo.record_local(request.text, response, session, context_token)
            return response
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.post('/v1/chat')
    async def chat(request: TextRequest, connection: Request, session=Depends(authorize)):
        # Browser actions require an explicit opt-in on this message, plus device grants.
        try: activity = conversations.begin(session)
        except ConversationBusy as error: raise HTTPException(409,str(error)) from None
        before=displays.profile_for(session)
        result=await run_conversation(connection, app.state.speech_stop,
            partial(profiled_echo.respond,allow_home_actions=request.allow_home_actions,progress=activity.progress,calendar_review=request.calendar_review),
            request.text, session,request.lookup,activity=activity)
        authorize(connection)
        if displays.profile_for(session)!=before:raise HTTPException(409,'Display access changed during the reply')
        return result

    class RoutineSave(BaseModel):
        model_config=ConfigDict(extra='forbid')
        name: str=Field(min_length=1,max_length=60)
        steps: list[RoutineStep]=Field(min_length=1,max_length=12)

    class RoutineRevision(BaseModel):
        model_config=ConfigDict(extra='forbid')
        revision: str=Field(pattern=r'^[a-f0-9]{64}$')

    class RoutineEdit(RoutineSave,RoutineRevision): pass

    @app.exception_handler(RoutineUnavailable)
    async def routine_unavailable(request,error):
        return JSONResponse(status_code=503,content={'detail':str(error)})

    @app.exception_handler(RoutineConflict)
    async def routine_conflict(request,error):
        return JSONResponse(status_code=409,content={'detail':str(error)})

    @app.get('/v1/routines',dependencies=[Depends(authorize)])
    def routine_list(): return {'items':routines.store.snapshot(),'limit':32}

    def save_routine(body,identifier=None):
        try: return {'item':routines.save(body.name,[s.model_dump() for s in body.steps],identifier,getattr(body,'revision',None))}
        except RoutineConflict: raise
        except KeyError: raise HTTPException(404,'Routine not found') from None
        except (ValueError,HomeUnavailable,HomeAccessUnavailable) as error: raise HTTPException(422,str(error)) from None

    @app.post('/v1/routines',dependencies=[Depends(authorize)])
    def create_routine(body:RoutineSave): return save_routine(body)

    @app.put('/v1/routines/{identifier}',dependencies=[Depends(authorize)])
    def update_routine(identifier:str,body:RoutineEdit): return save_routine(body,identifier)

    @app.delete('/v1/routines/{identifier}',dependencies=[Depends(authorize)])
    def delete_routine(identifier:str,body:RoutineRevision):
        try: routines.store.delete(identifier,body.revision)
        except KeyError: raise HTTPException(404,'Routine not found') from None
        return {'deleted':True}

    @app.post('/v1/routines/{identifier}/run')
    async def run_routine(identifier:str,body:RoutineRevision,connection:Request,session=Depends(authorize)):
        try:
            routines.store.get(identifier,body.revision)
            activity=conversations.begin(session)
        except KeyError: raise HTTPException(404,'Routine not found') from None
        except ConversationBusy as error: raise HTTPException(409,str(error)) from None
        return await run_conversation(connection,app.state.speech_stop,
            partial(routines.run,progress=activity.progress),identifier,body.revision,activity=activity)

    @app.get('/v1/chat/activity')
    def chat_activity(session=Depends(authorize)):
        return conversations.snapshot(session)

    class ResearchRequest(BaseModel):
        model_config=ConfigDict(extra='forbid')
        prompt: str=Field(min_length=3,max_length=2400)

    @app.get('/v1/tasks')
    def list_tasks(session=Depends(authorize)): return {'items':research.list(session)}

    @app.post('/v1/tasks',status_code=202)
    def start_task(body:ResearchRequest,session=Depends(authorize)):
        try:return research.start(session,body.prompt)
        except ValueError as error:raise HTTPException(409,str(error)) from None

    @app.post('/v1/tasks/{identifier}/stop')
    def stop_task(identifier:str,session=Depends(authorize)):
        try:return research.stop(session,identifier)
        except KeyError:raise HTTPException(404,'Task not found') from None

    @app.delete('/v1/tasks/{identifier}')
    def delete_task(identifier:str,session=Depends(authorize)):
        try:research.delete(session,identifier)
        except KeyError:raise HTTPException(404,'Task not found') from None
        except ValueError as error:raise HTTPException(409,str(error)) from None
        return {'deleted':True}

    @app.post('/v1/chat/activity/{identifier}/stop')
    def stop_chat(identifier: str, session=Depends(authorize)):
        try: return conversations.stop(session,identifier)
        except KeyError: raise HTTPException(404,'Conversation not found') from None

    @app.get('/memory')
    def memory_page():return FileResponse(web/'index.html')

    @app.exception_handler(MemoryUnavailable)
    async def memory_error(request,error):
        return JSONResponse(status_code=503,content={'detail':str(error)})

    @app.get('/v1/memory',dependencies=[Depends(authorize)])
    def memories():
        return {'items':memory.snapshot(),'enabled':store.snapshot()[0].memory_enabled,'limit':200}

    @app.post('/v1/memory',dependencies=[Depends(authorize)])
    def add_memory(request:MemoryRequest):
        try:item=memory.save(request.text)
        except ValueError as error:raise HTTPException(422,str(error)) from None
        echo.clear();return {'item':item}

    @app.put('/v1/memory/{identifier}',dependencies=[Depends(authorize)])
    def edit_memory(identifier:str,request:MemoryRequest):
        try:item=memory.save(request.text,identifier)
        except KeyError:raise HTTPException(404,'Memory was not found') from None
        except ValueError as error:raise HTTPException(422,str(error)) from None
        echo.clear();return {'item':item}

    @app.delete('/v1/memory/{identifier}',dependencies=[Depends(authorize)])
    def remove_memory(identifier:str):
        try:memory.delete(identifier)
        except KeyError:raise HTTPException(404,'Memory was not found') from None
        echo.clear();return {'status':'deleted'}

    @app.delete('/v1/memory',dependencies=[Depends(authorize)])
    def clear_memories():
        memory.clear();echo.clear();return {'status':'cleared'}

    @app.get('/v1/chat')
    def chat_history(session=Depends(authorize)):
        return {'messages': echo.messages(session)}

    @app.delete('/v1/chat')
    def clear_chat(session=Depends(authorize)):
        conversations.clear(session)
        echo.clear(session)
        return {'cleared': True}

    @app.get('/v1/echo', dependencies=[Depends(authorize)])
    def echo_status(): return echo.status()

    @app.get('/v1/settings', dependencies=[Depends(authorize)])
    def settings(): return store.public()

    @app.get('/v1/settings/agent', dependencies=[Depends(authorize)])
    def agent_settings_state():
        try: return agent_apply.status()
        except (OSError, ValueError): raise HTTPException(503, 'Agent settings status is unavailable') from None

    @app.post('/v1/settings/apply-agent', dependencies=[Depends(authorize)])
    def apply_agent_settings():
        if not echo.lock.acquire(blocking=False):
            raise HTTPException(409, 'Wait for Echo to finish its current reply before applying')
        try: return agent_apply.start()
        except (OSError, ValueError, RuntimeUnavailable) as error: raise HTTPException(409, str(error)) from None
        finally: echo.lock.release()

    @app.delete('/v1/settings/apply-agent', dependencies=[Depends(authorize)])
    def cancel_agent_settings():
        try: return agent_apply.cancel()
        except (OSError, ValueError) as error: raise HTTPException(409, str(error)) from None

    @app.put('/v1/settings', dependencies=[Depends(authorize)])
    def save_settings(request: SettingsUpdate):
        if request.settings.stt_engine == 'whisper' and not whisper_available(runtime_root):
            raise HTTPException(422, 'The local Whisper runtime and model must be installed first')
        try:
            validate_selection(request.settings,runtime_root,speech_voices())
            return store.save(request)
        except ValueError as error: raise HTTPException(422, str(error)) from None

    @app.get('/v1/settings/speech', dependencies=[Depends(authorize)])
    def speech_options():
        voice = voice_status(runtime_root) if runtime_root else {}
        voices = speech_voices()
        return {'voices': voices, 'engines':tts_catalog(runtime_root,voices), 'stt': [
            {'id': 'vosk', 'name': 'Vosk · low latency', 'available': True},
            {'id': 'whisper', 'name': 'Whisper base.en · CPU', 'available': whisper_available(runtime_root)}],
            'active_stt': voice.get('engine', 'disconnected'), 'tts': selected_status(store.snapshot()[0],runtime_root), 'apply_status': speech_restart.state}

    class VoiceCheck(BaseModel):
        model_config = ConfigDict(extra='forbid')
        tts_engine: Literal['sapi','kokoro','pocket']
        tts_voice: str = Field(default='',max_length=160)
        tts_rate: int = Field(default=0,strict=True,ge=-5,le=5)

    @app.post('/v1/settings/check-voice', dependencies=[Depends(authorize)])
    def check_voice(request: VoiceCheck):
        settings = EchoSettings(**request.model_dump())
        try: validate_selection(settings,runtime_root,speech_voices())
        except ValueError as error: raise HTTPException(422,str(error)) from None
        if not voice_check_lock.acquire(blocking=False): raise HTTPException(409,'A silent voice check is already running')
        try:
            pcm, metrics = synthesize_checked('Hello. I am Echo. Your timer is set for five minutes.',settings=settings,cancel=app.state.speech_stop)
            del pcm
            return {'status':'complete','playback':False,**metrics}
        except (RuntimeError,OSError,TimeoutError,ValueError):
            raise HTTPException(503,'Local voice check failed. Verify the speech runtime and model files.') from None
        finally: voice_check_lock.release()

    @app.post('/v1/settings/apply-speech', dependencies=[Depends(authorize)])
    def apply_speech():
        try: return speech_restart.start()
        except ValueError as error: raise HTTPException(409, str(error)) from None

    @app.get('/v1/settings/speaker-check', dependencies=[Depends(authorize)])
    def speaker_check_state():
        try:return speaker_check.state()
        except (ValueError,OSError) as error:raise HTTPException(409,'Speaker check status is unavailable') from None

    @app.post('/v1/settings/speaker-check', dependencies=[Depends(authorize)])
    def start_speaker_check():
        if deployment_mode=='validation':raise HTTPException(409,'Speaker playback is disabled on the validation host')
        try:return speaker_check.request()
        except ValueError as error:raise HTTPException(409,str(error)) from None
        except OSError:raise HTTPException(503,'Speaker check could not be queued') from None

    @app.delete('/v1/settings/speaker-check/{identifier}', dependencies=[Depends(authorize)])
    def stop_speaker_check(identifier:str):
        try:return speaker_check.cancel(identifier)
        except (ValueError,OSError):raise HTTPException(409,'Speaker check could not be cancelled; check its status') from None

    @app.post('/v1/settings/models', dependencies=[Depends(authorize)])
    async def models(connection: Request):
        settings, keys, _ = store.snapshot()
        try: return {'models': await run_conversation(connection, app.state.speech_stop, echo.provider.models, settings, keys)}
        except ProviderUnavailable as error: raise HTTPException(503, str(error)) from None

    @app.post('/v1/settings/test', dependencies=[Depends(authorize)])
    async def test_provider(connection: Request):
        settings, keys, _ = store.snapshot()
        try:
            if settings.agent_runtime == 'hermes':
                await run_in_threadpool(access.ensure_applied)
                answer = await run_conversation(connection, app.state.speech_stop,
                    partial(echo.runtime.complete, instructions=settings.personality),
                    settings, keys, [{'role':'user','content':'Say hello in one brief sentence.'}])
            else:
                answer = await run_conversation(connection, app.state.speech_stop, echo.provider.complete,
                    settings, keys, [{'role': 'user', 'content': 'Say hello in one brief sentence.'}])
            return {'status': 'complete', 'text': answer}
        except (ProviderUnavailable, RuntimeUnavailable) as error: raise HTTPException(503, str(error)) from None
        except (KeyError, TypeError, AttributeError, IndexError): raise HTTPException(503, 'Unsupported provider response') from None

    @app.post("/v1/timers", dependencies=[Depends(authorize)])
    def timer(request: TimerRequest,session=Depends(authorize)):
        try:
            return {"id": assistant.start_timer(request.seconds, request.label, destination=destination_for(session))}
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.delete("/v1/timers/{timer_id}", dependencies=[Depends(authorize)])
    def dismiss(timer_id: str,session=Depends(authorize)):
        if displays.profile_for(session)['profile']['mode']=='guest':
            items=assistant.timer_states()+schedules.timer_states()
            if not any(t['id']==timer_id and t['destination']==session for t in items):raise HTTPException(404,'Timer not found')
        if not assistant.dismiss_timer(timer_id) and not schedules.event_action(timer_id,'dismiss'):
            raise HTTPException(404, "Timer not found")
        return {"dismissed": True}

    @app.post("/v1/timers/{timer_id}/ack", dependencies=[Depends(authorize)])
    def acknowledge(timer_id: str,session=Depends(authorize)):
        if not assistant.acknowledge_timer(timer_id,destination=destination_for(session)) and not schedules.event_action(timer_id,'ack',destination=destination_for(session)):
            raise HTTPException(404, 'Finished timer not found')
        return {'acknowledged': True}

    return app

def main():
    import argparse
    from threading import Thread
    import uvicorn
    from .lifecycle import Lifecycle, request_stop
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description='Round Voice loopback service')
    parser.add_argument('--stop', action='store_true', help='Request graceful shutdown of this checkout\'s API')
    args = parser.parse_args()
    if args.stop:
        print('Stop requested' if request_stop(root, 'api') else 'No running API record', flush=True)
        return
    token_path = root / "local" / "api-token"
    token_path.parent.mkdir(exist_ok=True)
    token = os.environ.get("ROUND_VOICE_TOKEN")
    if not token:
        try:
            with token_path.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        token = token_path.read_text(encoding="utf-8").strip()
    home = HomeBridge(HomeConfig.load(root))
    with Lifecycle(root, 'api') as lifecycle:
        tool_path=os.environ.get('ECHO_HOME_TOOLS_TOKEN_FILE')
        tool_token=Path(tool_path).read_text().strip() if tool_path else None
        app = create_app(token,home,root,deployment_mode=os.environ.get('ECHO_DEPLOYMENT_MODE','device'),home_tools_token=tool_token)
        bind='0.0.0.0' if os.environ.get('ECHO_CONTAINER')=='1' else '127.0.0.1'
        server = uvicorn.Server(uvicorn.Config(app, host=bind, port=8768, access_log=False))
        def stop_when_requested():
            while not lifecycle.stopped() and not server.should_exit:
                lifecycle.wait(.2)
            app.state.speech_stop.set()
            server.should_exit = True
        monitor = Thread(target=stop_when_requested, name='api-stop', daemon=True)
        monitor.start()
        try: server.run()
        finally:
            server.should_exit = True
            monitor.join(timeout=1)

if __name__ == "__main__":
    main()
