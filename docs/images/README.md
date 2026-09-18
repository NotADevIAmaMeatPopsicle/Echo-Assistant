# Public illustrations

- `echo.svg` is the original illustrative hero artwork.
- `web-*.png` are browser captures of the production web UI served by
  `tools/preview_web.py` with fixed sample data. Detail images capture real
  panels/fieldsets. See [the web gallery](../WEB_UI.md) for the capture workflow.
- `voice-states.png`, `home-controls.png`, and `everyday-tools.png` are generated
  from the shared firmware C++ renderer with synthetic fixtures. They contain no
  screenshots of a user's network, accounts, keys, conversations, or home state.
- Enclosure renders live in `enclosure/crescent-v1/preview`. They depict exported
  geometry and reference electronics, not photographs of a completed print.

To refresh the screen galleries on Windows with MSVC C++ tools and Pillow:

```text
python tools/preview_firmware.py
python tools/readme_gallery.py
```

The first command also checks screen bounds and interaction state fixtures. Both
commands run silently without connecting to a board or home service. No physical
acceptance claim follows from rendering a fixture.
