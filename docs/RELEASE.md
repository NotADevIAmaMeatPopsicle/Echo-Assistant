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

## Public source update, 18 September 2026

- Portable Linux Whisper worker availability, offline execution, and pinned CPU
  dependencies. Model import adds optional Whisper files without requiring them
  for Vosk-only installations or recopying complete directories.
- Room-light requests resolve all controllable room members before acting.
- Checksum-pinned alternate Hermes WebUI plus the retained native dashboard.
- Optional exact-device Tailscale HTTPS gateway, access checks, and setup guide.
- USB Wi-Fi pairing through an explicitly selected remote Windows computer.
- Crescent v1 printable enclosure package, editable source, fit kit, M7
  orientations, illustrated assembly guide, and original digital-check records.
- README galleries of 18 firmware screens generated with synthetic data.
- Publication guard now includes untracked files in its pre-staging check, with
  regression coverage for both worktree and staged-byte inspection.

The host suite passed locally (325 tests, seven skips), with five gateway checks
and two publication-guard checks passing in a separate isolated environment.
The firmware built successfully and the native scene renderer passed its bounds
and interaction checks. No board was flashed, audio played, or home device
operated for this publication. Enclosure physical acceptance remains open.

The enclosure's vendor STEP, local configuration, credentials, node allowlist,
personal screenshots, and live runtime data are excluded. `SHA256SUMS.json` in
the enclosure folder describes the sanitized public package; the original
`verification.json` is a digital-check record, not a physical fit certificate.

## Physical prototype gallery

The README and assembly guide now include publication copies of three prototype
photographs: the powered display and speaker stand, rear board detail, and cable
route with battery cradle. These document an assembled print and a working
display. They do not establish battery runtime, acoustic performance, durability,
or repeatable fit of every released mounting option. Photo metadata is removed
and unique QR/serial labels are obscured; original photos remain private.
