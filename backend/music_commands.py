"""One bounded, generation-bound music command between the API and voice owner."""
import json
from .lifecycle import _acquire_lock,_release_lock
from .voice_status import voice_status

ACTIONS={'play','pause','toggle','next','previous'}


def request(root,action):
    if root is None or action not in ACTIONS:raise ValueError('Unsupported music command')
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
    owner=json.loads((root/'local/voice-process.json').read_text())
    identity=owner.get('run_id')
    if not isinstance(identity,str) or len(identity)!=32:raise ValueError('The speaker is not ready')
    path=root/'local/music-command.json';temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'run_id':identity,'action':action}));temporary.replace(path)
    return {'status':'queued','action':action}


def take(root,identity):
    path=root/'local/music-command.json'
    processing=path.with_suffix('.processing')
    try:
        path.replace(processing)
        data=processing.read_bytes();processing.unlink(missing_ok=True)
        if len(data)>1024:return None
        value=json.loads(data)
        if value.get('run_id')==identity and value.get('action') in ACTIONS:return value['action']
    except (OSError,ValueError,TypeError,AttributeError):pass
    return None
