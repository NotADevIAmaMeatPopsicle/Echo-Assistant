#!/bin/sh
# Managed by Echo display setup
# Optional session entry for an existing dedicated X11 kiosk service.
if command -v xset >/dev/null 2>&1; then
    xset s off || true
    xset -dpms || true
    xset s noblank || true
fi
if command -v unclutter >/dev/null 2>&1; then
    unclutter -idle 1 -root &
fi
exec /usr/bin/python3 "$HOME/.local/share/echo-display/runner.py" kiosk
