"""Run existing browser checks against a fresh private synthetic preview per check.

Requires Node, Playwright and Chrome already installed. Installs nothing, never
uses the live Echo server, and stops only the preview processes it creates.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
CHECKS=('smart_display_ui','display_connection','display_conversation','display_voice_ui',
        'display_daily','display_music','display_cameras','display_announcements',
        'display_intercom','pi_spotify_ui','display_alerts_ui','pi_voice_ui','display_keyboard','display_form_keyboard','display_home','display_screen','display_presence')


def run_check(name,node,output):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    env={**os.environ,'ECHO_PREVIEW_URL':base,'PYTHONUTF8':'1'}
    with (output/(name+'-preview.log')).open('w',encoding='utf-8') as log:
        preview=subprocess.Popen([sys.executable,'-u','tools/preview_smart_display.py','--port',str(port)],
            cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            until=time.monotonic()+15
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while True:
                if preview.poll() is not None:raise RuntimeError('Synthetic preview exited; inspect '+str(output))
                try:
                    with opener.open(base+'/health',timeout=1) as response:
                        if json.load(response).get('display_demo') is True:break
                except (urllib.error.URLError,TimeoutError,ValueError):pass
                if time.monotonic()>=until:raise RuntimeError('Synthetic preview did not start')
                time.sleep(.1)
            print('Checking '+name+'...',flush=True)
            subprocess.run([node,str(ROOT/'tools'/('check_'+name+'.cjs'))],cwd=ROOT,env=env,check=True,timeout=120)
        finally:
            if preview.poll() is None:
                preview.terminate()
                try:preview.wait(timeout=5)
                except subprocess.TimeoutExpired:preview.kill();preview.wait(timeout=5)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node',default=shutil.which('node'))
    parser.add_argument('--check',action='append',choices=CHECKS,help='Run only the named check; repeat as needed')
    args=parser.parse_args()
    if not args.node:raise SystemExit('Node is required; no runtime was installed.')
    output=ROOT/'output/package-checks';output.mkdir(parents=True,exist_ok=True)
    checks=args.check or CHECKS;passed=[]
    try:
        for name in checks:run_check(name,args.node,output);passed.append(name)
    finally:
        (output/'browser-results.json').write_text(json.dumps({'requested':list(checks),'passed':passed},indent=2))
    print(f'PASS: {len(passed)} isolated synthetic browser checks. No live devices or audio used.')


if __name__=='__main__':main()
