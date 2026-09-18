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
