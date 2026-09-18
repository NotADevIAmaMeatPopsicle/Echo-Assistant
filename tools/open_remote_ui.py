"""Open the isolated Linux validation UI through its private SSH tunnel."""
import argparse
import sys
from pathlib import Path
import webbrowser
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from tools.start_remote_api import connection, tunnel

def launch_url(settings=False,expected_mode='validation'):
    tunnel();value=connection()
    with httpx.Client(base_url=value['url'],headers={'Authorization':'Bearer '+value['token']},
                      trust_env=False,follow_redirects=False,timeout=10) as client:
        health=client.get('/health');health.raise_for_status()
        if health.json().get('deployment_mode')!=expected_mode:raise RuntimeError('The selected Echo host is in a different deployment mode')
        result=client.post('/v1/ui/ticket');result.raise_for_status()
    # A different loopback hostname keeps its cookie separate from the device UI.
    return value['url'].replace('127.0.0.1','localhost')+('/settings' if settings else '/')+'#ticket='+result.json()['ticket']

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',action='store_true')
    args=parser.parse_args()
    webbrowser.open(launch_url(args.settings))
