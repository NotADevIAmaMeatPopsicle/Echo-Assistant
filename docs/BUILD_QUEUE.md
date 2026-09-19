# Echo complete-package build queue

Both builds stay private until explicitly approved for release. The Pi power/video connections
are working; continue the remaining software and hardware acceptance. The verified original
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
- [x] Pi push-to-talk/ALSA adapter and request-specific reply routing (software; simulated audio only).
- [ ] Pi hands-free wake, interruption and physical echo-control acceptance.
- [x] Pi pairing/install/rollback client bundle; installed and OS restart verified.
- [ ] Integrated software verification and refreshed screenshots/documentation.

## Hardware acceptance when the owner returns

- [x] Stable Pi power, HDMI at 1024 × 600, USB touch, owner visual check.
- [ ] Exact panel model and complete touch calibration.
- [ ] Decide/identify Pi microphone and speaker; physical mute/indicator wiring.
- [x] Deploy the current display software and restricted gateway; Pi pairing and restart recovery.
- [ ] Full power-off cold boot, extended network loss, and live revocation/re-enrollment.
- [ ] Quiet audio, wake/reply, interruption and feedback tests on each endpoint.
- [ ] Physical enclosure fit, thermal behavior and final assembly instructions.

## External-service acceptance

Calendar accounts and camera services need actual configured integrations. Calls,
commercial video, and proprietary casting depend on supported third-party services;
do not present a placeholder as a working integration. Expose clear availability
and configuration states, and record any unsupported service explicitly.

## Software checkpoint

The current private branch has 79 passing focused tests across the new display
features and related existing home/timer paths. Silent browser checks pass for
reminders, lists, notifications, calendar selection, shared photo upload/delete,
and desktop/phone layout. No live home devices or audio were used in these tests.

The Pi is installed, paired and running Echo over Wi-Fi at 1024 × 600. The host
runs the reviewed display additions, with private credentials/settings and legacy
identity modules preserved. The Pi has restricted display access; its requests to
owner settings and display administration were rejected. Its kiosk and bridge
returned after an OS restart. The original card image and kiosk script remain
available for rollback.

The Echo workspace now has a blue-green ring icon, status/settings at left and a
shared typed/spoken conversation with microphone control at right. Browser checks
cover that layout, retained messages, simulated recording, delayed permission
cancellation, and phone width. None used physical audio or home actions.

Next: daily briefing/calendar creation and remaining household integrations.
Pi hands-free wake and acoustic acceptance need an identified microphone and
speaker. No Pi wake-word or physical audio acceptance claim is made.
