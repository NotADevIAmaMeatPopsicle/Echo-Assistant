"""Read-only check of Hermes' actual MCP functions against the validation API."""
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import deployment
from tools.remote_device import client
from tools.start_remote_api import connection

RUNNER=r'''
import json,runpy,sys
from pathlib import Path
config=json.load(sys.stdin)
path=Path('/opt/data/echo-home-api.json')
path.write_text(json.dumps(config));path.chmod(0o600)
module=runpy.run_path('/opt/echo/home_tools.py')
devices=module['home_devices']()
assert isinstance(devices.get('devices'),list), 'Home inventory unavailable'
available=[d for d in devices['devices'] if d['available']]
assert available, 'No reachable device for the state check'
state=module['home_state'](available[0]['entity_id'])
assert state.get('entity_id')==available[0]['entity_id'], 'Device state did not match'
module['home_devices'].__globals__['api']['token']='invalid-test-token'
assert module['home_devices']()['status']=='unavailable', 'Invalid token was not rejected'
print(json.dumps({'home_api_proxy':True,'counts':devices['counts'],'state_read':True,'invalid_token_rejected':True,'actuation':False}))
'''

def main():
    with client() as api:
        response=api.get('/health');response.raise_for_status()
        if response.json().get('deployment_mode')!='validation':
            raise RuntimeError('Run this check before the physical host transfer')
    result=subprocess.run(['docker','--context',deployment.docker_context(),'run','--rm','-i',
        '--user','10000:10000','--network','echo_default','--log-driver','none',
        '--tmpfs','/opt/data:rw,nosuid,nodev,size=16777216,uid=10000,gid=10000,mode=0700',
        '--entrypoint','/opt/hermes/.venv/bin/python','echo-hermes:trial-0.1','-c',RUNNER],
        input=json.dumps({'url':'http://api:8768','token':connection()['home_tools_token']}).encode())
    return result.returncode

if __name__=='__main__':sys.exit(main())
