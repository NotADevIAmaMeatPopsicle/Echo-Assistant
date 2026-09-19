"""Launch the large Echo display in an existing Linux desktop session.

--check is read-only. Launching creates a separate Chromium profile; it does not
replace an existing kiosk, install packages, change audio, or configure login.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
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


def x11_geometry(output):
    """Use the active primary monitor, not the virtual desktop or an EDID mode."""
    monitors = re.findall(r'^\S+ connected (primary )?(\d+)x(\d+)([+-]\d+)([+-]\d+)\b', output, re.M)
    primary = [item for item in monitors if item[0]]
    selected = primary or (monitors if len(monitors) == 1 else [])
    if len(selected) != 1:
        return []
    _, width, height, left, top = selected[0]
    return [f'--window-size={width},{height}', f'--window-position={int(left)},{int(top)}']


def dedicated_x11_flags():
    # A bare startx session has no window manager to honor Chromium's fullscreen
    # request. Explicit bounds remove its default 10px inset. Desktop/Wayland
    # sessions keep their own monitor selection and accessibility scaling.
    if os.environ.get('ECHO_DEDICATED_X11') != '1' or not os.environ.get('DISPLAY'):
        return []
    try:
        result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True, check=True, timeout=5)
        bounds = x11_geometry(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return []
    return ['--ozone-platform=x11', '--force-device-scale-factor=1', *bounds] if bounds else []


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
    os.execv(browser,[browser,'--kiosk','--no-first-run','--noerrdialogs',*dedicated_x11_flags(),f'--user-data-dir={profile}',url])


if __name__ == '__main__':
    try: main()
    except (OSError,ValueError,KeyError) as error: raise SystemExit(str(error)) from None
