"""Echo's bounded home tools. The model has no arbitrary HTTP/service tool."""
import json
from pathlib import Path
from typing import Literal
import sys
import httpx
sys.path.insert(0, '/opt/echo')
from mcp.server import MCPServer
from backend.home import HomeConfig, HomeBridge, HomeUnavailable
from backend.home_catalog import HomeCatalog
from backend.home_policy import validate_policy, apply_policy

api_path = Path('/opt/data/echo-home-api.json')
api = json.loads(api_path.read_text()) if api_path.exists() else None
if api:
    if api.get('url') != 'http://api:8768' or not isinstance(api.get('token'),str) or len(api['token'])<32:
        raise ValueError('Invalid internal home service')
    catalog = None
else:
    config = HomeConfig(**json.loads(Path('/opt/data/echo-home.json').read_text()))
    catalog = HomeCatalog(HomeBridge(config))
server = MCPServer('echo-home', instructions='Read real home states. Actions require an active request and explicit device Control access.',
                   log_level='ERROR')

def permitted_snapshot():
    # Re-read on every invocation so a live process cannot retain revoked access.
    snapshot = catalog.snapshot()
    policy = validate_policy(json.loads(Path('/opt/data/echo-access.json').read_text()))
    return apply_policy(snapshot, policy)


def api_read(path, params):
    with httpx.Client(base_url=api['url'],headers={'Authorization':'Bearer '+api['token']},
                      trust_env=False,follow_redirects=False,timeout=10) as client:
        response=client.get(path,params=params)
        response.raise_for_status()
        if len(response.content)>1_000_000:raise ValueError('Home inventory too large')
        return response.json()

@server.tool()
def home_devices(domain: str = '', area: str = '') -> dict:
    """List real home devices and rooms. Use counts.available for reachable devices; counts.total includes unavailable ones. Null area means unassigned/unknown."""
    try:
        if api:return api_read('/internal/home/devices',{'domain':domain,'area':area})
        result = permitted_snapshot()
        result['devices'] = [d for d in result['devices'] if (not domain or d['domain'] == domain)
                             and (not area or (d['area'] or '').casefold() == area.casefold())]
        items = result['devices']
        result['areas'] = sorted({d['area'] for d in items if d['area']})
        result['counts'] = {'total':len(items), 'available':sum(d['available'] for d in items),
                            'unavailable':sum(not d['available'] for d in items),
                            'without_area':sum(d['area'] is None for d in items)}
        return result
    except (HomeUnavailable, ValueError, OSError, TypeError, KeyError, httpx.HTTPError):
        return {'status':'unavailable','error':'Home inventory unavailable'}

@server.tool()
def home_state(entity_id: str) -> dict:
    """Read current state and capabilities of a device returned by home_devices."""
    try:
        if api:return api_read('/internal/home/state',{'entity_id':entity_id})
        return next(d for d in permitted_snapshot()['devices'] if d['entity_id'] == entity_id)
    except (HomeUnavailable, ValueError, OSError, TypeError, KeyError, StopIteration, httpx.HTTPError):
        return {'status':'unavailable','error':'Home device unavailable'}

@server.tool()
def home_action(request_id: str, entity_id: str,
                action: Literal['turn_on','turn_off','brightness','color_temperature','temperature','mode',
                                'play','pause','stop','volume','mute','next','previous','activate'],
                value: float | int | bool | str | None = None, unit: Literal['°C','°F'] | None = None) -> dict:
    """Act only on a user-requested, Control-enabled entity from home_devices.

    request_id must be the active ID supplied for this message. Light/switch:
    turn_on/turn_off; light brightness (0-100 percent), color_temperature (Kelvin,
    reported limits). Climate: temperature (reported limits and explicit °C/°F),
    mode (reported hvac_modes). Player: play/pause/stop/next/previous/turn_on/turn_off,
    volume (0-100 percent), mute (boolean), only reported capabilities. Scene: activate.
    unit is only for climate temperature; omit it for light color_temperature,
    whose numeric value is already Kelvin. Omit value for simple on/off/play actions.
    complete means observed; accepted is not verified.
    denied/unavailable/unconfirmed are not success. Never blindly retry a write.
    """
    if not api:return {'status':'denied','error':'Home actions require the Echo API'}
    try:
        command={'request_id':request_id,'entity_id':entity_id,'action':action,'value':value,'unit':unit}
        with httpx.Client(base_url=api['url'],headers={'Authorization':'Bearer '+api['token']},
                          trust_env=False,follow_redirects=False,timeout=20) as client:
            response=client.post('/internal/home/action',json=command)
            if response.status_code==422:return {'status':'denied','error':'Invalid home action arguments'}
            response.raise_for_status()
            if len(response.content)>1_000_000:raise ValueError('Home result too large')
            return response.json()
    except (ValueError,TypeError):return {'status':'denied','error':'Invalid home action arguments'}
    except httpx.HTTPError:
        return {'status':'unconfirmed','error':'Home action response unavailable; do not assume success or retry blindly'}

if __name__ == '__main__': server.run(transport='stdio')
