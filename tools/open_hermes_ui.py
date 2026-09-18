"""Open Echo's Hermes WebUI through an on-demand loopback tunnel.

Docker exec carries each TCP stream over the existing authenticated remote host
connection. No new container ports, passwords, model calls or gateway restart.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
import time
import webbrowser

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import deployment
PORT = 18646
URL = f'http://127.0.0.1:{PORT}/'
DOCKER = ['docker', '--context', deployment.docker_context(), 'exec', '-i', 'echo-agent',
          '/opt/hermes/.venv/bin/python', '-u', '-c']
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

# All WebUI state/output stays in the container's existing volatile home.
START = "import runpy; runpy.run_path('/opt/echo/start_webui.py', run_name='__main__')\n"

# A browser refresh also recovers a stopped WebUI, without replaying an
# HTTP request. The container-side lock prevents concurrent browser sockets
# from launching multiple WebUI processes. START writes no protocol bytes.
RELAY = START + r'''
import os,socket,threading
s=socket.create_connection(('127.0.0.1',8787),timeout=10)
s.settimeout(None)
def upstream():
    try:
        while True:
            data=os.read(0,65536)
            if not data: break
            s.sendall(data)
    except OSError: pass
    finally:
        try: s.shutdown(socket.SHUT_WR)
        except OSError: pass
threading.Thread(target=upstream,daemon=True).start()
try:
    while True:
        data=s.recv(65536)
        if not data: break
        view=memoryview(data)
        while view:
            sent=os.write(1,view)
            view=view[sent:]
finally: s.close()
'''


class Tunnel(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    slots = threading.BoundedSemaphore(12)


class Stream(socketserver.BaseRequestHandler):
    def handle(self):
        if not self.server.slots.acquire(timeout=2): return
        process = None
        try:
            process = subprocess.Popen(DOCKER+[RELAY], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                creationflags=FLAGS)

            def upload():
                try:
                    while True:
                        data = self.request.recv(65536)
                        if not data: break
                        view = memoryview(data)
                        while view:
                            sent = process.stdin.write(view)
                            if not sent: raise OSError('Tunnel closed')
                            view = view[sent:]
                except (OSError, ValueError): pass
                finally:
                    try: process.stdin.close()
                    except (OSError, ValueError): pass

            threading.Thread(target=upload, daemon=True).start()
            while True:
                data = os.read(process.stdout.fileno(), 65536)
                if not data: break
                self.request.sendall(data)
        except OSError: pass
        finally:
            if process is not None:
                if process.poll() is None: process.kill()
                process.wait()
                for pipe in (process.stdin, process.stdout):
                    try: pipe.close()
                    except (OSError, ValueError): pass
            self.server.slots.release()


def ensure_webui():
    result = subprocess.run(DOCKER+[START], capture_output=True, timeout=35,
                            creationflags=FLAGS)
    if result.returncode:
        raise RuntimeError('Could not start the Hermes WebUI inside echo-agent.')


def ready():
    try:
        with httpx.Client(trust_env=False, timeout=15) as client:
            response = client.get(URL)
            return response.status_code == 200 and 'Hermes Web' in response.text
    except httpx.HTTPError: return False


def launch_url():
    ensure_webui()
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=1): occupied = True
    except OSError: occupied = False
    if occupied:
        if not ready(): raise RuntimeError('The local WebUI port is occupied by another service.')
        return URL
    (ROOT / 'local').mkdir(exist_ok=True)
    with open(ROOT/'local/hermes-webui-tunnel.log', 'ab') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve'],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=FLAGS)
    (ROOT/'local/hermes-webui-tunnel.json').write_text(json.dumps(
        {'pid': child.pid, 'port': PORT, 'container': 'echo-agent'}))
    for _ in range(12):
        if child.poll() is not None: break
        time.sleep(.25)
        if ready(): return URL
    raise RuntimeError('The private Hermes WebUI tunnel did not become ready.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    if args.serve:
        with Tunnel(('127.0.0.1', PORT), Stream) as server:
            server.serve_forever()
    else:
        url = launch_url()
        if not args.no_open: webbrowser.open(url)
        print(url)
