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
- A large, steady clock with a smaller mint AM/PM marker and room for the date.
  Both home and ambient clocks respect the saved 12/24-hour choice; screen
  readers receive the complete localized time.

The display styling is in `web/display/polish.css`. The bundled font's original
[license and source notice](../web/fonts/README.md) travel with the project;
loading the interface does not contact a font service.

![Home at 1024 × 600, with synthetic household data](images/display-home.png)

![Conversation at 1024 × 600, with synthetic messages](images/display-echo.png)

![Ambient clock with separate day-period marker, using synthetic data](images/display-ambient.png)

## Touchscreen text entry

On landscape displays wider than 760 pixels, text fields open Echo's local
keyboard. In chat it sits below the composer; elsewhere it docks along the
bottom and scrolls the active field into view. Modal forms keep their keyboard
inside the dialog so the browser's modal focus boundary remains intact.

Word suggestions and English swipe typing run locally. Passwords, URLs,
telephone fields and fields marked `data-keyboard="literal"` use tap entry
without word suggestions. Text fields retain their original input mode when
the keyboard closes. Date/time pickers, number controls, selects and phone
keyboards keep their browser behavior.

Previous/next arrows move between editable text fields in the current form.
The newline key inserts a line in a note; Done hides the keyboard. Neither
submits a form. Add, Save, Send and Create event remain separate actions.
Physical typing dismisses the local keyboard, and closing a dialog or changing
pages clears its active field. The keyboard saves no drafts or keystroke history.

Focused synthetic browser checks cover list entry, note editing, calendar
drafts, explicit saving, field visibility at 1024 × 600 and phone fallback.

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

For a dedicated touchscreen, start X with `-nocursor` as shown in the
[kiosk service example](SMART_DISPLAY.md#reusing-a-dedicated-x11-kiosk).
This hides the pointer throughout the session without disabling touch input.
An idle cursor-hiding utility alone lets the hand reappear on each tap.

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

The live idle-screen capture exposed an oversized day-period suffix crowding
the date. The clock now separates that suffix from the digits, keeps its edges
unscaled, and leaves an explicit gap above the date. Focused browser checks
cover 12/24-hour switching, date separation, and phone-width layout.
