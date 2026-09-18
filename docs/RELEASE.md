# Alpha release status

Public package: **0.1.0-alpha.1**. Included host implementation: **0.26.0**;
firmware implementation: **0.13.0**. Wire-protocol identifiers retain `round-voice`
for compatibility; the project and repository are Echo Assistant.

Implemented: paired USB/Wi-Fi transport; board UI, swipe navigation and contextual
buttons; software mute; local speech; configurable conversation; Hermes tools;
Home Assistant inventory/control policy; explicit memory and routines; research;
Spotify receiver/control; host recovery archives and runtime status reporting.

Still requiring broader physical/fresh-install acceptance:

- Sustained Spotify playback, interruption/resume and room-distance wake accuracy.
- Every contextual physical button against a designated real target.
- Battery/charging with a compatible attached battery.
- New-user Windows/Docker setup, host reboot/outage recovery and a live restore.
- Provider options other than the exercised Azure configuration.

The release is source-only. No device backup, NVS state, model weights, personal
configuration, runtime database, authenticated image or pre-paired firmware is
distributed. Build firmware from source after configuring your own board.

Release checks include offline tests, source/privacy guards and a redacted
Gitleaks scan. These reduce publication risk; they are not a claim of a complete
security audit or production hardware certification.

## Publication checks

- 322 host tests completed successfully; 6 platform-dependent checks skipped.
- PlatformIO firmware build succeeded; no device was flashed for this release.
- The staged-source publication guard checked 565 files with no findings.
- Gitleaks 8.30.1 reported no secrets. A separate in-memory comparison against
  available private deployment credentials found no matches in staged source.
- Source links, deployment examples and original device/host identifiers were
  reviewed; runtime state and the original repository history were excluded.

GitHub CI repeats the host, firmware and secret checks on subsequent changes.
