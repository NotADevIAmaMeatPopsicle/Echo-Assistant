# Local setup

The best-tested local host is Windows with 64-bit Python 3.13. Python 3.13's
OpenSSL PSK support is required for paired Wi-Fi. USB-only operation can use
Python 3.12–3.14 with compatible dependency wheels. Optional neural speech runs
in a separate environment.

1. Clone the repository and open PowerShell in its directory.
2. Create `.venv`: `py -3.13 -m venv .venv`.
3. Run `./tools/setup.ps1`. This installs the pinned host dependencies and Vosk
   model inside the checkout. `-Echo` optionally adds local echo cancellation
   using an existing Python 3.13 installation.
4. Follow [hardware setup](HARDWARE.md). For USB ownership, set
   `$env:ECHO_DEVICE_MAC` to the MAC confirmed by esptool. No maintainer board
   identity is built into the public source.
5. Run `./tools/run.ps1 start`, then `./.venv/Scripts/python.exe tools/open_ui.py`.
6. In Settings choose your conversation provider, model, endpoint where applicable
   and API key. Leave the provider disabled to use the offline built-in functions.

The browser launcher signs in using a short-lived, single-use ticket. The long-lived
device credential is never placed in the URL. Settings use Windows DPAPI locally;
the Linux container uses a separately provisioned storage key. Do not copy one
user's encrypted store to a different account and expect it to decrypt.

`./tools/run.ps1 status` reports health; `./tools/run.ps1 stop` stops the selected
host. After migration these commands operate the remote host, so closing a local
browser is different from stopping the selected services.

For neural speech, inspect `config/tts-models.json`, then use
`tools/download_tts_models.py --help` and `tools/setup_tts.ps1`. Downloads are explicit;
weights are not in Git. Retain downloaded voice/model attribution. Windows SAPI
is available without a neural model download. For Linux speech use the pinned
Docker build described in [deployment](DEPLOYMENT.md).

Environment variables can be set per terminal; no system-wide PATH, coding-agent
configuration or global Python installation is changed by the local setup script.
