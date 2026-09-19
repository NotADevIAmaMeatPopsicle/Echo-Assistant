# A clear display at its native size

The Pi layout is designed for a 1024 × 600 landscape touchscreen. Its main
controls remain large enough to touch; longer pages scroll. Smaller text is
reserved for supporting information, not primary actions.

## Visual language

- Dark blue surfaces with gently brighter blue edges and mint action buttons.
- Locally served Manrope for consistent text on Linux, Windows and phones.
- Vector icons and a four-pixel blue-green ring with a soft underglow.
- A fixed ring edge; only the glow changes opacity. Scaling the entire ring
  during animation can soften its edge on a low-density panel.
- Blue for listening, lavender for thinking, mint for speaking, amber for mute,
  and slate for a lost connection. Status text supplies the same information.
- Visible keyboard focus and reduced-motion support.

The display styling is in `web/display/polish.css`. The bundled font's original
[license and source notice](../web/fonts/README.md) travel with the project;
loading the interface does not contact a font service.

![Home at 1024 × 600, with synthetic household data](images/display-home.png)

![Conversation at 1024 × 600, with synthetic messages](images/display-echo.png)

## Avoiding unnecessary scaling

Use the panel's preferred mode rather than a larger accepted HDMI input mode.
A controller may accept 1080p while its physical panel has fewer pixels.
Browser zoom and desktop fractional scaling can further soften text.

Echo's optional `deploy/pi/x11-session.sh` is for a dedicated X11 kiosk. It sets
`ECHO_DEDICATED_X11=1`; the launcher reads the active primary monitor's bounds
from `xrandr` and requests a matching Chromium window at scale factor 1. This
removes the default ten-pixel inset seen without a window manager. It does not
change HDMI modes, overscan, desktop settings or touch calibration. A normal
desktop or Wayland session keeps its own scaling and monitor management.

For the current development panel, 1024 × 600 is both the preferred HDMI timing
and the active mode, with no X11 scaling transform. Chromium's dedicated X11
window now starts at the screen origin; this Chromium build retains a one-pixel
right/bottom inset. The exact physical panel model is still unverified.

## Evidence and limits

The visual pass was checked in Chromium at 1024 × 600 and phone width, including
the native listening controls. It is deployed on the Pi and its screen was
captured after the kiosk restart. The gallery above uses synthetic data only.
Physical screen clarity, touch calibration and microphone/speaker acceptance
remain separate checks; screenshots cannot establish those properties.
