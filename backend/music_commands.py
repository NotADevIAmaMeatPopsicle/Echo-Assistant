"""One bounded, generation-bound music command between the API and voice owner."""
import json
from .lifecycle import _acquire_lock,_release_lock
from .voice_status import voice_status

ACTIONS={'play','pause','toggle','next','previous'}


def wire_command(action,value=None):
    if action in ACTIONS and value is None:return action
    if action=='seek' and type(value) is int and 0<=value<=86400000:return f'seek {value}'
    if action=='volume' and type(value) is int and 0<=value<=100:return f'volume {value}'
    if action=='shuffle' and type(value) is bool:return 'shuffle '+str(value).lower()
    if action=='repeat' and type(value) is str and value in {'off','context','track'}:return 'repeat '+value
    raise ValueError('Unsupported music command or value')


def request(root,action,value=None):
    wire_command(action,value)
    if root is None:raise ValueError('The speaker is not connected')
    lock=_acquire_lock(root/'local','voice')
    if lock is not None:
        _release_lock(lock);raise ValueError('The speaker is not connected')
    status=voice_status(root)
    phases={'armed','muted','cooldown','music'}
    if action=='pause': phases |= {'activation','listening','thinking','speaking','alarm'}
    if status.get('status') not in phases:
        raise ValueError('Wait until Echo is ready before changing playback')
    if status.get('music',{}).get('status') not in {'connected','playing','paused','stopped'}:
        raise ValueError('Connect Spotify to this speaker first')
    if action not in ACTIONS:
        from .music_now_playing import snapshot
        current=snapshot(root)
        if action not in current.get('capabilities',[]) or current['status'] not in {'playing','paused'}:
            raise ValueError('This control is unavailable until Spotify is playing on Echo')
        if action=='seek' and value>current.get('duration_ms',0):raise ValueError('Position is past the end of this track')
    owner=json.loads((root/'local/voice-process.json').read_text())
    identity=owner.get('run_id')
    if not isinstance(identity,str) or len(identity)!=32:raise ValueError('The speaker is not ready')
    path=root/'local/music-command.json';temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'run_id':identity,'action':action,'value':value}));temporary.replace(path)
    return {'status':'queued','action':action}


def take(root,identity):
    path=root/'local/music-command.json'
    processing=path.with_suffix('.processing')
    try:
        path.replace(processing)
        data=processing.read_bytes();processing.unlink(missing_ok=True)
        if len(data)>1024:return None
        value=json.loads(data)
        if value.get('run_id')==identity:return wire_command(value.get('action'),value.get('value'))
    except (OSError,ValueError,TypeError,AttributeError):pass
    return None
