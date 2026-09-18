"""Check actual MCP argument conversion in an isolated, network-disabled container."""
from backend import deployment
import subprocess

RUNNER=r'''
import asyncio,json,runpy
from pathlib import Path
from unittest.mock import patch
import httpx
Path('/opt/data/echo-home-api.json').write_text(json.dumps({'url':'http://api:8768','token':'synthetic-token-'*4}))
namespace=runpy.run_path('/opt/echo/home_tools.py')
server=namespace['server']
real_client=httpx.Client
requests=[]
def handler(request):
    assert request.url.host=='api' and request.url.port==8768
    requests.append(request)
    if request.method=='POST':
        command=json.loads(request.content)
        assert command['request_id']=='a'*32 and command['entity_id']=='media_player.test'
        assert command['action']=='mute' and command['value'] is True
        return httpx.Response(200,json={'status':'complete','attempted':True})
    return httpx.Response(200,json={'status':'available','devices':[]})
def client(**kwargs):
    assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
    return real_client(**kwargs,transport=httpx.MockTransport(handler))
async def main():
    definitions=await server.list_tools()
    assert {tool.name for tool in definitions}=={'home_devices','home_state','home_action'}
    action=next(tool for tool in definitions if tool.name=='home_action').model_dump(by_alias=True)
    assert 'color_temperature' in action['inputSchema']['properties']['action']['enum']
    with patch('httpx.Client',side_effect=client):
        result=await server.call_tool('home_action',{'request_id':'a'*32,'entity_id':'media_player.test','action':'mute','value':True})
        assert 'complete' in result.model_dump_json()
        result=await server.call_tool('home_devices',{})
        assert 'available' in result.model_dump_json()
    assert len(requests)==2
    print(json.dumps({'mcp_tools':3,'action_enum':True,'boolean_preserved':True,'fixed_api_origin':True,'requests':2,'network':'none'}))
asyncio.run(main())
'''

if __name__=='__main__':
    subprocess.run(['docker','--context',deployment.docker_context(),'run','--rm','--init',
        '--name','echo-home-tools-check','--network','none','--cpus','1','--memory','768m',
        '--memory-swap','768m','--log-driver','none','--user','10000:10000',
        '--tmpfs','/opt/data:rw,nosuid,nodev,size=67108864,uid=10000,gid=10000,mode=0700',
        '--entrypoint','/opt/hermes/.venv/bin/python','echo-hermes:trial-0.1','-c',RUNNER],check=True)
