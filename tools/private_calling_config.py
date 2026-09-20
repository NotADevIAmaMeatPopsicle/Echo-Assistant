"""Export existing protected calling credentials to one new private LiveKit config.

Run only inside echo-api. This helper does not generate credentials, configure
Echo, contact a provider or start a service. Its output file contains secrets.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.calling import CallSettings, CallStore, LiveKit, raw_settings
from backend.linux_protection import LinuxProtector


def render_config(settings, private_origin, node_ip):
    """Pure pinned server configuration; accepting disabled Echo setup is deliberate."""
    try:
        if not isinstance(settings, CallSettings) or not private_origin:
            raise ValueError()
        binding = LiveKit(private_origin=private_origin)
        # Disabled settings may omit credentials. Export still requires a valid
        # complete provider connection, without enabling or mutating the store.
        checked = CallSettings.model_validate({**raw_settings(settings), 'enabled': True})
        if not binding.private_transport(checked):
            raise ValueError()
        address = ipaddress.IPv4Address(node_ip)
        if not isinstance(node_ip, str) or str(address) != node_ip or address not in ipaddress.IPv4Network('100.64.0.0/10'):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('A matching private origin, saved credentials and a literal tailnet IPv4 address are required') from None
    return {
        'port': 7880,
        'bind_addresses': ['0.0.0.0'],
        'rtc': {'tcp_port': 7881, 'force_tcp': True, 'node_ip': str(address),
                'use_external_ip': False, 'advertise_internal_ip': False},
        'keys': {checked.api_key.get_secret_value(): checked.api_secret.get_secret_value()},
    }


def _private_directory(path):
    """Pin every path component without following symlinks, then check the owner."""
    if (os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY')
            or os.open not in os.supports_dir_fd or not path.is_absolute()):
        raise ValueError('A private POSIX runtime directory is required')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    descriptor = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            if component in {'.', '..'}:
                raise ValueError('Use the exact private runtime directory')
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Runtime directory must be owned by the service with mode 0700')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def write_new_config(config, output, *, private_dir=Path('/run/echo')):
    """Create exactly one new 0600 file inside a pinned private directory."""
    output, private_dir = Path(output), Path(private_dir)
    if (not output.is_absolute() or output.parent != private_dir
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.json', output.name)):
        raise ValueError('Choose a new JSON filename directly in the private runtime directory')
    raw = (json.dumps(config, separators=(',', ':'), ensure_ascii=True) + '\n').encode('utf-8')
    if len(raw) > 8192:
        raise ValueError('Private calling configuration exceeds its bound')
    directory = _private_directory(private_dir)
    descriptor = None
    created = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        descriptor = os.open(output.name, flags, 0o600, dir_fd=directory)
        created = os.fstat(descriptor)
        if (not stat.S_ISREG(created.st_mode) or created.st_uid != os.geteuid()
                or created.st_nlink != 1 or stat.S_IMODE(created.st_mode) != 0o600):
            raise ValueError('New configuration is not a private regular file')
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                raise OSError('Configuration write did not finish')
            written += count
        os.fsync(descriptor)
    except BaseException:
        # Never unlink an existing file or a replacement not created by us.
        if created is not None:
            try:
                current = os.stat(output.name, dir_fd=directory, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                    os.unlink(output.name, dir_fd=directory)
            except OSError:
                pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes invalid argument values. Keep diagnostics
        # fixed, including when someone mistakenly supplies a credential.
        raise ValueError('Use --node-ip and --output')


def main(argv=None):
    try:
        parser = _Arguments(description=__doc__)
        parser.add_argument('--node-ip', required=True)
        parser.add_argument('--output', required=True)
        args = parser.parse_args(argv)
        if (sys.platform != 'linux' or os.environ.get('ECHO_CONTAINER') != '1'
                or ROOT != Path('/opt/echo') or os.geteuid() == 0):
            raise ValueError('Run as the existing echo-api service user')
        # Validate the private runtime before opening protected credentials.
        directory = _private_directory(Path('/run/echo'))
        os.close(directory)
        source = ROOT/'local/echo-calling.json'
        if source.is_symlink() or not source.is_file():
            raise ValueError('Existing protected calling settings are required')
        private_origin = os.environ.get('ECHO_CALLING_PRIVATE_ORIGIN', '')
        if not private_origin:
            raise ValueError('Private calling deployment is not configured')
        LiveKit(private_origin=private_origin)
        store = CallStore(ROOT, LinuxProtector())
        config = render_config(store.require(), private_origin, args.node_ip)
        write_new_config(config, args.output)
    except Exception:
        print('Private calling configuration was not saved.', file=sys.stderr)
        return 1
    print(json.dumps({'saved': True}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
