"""Single-request Home Assistant calendar transport; no automatic write retries."""
import json
from .home import HomeUnavailable


def calendar_command(config, command):
    if not config.enabled:raise HomeUnavailable('Home integration is not configured')
    if command.get('type') not in {'calendar/event/create','calendar/event/update','calendar/event/delete'}:
        raise ValueError('Unsupported calendar operation')
    try:
        from websockets.sync.client import connect
        origin=config.base_url.replace('http://','ws://').replace('https://','wss://')
        # HomeConfig validates a private IP origin. Disable proxy discovery and
        # redirects; credentials are sent only after the local HA handshake.
        with connect(origin+'/api/websocket',proxy=None,open_timeout=4,close_timeout=1,max_size=1_000_000) as ws:
            if json.loads(ws.recv(timeout=5)).get('type')!='auth_required':raise ValueError()
            ws.send(json.dumps({'type':'auth','access_token':config.token}))
            if json.loads(ws.recv(timeout=5)).get('type')!='auth_ok':raise ValueError()
            ws.send(json.dumps({**command,'id':1}))
            result=json.loads(ws.recv(timeout=12))
            if result.get('type')!='result' or result.get('id')!=1 or type(result.get('success')) is not bool:raise ValueError()
            return 'accepted' if result['success'] else 'rejected'
    except Exception:
        # HA errors can contain private data. A lost response may follow a
        # successful write, so the caller retains its durable dispatch receipt.
        raise HomeUnavailable('The calendar connection failed or its reply was invalid') from None
