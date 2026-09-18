"""Run a disposable synthetic-board check; the physical speaker is untouched."""
from backend import deployment
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

if __name__=='__main__':
    result=subprocess.run(['docker','--context',deployment.docker_context(),'run','--rm','-i','--init',
        '--name','echo-voice-check','--network','none','--cpus','3','--memory','2g','--memory-swap','2g',
        '--log-driver','none','--user','10000:10000',
        '--tmpfs','/opt/echo/local:rw,nosuid,nodev,size=67108864,uid=10000,gid=10000,mode=0700',
        '--tmpfs','/run/echo:rw,nosuid,nodev,size=16777216,uid=10000,gid=10000,mode=0700',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=268435456,mode=1777',
        '-v','echo_models:/models:ro','-e','ECHO_SYNTHETIC_CHECK=1','-e','ECHO_DEPLOYMENT_MODE=device',
        '-e','ECHO_VOICE_ENABLED=1','--entrypoint','python','echo-host:validation-0.1',
        '-c','import sys; exec(compile(sys.stdin.read(),"synthetic_voice_check","exec"))'],
        input=(ROOT/'tools/check_linux_voice.py').read_bytes())
    sys.exit(result.returncode)
