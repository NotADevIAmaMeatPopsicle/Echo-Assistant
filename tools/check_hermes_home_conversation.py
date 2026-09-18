"""Exercise the real Azure/Hermes loop against synthetic lights, without HA credentials.

Runs a disposable unpublished container. Only the currently selected Azure key
is copied through encrypted Docker stdin; all runtime files/logs remain tmpfs.
No board, speaker, Home Assistant token or persistent data volume is attached.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
DOCKER=['docker','--context',deployment.docker_context()]
RUNNER=r'''
import base64,copy,hmac,json,os,secrets,subprocess,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
payload=json.load(sys.stdin)
eager_tools=payload.pop('eager_tools',False)
root=Path('/opt/data/check');(root/'backend').mkdir(parents=True)
(root/'home_tools.py').write_text(payload.pop('home_tools'))
for name,source in payload.pop('backend').items():
    assert name.endswith('.py') and '/' not in name and '\\' not in name
    (root/'backend'/name).write_text(source)
sys.path.insert(0,str(root))
from backend import deployment
os.environ['ECHO_CONTAINER']='1'
os.environ['ECHO_STORAGE_KEY_FILE']='/run/echo/storage.key'
key=Path('/run/echo/storage.key');key.write_bytes(os.urandom(32));key.chmod(0o600)
from backend.agent import EchoAgent
from backend.agent_runtime import configuration_fingerprint
from backend.settings import EchoSettings,SettingsStore,SettingsUpdate
from backend.home_actions import HomeActions,ActionRequest
from backend.home_access import HomeAccessStore
from backend.home_catalog import HomeCatalog
from backend.home_policy import apply_policy

settings=EchoSettings(**payload['settings'])
assert settings.provider=='azure' and settings.agent_runtime=='hermes'
provider_key=payload['key'];del payload
gateway_token=secrets.token_urlsafe(40);tool_token=secrets.token_urlsafe(40)
fingerprint=configuration_fingerprint(settings,{'azure':provider_key})
store=SettingsStore(root);store.save(SettingsUpdate(settings=settings,api_key=provider_key))
access=HomeAccessStore(root,synchronizer=lambda _:None)
policy={'default_access':'hidden','devices':{entity:{'access':'control','room':'Study'}
    for entity in ('light.study_left','light.study_right')}}
access.update(policy,access.snapshot()['revision'])
connection={'url':'http://agent:8642','token':gateway_token,'configuration':fingerprint}
(root/'local/remote-agent.json').write_text(json.dumps({'protected':base64.b64encode(store.protector.encrypt(json.dumps(connection).encode())).decode()}))

class Home:
    def __init__(self):
        self.states={entity:{'entity_id':entity,'state':'on','attributes':{'friendly_name':entity.split('.')[1],
            'supported_color_modes':['color_temp'],'brightness':255,'color_temp_kelvin':4000,
            'min_color_temp_kelvin':2200,'max_color_temp_kelvin':6500}}
            for entity in policy['devices']}
        self.writes=[];self.cancel=None
    def _request(self,method,path,body=None):
        if method=='GET':
            if path=='/api/states':return copy.deepcopy(list(self.states.values()))
            assert path.startswith('/api/states/')
            return copy.deepcopy(self.states[path.removeprefix('/api/states/')])
        assert method=='POST' and path in ('/api/services/light/turn_on','/api/services/light/turn_off')
        assert body['entity_id'] in self.states
        assert set(body)<={'entity_id','brightness_pct','color_temp_kelvin'}
        self.writes.append(copy.deepcopy(body))
        state=self.states[body['entity_id']]
        state['state']='off' if path.endswith('/turn_off') else 'on'
        if 'brightness_pct' in body:state['attributes']['brightness']=round(body['brightness_pct']*255/100)
        if 'color_temp_kelvin' in body:state['attributes']['color_temp_kelvin']=body['color_temp_kelvin']
        if self.cancel:self.cancel.set()
        return []
home=Home();catalog=HomeCatalog(home,registry=lambda:([],[],[]))
actions=HomeActions(home,access)
agent=EchoAgent(store);agent.home_access=access;agent.home_actions=actions
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,data):
        body=json.dumps(data).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
    def authorized(self):
        return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+tool_token)
    def do_GET(self):
        from urllib.parse import urlparse,parse_qs
        if not self.authorized():return self.send(401,{})
        route=urlparse(self.path);query=parse_qs(route.query)
        snapshot=apply_policy(catalog.snapshot(),access.snapshot()['policy'])
        if route.path=='/internal/home/devices':
            snapshot['devices']=[x for x in snapshot['devices'] if
                (not query.get('domain') or x['domain']==query['domain'][0]) and
                (not query.get('area') or (x['area'] or '').casefold()==query['area'][0].casefold())]
            return self.send(200,snapshot)
        if route.path=='/internal/home/state':
            value=next((x for x in snapshot['devices'] if x['entity_id']==query.get('entity_id',[''])[0]),None)
            return self.send(200 if value else 404,value or {})
        self.send(404,{})
    def do_POST(self):
        if not self.authorized():return self.send(401,{})
        if self.path!='/internal/home/action':return self.send(404,{})
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<4096:return self.send(422,{})
        try:command=ActionRequest.model_validate_json(self.rfile.read(length))
        except ValueError:return self.send(422,{})
        return self.send(200,actions.execute(command))
server=ThreadingHTTPServer(('0.0.0.0',8768),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
envelope={'secrets':{'AZURE_FOUNDRY_API_KEY':provider_key,'API_SERVER_KEY':gateway_token},
    'configuration':fingerprint,'personality':settings.personality,'home_access':policy,
    'home_api':{'url':'http://api:8768','token':tool_token},'config':{
        'model':{'provider':'azure-foundry','default':settings.model,'base_url':settings.azure_url,'api_mode':'codex_responses'},
        'agent':{'max_turns':12,'gateway_timeout':60},'platform_toolsets':{'api_server':[]},
        'tools':{'tool_search':{'enabled':'off' if eager_tools else 'auto'}},
        'mcp_servers':{'echo-home':{'command':'/opt/hermes/.venv/bin/python','args':[str(root/'home_tools.py')]}},
        'memory':{'memory_enabled':False,'user_profile_enabled':False,'nudge_interval':0},
        'skills':{'creation_nudge_interval':0},'auxiliary':{'background_review':{'enabled':False}},
        'updates':{'check':False},'telemetry':{'shared_metrics':{'enabled':False,'send':False}},
        'terminal':{'cwd':'/opt/data/workspace'}}}
Path('/opt/data/.echo-bootstrap.json').write_text(json.dumps(envelope));del envelope,provider_key
process=subprocess.Popen(['/opt/hermes/.venv/bin/python','/opt/echo/bootstrap.py'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def require(condition,message):
    if not condition:raise RuntimeError(message)
try:
    import httpx
    deadline=time.monotonic()+60
    with httpx.Client(trust_env=False,timeout=2) as client:
        while True:
            try:
                if client.get('http://127.0.0.1:8642/health').json().get('status')=='ok':break
            except (httpx.HTTPError,ValueError):pass
            require(process.poll() is None and time.monotonic()<deadline,'Disposable gateway did not become ready')
            time.sleep(.5)
    print(json.dumps({'phase':'ready','home':'synthetic','model':settings.model,'eager_tools':eager_tools}),flush=True)
    results=[]
    for text,field,expected in [('Dim the study lights to 30 percent.','brightness',76),
                               ('Make them warmer, 2700 kelvin.','color_temp_kelvin',2700)]:
        began=time.monotonic();event_start=time.time();reply=agent.respond(text,'test',allow_home_actions=True)
        if reply['status']!='complete':
            activity=agent.runtime.activity()
            detail={}
            try:
                with httpx.Client(trust_env=False,timeout=3,headers={'Authorization':'Bearer '+gateway_token}) as diagnostics:
                    terminal=diagnostics.get('http://127.0.0.1:8642/v1/runs/'+activity['task_id']).json()
                    detail={k:terminal.get(k) for k in ('status','error','error_type','partial','interrupted')}
            except (httpx.HTTPError,KeyError,ValueError):pass
            rendered=json.dumps({'phase':'failed','reason':reply['text'],'activity':activity,
                'receipts':reply.get('home_actions',[]),'synthetic_writes':home.writes,'terminal':detail})
            for secret in (store.snapshot()[1]['azure'],gateway_token,tool_token):rendered=rendered.replace(secret,'[redacted]')
            print(rendered,flush=True)
        require(reply['status']=='complete','Conversation did not complete')
        receipts=reply.get('home_actions',[])
        if len(receipts)!=2 or not all(x['status']=='complete' for x in receipts):
            rendered=json.dumps({'phase':'unexpected_receipts','field':field,'receipts':receipts,
                'synthetic_reply':reply['text'],'activity':agent.runtime.activity(),'states':home.states})
            for secret in (store.snapshot()[1]['azure'],gateway_token,tool_token):rendered=rendered.replace(secret,'[redacted]')
            print(rendered,flush=True)
        require(len(receipts)==2 and all(x['status']=='complete' for x in receipts),'Expected two verified home actions')
        require(all(x['attributes'][field]==expected for x in home.states.values()),'Synthetic light state did not match')
        require(not actions.scopes,'Action authority outlived its request')
        events=[x['state'] for x in agent.runtime.activity()['events'] if x['time']>=event_start]
        require('acting' in events,'No actual home-action progress event arrived')
        results.append({'verified_actions':len(receipts),'field':field,'seconds':round(time.monotonic()-began,2),'acting_event':True})
        print(json.dumps({'phase':'verified',**results[-1]}),flush=True)
    before=len(home.writes);cancel=threading.Event();home.cancel=cancel
    reply=agent.respond('Turn both study lights off.','test',allow_home_actions=True,cancel=cancel)
    require(reply['status']=='unavailable' and cancel.is_set(),'Cancellation was not observed')
    require(not actions.scopes,'Cancelled scope remains active')
    time.sleep(1)
    require(len(home.writes)==before+1,'A new action was admitted after cancellation')
    print(json.dumps({'result':'PASS','natural_language':results,'cancelled_after_first_action':True,
        'total_synthetic_writes':len(home.writes),'real_home_actions':0,'audio_played':False}),flush=True)
finally:
    server.shutdown();process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--eager-tools',action='store_true',help='Present the three tools directly (the production default)')
    group.add_argument('--deferred-tools',dest='eager_tools',action='store_false',help='Compare the older deferred tool discovery mode')
    parser.set_defaults(eager_tools=True)
    args=parser.parse_args()
    extract="from pathlib import Path; import json; from backend.settings import SettingsStore; s,k,_=SettingsStore(Path('/opt/echo')).snapshot(); assert s.provider=='azure' and s.agent_runtime=='hermes'; print(json.dumps({'settings':s.model_dump(),'key':k['azure']}))"
    private=subprocess.run([*DOCKER,'exec','echo-api','python','-c',extract],check=True,capture_output=True)
    payload=json.loads(private.stdout)
    payload['eager_tools']=args.eager_tools
    payload['backend']={p.name:p.read_text(encoding='utf-8') for p in (ROOT/'backend').glob('*.py')}
    payload['home_tools']=(ROOT/'deploy/remote/home_tools.py').read_text(encoding='utf-8')
    runner=RUNNER
    result=subprocess.run([*DOCKER,'run','--rm','-i','--init','--name','echo-conversation-check',
        '--network','bridge','--add-host','api:127.0.0.1','--add-host','agent:127.0.0.1',
        '--cpus','2','--memory','1536m','--memory-swap','1536m','--pids-limit','256',
        '--log-driver','none','--user','10000:10000',
        '--tmpfs','/opt/data:rw,nosuid,nodev,size=268435456,uid=10000,gid=10000,mode=0700',
        '--tmpfs','/run/echo:rw,nosuid,nodev,size=16777216,uid=10000,gid=10000,mode=0700',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=268435456,mode=1777',
        '-e','HERMES_HOME=/opt/data','-e','HOME=/opt/data','-e','PYTHONDONTWRITEBYTECODE=1',
        '--entrypoint','/opt/hermes/.venv/bin/python','echo-hermes:trial-0.1','-c',runner],
        input=json.dumps(payload).encode())
    return result.returncode


if __name__=='__main__':sys.exit(main())
