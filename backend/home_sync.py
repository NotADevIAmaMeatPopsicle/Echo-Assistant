"""Persist home rules with DPAPI on Remote host, then apply via private Docker stdin."""
from .home_policy import policy_hash, validate_policy
from .remote_host import manage


def sync_home_policy(policy):
    policy = validate_policy(policy)
    try:
        result = manage('SavePolicy', policy)
        if result.get('applied') != policy_hash(policy): raise RuntimeError()
    except (RuntimeError, ValueError, OSError):
        raise RuntimeError('Remote host did not confirm home access settings') from None
