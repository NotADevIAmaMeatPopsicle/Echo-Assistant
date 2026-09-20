"""Install only the optional pinned Pi Sendspin player runtime. Does not enable audio."""
import ctypes.util
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import venv


def main():
    if sys.platform!='linux' or platform.machine()!='aarch64' or sys.version_info[:2]!=(3,13):
        raise SystemExit('This wheel lock targets the 64-bit Pi image with Python 3.13.')
    if not ctypes.util.find_library('portaudio'):
        raise SystemExit('Install the OS package libportaudio2 first. Existing audio settings were not changed.')
    root=Path.home()/'.local/share/echo-display/runtime/group-music'
    if root.is_symlink():raise ValueError('Use a regular private runtime directory')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if shutil.disk_usage(root).free<600_000_000:raise SystemExit('Free at least 600 MB before installing this optional runtime.')
    python=root/'bin/python'
    if not python.is_file():venv.EnvBuilder(with_pip=True).create(root)
    subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','--no-cache-dir','--no-deps',
                    '--require-hashes','--only-binary=:all:','-r',str(Path(__file__).with_name('group-music-pi313.lock'))],check=True)
    # These imports do not create a player, open an audio stream or connect to MA.
    subprocess.run([str(python),'-c','from aiosendspin.client import SendspinClient; from sendspin.audio_connector import AudioStreamHandler; print("Optional player runtime ready; no audio opened.")'],check=True)
    print('Install the current display bundle, authorize this paired receiver in owner Settings, then choose its output. Grouped playback remains disabled until configured.')


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError):raise SystemExit('Grouped-player installation failed. Pairing and existing voice/Spotify settings were preserved.') from None
