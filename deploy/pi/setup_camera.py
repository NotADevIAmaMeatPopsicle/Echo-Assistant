"""Enable the optional Echo virtual webcam after installing the distro camera packages."""
import os
from pathlib import Path
import subprocess

MARKER = '# Managed by Echo camera setup\n'


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run sudo python3 setup_camera.py after installing the camera packages.')
    name = Path('/sys/class/video4linux/video42/name')
    if name.exists() and name.read_text().strip() != 'Echo Camera':
        raise SystemExit('Video device 42 is already in use. Existing camera configuration was preserved.')
    files = {
        Path('/etc/modules-load.d/echo-camera.conf'): MARKER + 'v4l2loopback\n',
        Path('/etc/modprobe.d/echo-camera.conf'): MARKER + 'options v4l2loopback video_nr=42 card_label="Echo Camera" exclusive_caps=1\n',
    }
    for path in files:
        if path.is_symlink() or path.exists() and not path.read_text().startswith(MARKER):
            raise SystemExit('An unmanaged Echo camera configuration already exists; it was preserved.')
    subprocess.run(['/usr/sbin/modprobe', 'v4l2loopback', 'video_nr=42', 'card_label=Echo Camera',
                    'exclusive_caps=1'], check=True, timeout=15)
    if not name.exists() or name.read_text().strip() != 'Echo Camera':
        raise SystemExit('A different loopback configuration is loaded. Reconcile it before enabling Echo Camera.')
    for path, text in files.items():
        path.write_text(text);path.chmod(0o644)
    print('Echo Camera is available. The physical camera remains off until requested.')


if __name__ == '__main__':
    main()
