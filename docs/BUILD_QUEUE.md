# Echo complete-package build queue

Both builds stay private until explicitly approved for release. Continue software
work while the owner resolves Pi power/video connections. The verified original
card backup is separate from Git; reuse of that card is authorized.

## Active software work

- [x] Recurring alarms, reminders, snooze, quiet hours, restart/DST behavior (software).
- [x] Voice/text list commands; list editing and ordering (software).
- [x] Detailed lights, climate modes and speaker playback controls (software; simulated devices only).
- [x] Persistent, revocable display pairing and unattended Pi loopback bridge (software).
- [x] Opt-in Home Assistant calendar agenda (read-only software).
- [ ] Daily briefing composition and calendar event creation.
- [x] Camera discovery and opt-in refreshing snapshots (software).
- [ ] Full-motion camera streams and doorbell event cards.
- [x] Encrypted shared photo albums and supported local/radio media playback (software).
- [x] Persistent notification inbox and opt-in announcements on the existing audio endpoint.
- [ ] Per-room announcement routing and intercom.
- [ ] Pi audio adapter and endpoint routing, with simulated transport tests.
- [x] Pi pairing/install/rollback client bundle (software; hardware installation pending).
- [ ] Integrated software verification and refreshed screenshots/documentation.

## Hardware acceptance when the owner returns

- [ ] Stable Pi power, actual panel identification, video and touch mapping.
- [ ] Decide/identify Pi microphone and speaker; physical mute/indicator wiring.
- [ ] Deploy the completed software, verify cold boot/reconnection and revocation.
- [ ] Quiet audio, wake/reply, interruption and feedback tests on each endpoint.
- [ ] Physical enclosure fit, thermal behavior and final assembly instructions.

## External-service acceptance

Calendar accounts and camera services need actual configured integrations. Calls,
commercial video, and proprietary casting depend on supported third-party services;
do not present a placeholder as a working integration. Expose clear availability
and configuration states, and record any unsupported service explicitly.

## Software checkpoint

The current private branch has 73 passing focused tests across the new display
features and related existing home/timer paths. Silent browser checks pass for
reminders, lists, notifications, calendar selection, shared photo upload/delete,
and desktop/phone layout. No live home devices or audio were used in these tests.

The Pi is reachable over Wi-Fi with healthy power. HDMI and microphone detection
remain open. Before pairing, deploy the backend additions and updated HTTPS
gateway. Add the Pi as a `display`-role peer, preserving owner access for the
existing selected machines. The new source must be reconciled with the private
instance's earlier naming/configuration; do not blindly copy the sanitized tree.

Next software implementation: a Pi capture/playback adapter using the paired
endpoint identity, with bounded audio, cancellation, and no routing to the round
speaker by default. Existing round wake/audio transport stays separate.
