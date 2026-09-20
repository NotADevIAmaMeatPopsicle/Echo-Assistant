"""Read content-free bridge health; stale files never imply an active microphone."""
import json
from pathlib import Path
import time
import math
from .wake import PHRASES


def voice_status(root: Path, now=None):
    try:
        data = json.loads((root / "local/voice-status.json").read_text(encoding="utf-8"))
        phases = {'connecting', 'disconnected', 'armed', 'activation', 'listening', 'thinking',
                  'speaking', 'music', 'alarm', 'cooldown', 'muted', 'intercom'}
        if not isinstance(data, dict) or not isinstance(data.get('status'), str) or data['status'] not in phases:
            raise ValueError('Invalid bridge health')
        timestamp = data.get('updated_at')
        if type(timestamp) not in {int, float} or not math.isfinite(timestamp):
            raise ValueError('Invalid bridge timestamp')
        for section in ('device', 'recognition', 'music', 'speaker', 'network', 'grouped_music'):
            if section in data and not isinstance(data[section], dict):
                raise ValueError('Invalid bridge health section')
        if 'transport' in data and data['transport'] not in ('usb', 'wifi'):
            raise ValueError('Invalid device transport')
        # Read the clock after the file: the writer may publish a newer snapshot
        # while this reader opens it. Measuring first falsely flags it as future.
        checked_at = time.time() if now is None else now
        if not 0 <= checked_at - timestamp < 5:
            raise ValueError("Stale voice process")
        return {**data, 'phrases': PHRASES}
    except (OSError, ValueError, TypeError, OverflowError):
        return {"status": "disconnected", "phrases": PHRASES}
