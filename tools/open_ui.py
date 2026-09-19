"""Open the local Echo app without placing the device bearer token in the browser."""
import argparse
import json
import sys
from pathlib import Path
import webbrowser
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def launch_url(settings=False, display=False):
    target=ROOT/'local/host-target.json'
    if target.exists():
        mode=json.loads(target.read_text()).get('mode')
        if mode=='migrating':raise RuntimeError('Echo is moving between hosts; wait for the transfer to finish')
        if mode=='remote':
            from tools.open_remote_ui import launch_url as remote_url
            return remote_url(settings,expected_mode='device',display=display)
        raise ValueError('Unknown Echo host target')
    token = (ROOT/'local/api-token').read_text(encoding='utf-8').strip()
    with httpx.Client(base_url='http://127.0.0.1:8768', trust_env=False, timeout=5) as client:
        response = client.post('/v1/ui/ticket', headers={'Authorization': 'Bearer '+token})
        response.raise_for_status()
        return 'http://127.0.0.1:8768'+('/display' if display else '/settings' if settings else '/')+'#ticket='+response.json()['ticket']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    pages = parser.add_mutually_exclusive_group()
    pages.add_argument('--settings', action='store_true')
    pages.add_argument('--display', action='store_true')
    args = parser.parse_args()
    try:
        webbrowser.open(launch_url(args.settings, args.display))
        print('Echo opened with a single-use sign-in link. Speaker volume is unchanged.')
    except (OSError, ValueError, RuntimeError, httpx.HTTPError):
        raise SystemExit('Start the local host with tools/run.ps1 start, then try again.')
