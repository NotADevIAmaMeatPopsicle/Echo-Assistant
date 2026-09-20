"""Install or roll back Echo's user-owned Pi display bundle; never writes an SD image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from kiosk import inventory

CORE_FILES=('bridge.py','connect.py','kiosk.py','audio_once.py')
FILES=(*CORE_FILES,'spotify.py','alerts.py','listener.py','screen.py','grouped.py','sendspin_player.py','bluetooth_receiver.py','bluetooth_backend.py','bluetooth_session.py','browser_video.py','browser_video_backend.py','video_session.py')
MARKER='# Managed by Echo display setup'


def atomic(path,text,mode=0o600):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix('.echo-new')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as stream:stream.write(text)
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()


def install_bundle(home,source):
    base=home/'.local/share/echo-display'
    content={name:(source/name).read_bytes() for name in FILES}
    identifier=hashlib.sha256(b''.join(name.encode()+content[name] for name in FILES)).hexdigest()[:16]
    release=base/'releases'/identifier
    if release.is_symlink():raise ValueError('Release directory must not be a symbolic link')
    release.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,raw in content.items():
        path=release/name
        if path.exists():
            if path.is_symlink() or path.read_bytes()!=raw:raise ValueError('Existing release was modified; preserve it and inspect before installing')
        else:atomic(path,raw.decode('utf-8'))
    # The launcher stays identical across normal updates. Rollback selects the
    # previous immutable bundle without touching pairing, profiles, or photos.
    runner=base/'runner.py'
    atomic(runner,(source/'runner.py').read_text(encoding='utf-8'))
    state_path=base/'release.json'
    old=json.loads(state_path.read_text()) if state_path.exists() else {}
    previous=old.get('active')
    if previous is not None and not re.fullmatch(r'[a-f0-9]{16}',previous):raise ValueError('Invalid previous release')
    state={'active':identifier,'previous':previous if previous!=identifier else old.get('previous')}
    atomic(state_path,json.dumps(state))
    return state


def rollback(home):
    base=home/'.local/share/echo-display';path=base/'release.json';state=json.loads(path.read_text())
    previous=state.get('previous')
    if not previous or not re.fullmatch(r'[a-f0-9]{16}',previous):raise ValueError('No previous display bundle is available')
    release=base/'releases'/previous
    if release.is_symlink() or not all((release/name).is_file() for name in CORE_FILES):raise ValueError('Previous bundle is incomplete')
    state={'active':previous,'previous':state['active']};atomic(path,json.dumps(state));return state


def command_arg(value,desktop=False):
    # Both systemd and the desktop entry accept quoted arguments. Neither runs a shell.
    if any(ord(c)<32 for c in str(value)):raise ValueError('Use paths without control characters')
    result=str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')
    result=result.replace('$','\\$' if desktop else '$$')
    if desktop:result=result.replace('`','\\`')
    return '"'+result+'"'


def autostart_files(home,python):
    runner=home/'.local/share/echo-display/runner.py'
    command=f'{command_arg(python)} {command_arg(runner)}'
    unit=MARKER+'\n[Unit]\nDescription=Echo private display bridge\nAfter=network-online.target\n\n[Service]\nExecStart='+command+' bridge\nRestart=on-failure\nRestartSec=5\nNoNewPrivileges=true\nPrivateTmp=true\nUMask=0077\n\n[Install]\nWantedBy=default.target\n'
    desktop_command=f'{command_arg(python,True)} {command_arg(runner,True)}'
    desktop=MARKER+'\n[Desktop Entry]\nType=Application\nName=Echo Display\nExec='+desktop_command+' kiosk\nTerminal=false\nX-GNOME-Autostart-enabled=true\n'
    return {home/'.config/systemd/user/echo-display-bridge.service':unit,home/'.config/autostart/echo-display.desktop':desktop}


def write_autostart(home,python):
    files=autostart_files(home,python)
    for path in files:
        if path.exists() and not path.read_text().startswith(MARKER):raise ValueError('An unmanaged Echo startup file already exists; it was not replaced')
    for path,text in files.items():atomic(path,text)


def service(*args):subprocess.run(['systemctl','--user',*args],check=True,timeout=20)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    choice=parser.add_mutually_exclusive_group(required=True)
    for name in ('check','install','rollback','remove-autostart'):choice.add_argument('--'+name,action='store_true')
    args=parser.parse_args();home=Path.home();source=Path(__file__).resolve().parent
    if args.check:
        print(json.dumps({**inventory(),'paired':(home/'.config/echo-display/connection.json').is_file(),
            'installed':(home/'.local/share/echo-display/release.json').is_file(),
            'systemctl':bool(shutil.which('systemctl'))},indent=2));return
    if sys.platform!='linux' or os.geteuid()==0:raise SystemExit('Run this as the normal Pi desktop user on Linux, without sudo.')
    if args.remove_autostart:
        paths=autostart_files(home,sys.executable)
        for path in paths:
            if path.exists() and not path.read_text().startswith(MARKER):raise ValueError('Refusing to remove an unmanaged startup file')
        service('disable','--now','echo-display-bridge.service')
        for path in paths:
            if path.exists():path.unlink()
        service('daemon-reload');print('Echo autostart removed. Pairing, browser data, and installed bundles were preserved.');return
    if args.rollback:
        state=rollback(home);service('restart','echo-display-bridge.service')
        print('Previous bundle selected: '+state['active']+'. Close and reopen the kiosk, or log out and in.');return
    if not (home/'.config/echo-display/connection.json').is_file():raise ValueError('Pair this display with connect.py before installing autostart')
    if not inventory()['chromium']:raise ValueError('Install Chromium in the existing desktop before continuing')
    state=install_bundle(home,source);write_autostart(home,sys.executable)
    service('daemon-reload');service('enable','--now','echo-display-bridge.service');service('restart','echo-display-bridge.service')
    print('Installed bundle '+state['active']+'. Echo opens at the next desktop login. Existing kiosks were not modified.')


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):raise SystemExit('Setup could not finish. Existing pairing and data are preserved. Check the desktop user, pairing, and user systemd service.') from None
