# Paired Wi-Fi

The board uses 2.4 GHz Wi-Fi and a paired TLS-PSK connection to its speech host.
USB can supply power after pairing; it is not required as the normal data path.
The host must remain running and reachable on the same trusted LAN.

Set `ECHO_DEVICE_MAC` to your verified board MAC, stop the bridge, and run:

```powershell
./.venv/Scripts/python.exe tools/pair_wifi.py --host YOUR_HOST_LAN_IP --port YOUR_PORT
```

The tool prompts for Wi-Fi credentials without printing the password and provisions
a randomly generated PSK. Private host state is written under ignored `local/`;
board credentials live in NVS. Keep full flash backups private because they may
contain that NVS state. Python 3.13+ with OpenSSL PSK support is required.

Pairing a different host is an explicit operation. See [deployment](DEPLOYMENT.md)
before migrating, because the board and the destination must agree on the host
address and pairing key. Do not forward the device listener to the public internet.

## Pair through USB on another computer

If the board is connected to a different Windows computer with OpenSSH, use
`tools/pair_remote_wifi.py --usb-host YOUR_SSH_ALIAS --port YOUR_COM_PORT --ssid YOUR_SSID`.
Set `ECHO_DEVICE_MAC` to the verified board identity first. The password is entered
at a hidden prompt; it and the existing TLS pairing travel over encrypted stdin.
The helper checks that the COM interface belongs to that USB board and that the
local pairing key matches the running server. Stop any serial monitor first.
It reuses the existing host pairing and does not enable pairing over Wi-Fi.
