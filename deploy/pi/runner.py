"""Stable entry point for an installed, locally versioned Echo display bundle."""
import json
import os
from pathlib import Path
import re
import sys


def selected_release(base):
    state=json.loads((base/'release.json').read_text())
    identifier=state['active']
    if not re.fullmatch(r'[a-f0-9]{16}',identifier):raise ValueError('Invalid release selection')
    path=base/'releases'/identifier
    if path.is_symlink() or not path.is_dir():raise ValueError('Installed release unavailable')
    return path


def main():
    if len(sys.argv)!=2 or sys.argv[1] not in {'bridge','kiosk'}:raise SystemExit('Choose bridge or kiosk')
    base=Path.home()/'.local/share/echo-display'
    release=selected_release(base)
    target=release/(sys.argv[1]+'.py')
    os.execv(sys.executable,[sys.executable,str(target)])


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError):raise SystemExit('Echo display bundle unavailable. Run setup.py --check or --rollback.') from None
