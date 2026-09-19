"""Launch the large Echo display in an existing Linux desktop session.

--check is read-only. Launching creates a separate Chromium profile; it does not
replace an existing kiosk, install packages, change audio, or configure login.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit


def validate_url(value):
    url = urlsplit(value)
    local = url.hostname == 'localhost'
    try: local = local or ipaddress.ip_address(url.hostname or '').is_loopback
    except ValueError: pass
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or url.path != '/display' or (url.scheme != 'https' and not (url.scheme == 'http' and local))):
        raise ValueError('Use an HTTPS /display URL, or loopback HTTP, without credentials, queries, or fragments.')
    _ = url.port  # Validate a supplied port before launching Chromium.
    return value


def inventory():
    model = Path('/proc/device-tree/model')
    cards = Path('/proc/asound/cards')
    return {'model':model.read_text().rstrip('\0') if model.exists() else 'Not detected',
        'display_session':bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')),
        'connectors':{p.parent.name:p.read_text().strip() for p in Path('/sys/class/drm').glob('card*-*/status')},
        'audio_cards':cards.read_text().strip() if cards.exists() else 'No ALSA inventory',
        'chromium':shutil.which('chromium') or shutil.which('chromium-browser'),
        'note':'Read-only inventory. No microphone capture, playback, or service changes.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path.home()/'.config/echo-display/config.json')
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    if sys.platform != 'linux': raise SystemExit('The kiosk launcher targets Linux. Use /display in your browser on other systems.')
    report = inventory()
    if args.check: print(json.dumps(report,indent=2)); return
    if not report['display_session']: raise SystemExit('Start an existing graphical desktop session first.')
    if not report['chromium']: raise SystemExit('Chromium was not found. See docs/SMART_DISPLAY.md for setup.')
    configuration = json.loads(args.config.read_text())
    url = validate_url(configuration['url'])
    profile = Path.home()/'.local/share/echo-display/chromium'
    profile.mkdir(parents=True,exist_ok=True,mode=0o700)
    profile.chmod(0o700)
    browser = report['chromium']
    os.execv(browser,[browser,'--kiosk','--no-first-run','--noerrdialogs',f'--user-data-dir={profile}',url])


if __name__ == '__main__':
    try: main()
    except (OSError,ValueError,KeyError) as error: raise SystemExit(str(error)) from None
