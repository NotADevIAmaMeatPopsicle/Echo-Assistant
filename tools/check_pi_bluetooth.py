#!/usr/bin/env python3
"""Inspect optional Pi Bluetooth receiver prerequisites. Never installs or plays."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy' / 'pi'))
from bluetooth_backend import inventory
from bluetooth_receiver import BluetoothReceiver, DEFAULT_CONFIG, load_private_config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Existing owner-only private configuration; no file is created')
    args = parser.parse_args(argv)
    try:
        config = load_private_config(args.config) if args.config else dict(DEFAULT_CONFIG)
    except (OSError, ValueError, TypeError):
        print(json.dumps({'supported': False, 'blocked_reason': 'invalid_private_configuration'}))
        return 1
    receiver = BluetoothReceiver(config, lambda: None)
    result = receiver.check()
    result['inventory'] = inventory()
    result['configured_enabled'] = config['enabled']
    result['audio_opened'] = False
    if result['inventory']['competing_audio_manager'] is True:
        result.update(supported=False, blocked_reason='competing_audio_manager')
    if result['inventory']['rfkill_blocked'] is True:
        result.update(supported=False, blocked_reason='bluetooth_rfkill_blocked')
    print(json.dumps(result, indent=2))
    return 0 if result['supported'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
