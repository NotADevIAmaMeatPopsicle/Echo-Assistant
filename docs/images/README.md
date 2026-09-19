# Public illustrations

- `echo.svg` is the original illustrative hero artwork.
- `prototype-front.jpg`, `prototype-board-rear.jpg`, and
  `prototype-wiring-rear.jpg` are photographs supplied for publication of the
  physical Echo prototype. They show the live ready screen, board in its printed
  carrier, salvaged speaker, battery cradle, and cable route. Publication copies
  are cropped and re-encoded without EXIF or location metadata; unique QR/serial
  labels are covered in the rear assembly image. No hardware or screen content
  has been generated or composited. Original photographs are not distributed.
- `web-*.png` are browser captures of the production web UI served by
  `tools/preview_web.py` with fixed sample data. Detail images capture real
  panels/fieldsets. See [the web gallery](../WEB_UI.md) for the capture workflow.
- `voice-states.png`, `home-controls.png`, and `everyday-tools.png` are generated
  from the shared firmware C++ renderer with synthetic fixtures. They contain no
  screenshots of a user's network, accounts, keys, conversations, or home state.
- `round-intercom.png` uses the same firmware renderer for disabled, room-picker,
  incoming, outgoing, active and muted call states with fictional room names.
- `display-*.png`, `pi-spotify.png` and `pi-alerts.png` show the actual smart-display
  UI with synthetic state. They are captured by the checks listed in
  [package checks](../PACKAGE_CHECKS.md), without real cameras, calendars,
  microphones, speakers or household accounts.
- Enclosure renders live in `enclosure/crescent-v1/preview`. They depict exported
  geometry and reference electronics. They are separate from the prototype
  photographs above.

To refresh the screen galleries on Windows with MSVC C++ tools and Pillow:

```text
python tools/preview_firmware.py
python tools/readme_gallery.py
```

The first command also checks screen bounds and interaction state fixtures. Both
commands run silently without connecting to a board or home service. No physical
acceptance claim follows from rendering a fixture.
