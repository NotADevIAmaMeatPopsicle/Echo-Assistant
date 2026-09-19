"""Stable audio ownership. Browser sessions are not room identities."""
import re


def validate_destination(value):
    if not isinstance(value, str) or not re.fullmatch(r'round|display:[a-f0-9]{32}', value):
        raise ValueError('Invalid audio destination')
    return value


def destination_for(session):
    return validate_destination(session) if session.startswith('display:') else 'round'
