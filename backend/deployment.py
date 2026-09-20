"""Nonsecret deployment choices; credentials belong in the encrypted stores."""
import ipaddress
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def value(name, default=''):
    path = ROOT/'local/deployment.json'
    config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    result = os.environ.get('ECHO_'+name.upper(), config.get(name, default))
    if not isinstance(result, str): raise ValueError('Deployment values must be strings')
    return result.strip()


def ssh_target():
    result = value('ssh_target', 'echo-host')
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,200}', result) or result.startswith('-'):
        raise ValueError('ECHO_SSH_TARGET must be an SSH alias or user@host')
    return result


def docker_context():
    result = value('docker_context', 'echo-host')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', result) or result.startswith('-'):
        raise ValueError('Invalid ECHO_DOCKER_CONTEXT')
    return result


def calling_private_origin():
    """Optional deployment binding; never inferred from owner call settings."""
    from .calling import LiveKit
    return LiveKit(private_origin=value('calling_private_origin')).private_origin


def device_host():
    result = value('device_host', os.environ.get('ECHO_BIND_ADDRESS',''))
    try: address = ipaddress.IPv4Address(result)
    except ValueError: raise ValueError('Set ECHO_DEVICE_HOST to the server LAN IPv4 address') from None
    if not any(address in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
        raise ValueError('ECHO_DEVICE_HOST must be a private LAN IPv4 address')
    return result


def lan_subnet():
    try: network = ipaddress.IPv4Network(value('lan_subnet'), strict=True)
    except ValueError: raise ValueError('Set ECHO_LAN_SUBNET to the intended LAN CIDR') from None
    if ipaddress.IPv4Address(device_host()) not in network or not network.is_private:
        raise ValueError('ECHO_LAN_SUBNET must contain the configured private host address')
    return str(network)
