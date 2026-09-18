# Rebuild the Crescent models

Python 3.12 was used. Create an isolated environment, install requirements.txt, then run these scripts in order:

1. python build_print_model.py
2. python verify_model.py
3. python prepare_m7.py

The generator writes into the package directory containing source/. Existing generated files there will be replaced. Copy the package before experimenting with changes. Editable dimensions and functions are in build_print_model.py; the STLs are Boolean solids generated with Manifold, not parametric STEP models.

Verification requires the original Waveshare STEP, which is not redistributed in this package. Download the ESP32-S3-Touch-AMOLED-1.75 board STEP from the [Waveshare documentation](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.75) and set the WAVESHARE_STEP environment variable to its absolute path. No machine-specific fallback is used. The source CAD's solid ordering matters to the two button contact checks, so use that exact board file.

The generator also creates an assembly-reference/ directory for CAD placement and diagnostics. It contains raw assembly-coordinate parts, not additional slicer parts. Use STL/ or M7-oriented/ for printing. Source changes are not automatically physically validated.

The generator and original enclosure designs are distributed under this repository's GPL-3.0-or-later license. Vendor board geometry is a dimensional reference and is not included. `verification.json` records the original CAD checks, not a physical print acceptance.
