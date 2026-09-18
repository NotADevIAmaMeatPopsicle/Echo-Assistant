"""Run silent Linux integration checks in a disposable container with no account data."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
RUNNER=r'''
import json, os, runpy, sys, tempfile, unittest, urllib.request
from pathlib import Path
assert os.environ.get('ECHO_ISOLATED_CHECK')=='1', 'Use the disposable check container'
key=Path('/run/echo/storage.key');key.write_bytes(os.urandom(32));key.chmod(0o600)
files=json.load(sys.stdin)
os.environ['PYTHONPATH']='/opt/echo'
with tempfile.TemporaryDirectory(prefix='echo-native-checks-') as directory:
    root=Path(directory)
    for name, source in files.items():
        assert '/' not in name and '\\' not in name
        (root/name).write_text(source)
    sys.path.insert(0,'/opt/echo')
from backend import deployment
    suite=unittest.defaultTestLoader.discover(directory,pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful(): sys.exit(1)
    runpy.run_path(str(root/'check_linux_receiver.py'),run_name='__main__')
'''


def main():
    names=('test_echo.py','test_transport.py','test_lifecycle.py','test_linux_storage.py','test_container_supervisor.py',
           'test_spotify_credentials.py','test_host_migration.py','test_music_commands.py','test_speaker_check.py','test_spoken_reply.py',
           'test_home_actions.py','test_container_host.py','test_agent_runtime.py','test_agent_apply.py','test_conversation_context.py',
           'test_music_conversation.py','test_music.py','test_home_lights.py','test_display.py','test_home_speakers.py',
           'test_conversation_activity.py','test_conversation_cancellation.py','test_routines.py')
    files={name:(ROOT/'tests'/name).read_text(encoding='utf-8') for name in names}
    files['check_linux_receiver.py']=(ROOT/'tools/check_linux_receiver.py').read_text(encoding='utf-8')
    result=subprocess.run(['docker','--context',deployment.docker_context(),'run','--rm','-i','--init',
        '--name','echo-native-check','--network','bridge','--cpus','2','--memory','1g',
        '--memory-swap','1g','--log-driver','none','--user','10000:10000',
        '--tmpfs','/opt/echo/local:rw,nosuid,nodev,size=67108864,uid=10000,gid=10000,mode=0700',
        '--tmpfs','/run/echo:rw,nosuid,nodev,size=16777216,uid=10000,gid=10000,mode=0700',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=268435456,mode=1777',
        '-e','ECHO_ISOLATED_CHECK=1','--entrypoint','python','echo-host:validation-0.1','-c',RUNNER],input=json.dumps(files).encode())
    return result.returncode


if __name__=='__main__': sys.exit(main())
