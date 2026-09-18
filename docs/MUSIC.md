# Spotify Connect

The receiver is based on pinned librespot 0.8.0 with a bounded event/control patch.
It requires Spotify Premium and access to Spotify's service. It is not Chromecast
or a Bluetooth A2DP receiver; ESP32-S3 does not provide Bluetooth Classic A2DP.

Use `tools/build_receiver.py` with Rust 1.90.0, or build the Linux image. Follow
the script's pinned source/checksum requirements. Copy `config/music.example.json`
to `local/music.json` and configure the receiver/interface for your network.
Start the host, open Spotify, select the receiver and start a track.

Discovery must reach your LAN. Docker Desktop may require the optional Windows
discovery helper in the deployment guide. Firewall changes are explicit:
`tools/enable_spotify_firewall.ps1` requires `ECHO_LAN_SUBNET` instead of assuming
a home subnet. Do not expose discovery or the receiver on the public internet.

The device supports playback controls and wake interruption with resume. Longer
playback endurance, room-distance wake accuracy and sound quality remain physical
acceptance work. The software does not claim a successful playback merely because
Spotify is authenticated. Start hardware playback at a low volume.
