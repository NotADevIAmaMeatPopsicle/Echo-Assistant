"""Start the alternate UI on container loopback; keep all state in existing tmpfs.

No stdout: this helper also runs ahead of a transparent browser TCP relay.
"""
import fcntl
import os
from pathlib import Path
import socket
import subprocess
import time

PORT = 8787
ROOT = Path('/opt/data')
PYTHON = '/opt/hermes/.venv/bin/python'


def ready():
    try:
        with socket.create_connection(('127.0.0.1', PORT), timeout=1):
            return True
    except OSError:
        return False


def main():
    with (ROOT / '.echo-webui-start.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if ready():
            return
        if not Path('/opt/echo-webui/server.py').is_file():
            raise RuntimeError('Install the pinned Echo WebUI source first')
        from dotenv import dotenv_values
        key = dotenv_values(ROOT / '.env').get('API_SERVER_KEY')
        if not key:
            raise RuntimeError('Echo gateway has not been provisioned')
        env = dict(os.environ)
        env.update(
            HERMES_HOME=str(ROOT), HOME=str(ROOT),
            HERMES_WEBUI_AGENT_DIR='/opt/hermes', HERMES_WEBUI_PYTHON=PYTHON,
            HERMES_WEBUI_HOST='127.0.0.1', HERMES_WEBUI_PORT=str(PORT),
            HERMES_WEBUI_STATE_DIR=str(ROOT / 'webui'),
            HERMES_WEBUI_CHAT_BACKEND='gateway',
            HERMES_WEBUI_GATEWAY_BASE_URL='http://127.0.0.1:8642',
            HERMES_API_URL='http://127.0.0.1:8642',
            HERMES_WEBUI_GATEWAY_API_KEY=key, API_SERVER_KEY=key,
            HERMES_WEBUI_GATEWAY_USE_RUNS_API='true',
            HERMES_WEBUI_AUTO_INSTALL='0', PYTHONDONTWRITEBYTECODE='1',
            PYTHONUNBUFFERED='1',
        )
        # The UI needs the same profile, not root privilege or the retired home.
        identity = {'user': 10000, 'group': 10000, 'extra_groups': []} if os.geteuid() == 0 else {}
        log_path = ROOT / 'webui.log'
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        if os.geteuid() == 0:
            os.fchown(fd, 10000, 10000)
        with os.fdopen(fd, 'ab', buffering=0) as log:
            child = subprocess.Popen(
                [PYTHON, '/opt/echo-webui/server.py'], env=env, cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True, **identity,
            )
        for _ in range(100):
            if ready():
                return
            if child.poll() is not None:
                break
            time.sleep(.25)
        raise RuntimeError('Hermes WebUI did not start; inspect its volatile startup log')


if __name__ == '__main__':
    main()
