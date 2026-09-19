# Echo complete-package build queue

Both builds stay private until explicitly approved for release. The Pi power/video connections
are working; continue the remaining software and hardware acceptance. The verified original
card backup is separate from Git; reuse of that card is authorized.

## Build direction

The Pi smart display uses its **own attached microphone and speaker**. It must not
require the round Echo speaker for voice, replies, music or alarms. The shared
host can still run the assistant and speech models. Other endpoints are optional
build choices or additional rooms, never an automatic audio fallback.

Prioritize the Pi audio path before extending round intercom. See
[build options](BUILD_OPTIONS.md) for the supported and planned configurations.

## Active software work

- [x] Recurring alarms, reminders, snooze, quiet hours, restart/DST behavior (software).
- [x] Voice/text list commands; list editing and ordering (software).
- [x] Detailed lights, climate modes and speaker playback controls (software; simulated devices only).
- [x] Persistent, revocable display pairing and unattended Pi loopback bridge (software).
- [x] Opt-in Home Assistant calendar agenda (read-only software).
- [x] Daily briefing composition, spoken/typed briefing requests and calendar event creation forms (software; actual calendar writes untested).
- [x] Camera discovery and opt-in refreshing snapshots (software).
- [x] Live MJPEG camera streams and persistent silent doorbell event cards (software; real camera/doorbell acceptance pending).
- [x] Encrypted shared photo albums and supported local/radio media playback (software).
- [x] Rich Spotify now-playing display: artwork, metadata, seeking, shuffle/repeat, input level and home-speaker controls (software; live listening acceptance pending).
- [x] Persistent notification inbox and opt-in announcements on the existing audio endpoint.
- [x] Per-room announcement routing, opt-in display/round receivers and delivery receipts (software; physical listening pending).
- [ ] Two-way intercom between room endpoints.
- [x] Pi push-to-talk/ALSA adapter and request-specific reply routing (software; simulated audio only).
- [ ] Pi hands-free wake, interruption and physical echo-control acceptance.
- [x] Pi Spotify receiver, direct ALSA playback, output attenuation and endpoint-specific naming (software; real Spotify/audio acceptance pending).
- [ ] Pi alarm/reminder sound routing without a round speaker; visible timers already work.
- [x] Pi pairing/install/rollback client bundle; installed and OS restart verified.
- [ ] Integrated software verification and refreshed screenshots/documentation.

## Hardware acceptance when the owner returns

- [x] Stable Pi power, HDMI at 1024 × 600, USB touch, owner visual check.
- [ ] Exact panel model and complete touch calibration.
- [ ] Identify and configure the microphone and speaker to be attached to the Pi; physical mute/indicator wiring.
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

My day now includes a local daily briefing, explicit calendar creation permissions,
and timed/all-day event forms. Seven focused Python tests cover calendar dispatch,
restart-safe duplicate protection, clock changes, permissions and local briefing
composition; the related source and display-voice checks also pass. Silent browser
checks cover the form and phone layout. No real calendar events were created.

Next: Pi audio independence: local wake/capture/replies and alarm
routing, then hardware acceptance when its microphone and speaker are attached.
The round intercom adapter remains planned as an optional endpoint.

The host and paired-display call UI
now support answered live audio, local microphone mute, hang-up and connection-loss
cleanup. Synthetic API, worklet and browser checks pass. Calls are off by default;
round firmware/adapter work and physical audio acceptance remain open.

Room announcements now include room assignments, explicit
destination selection, quiet hours, five-minute expiry, cancellation, protected
delivery history, and receiver-reported playback. Twenty-three focused Python
checks cover the new routing and existing timer/display-auth paths; silent browser
checks cover sending and receiving. See [Room audio](ROOM_AUDIO.md).

Camera/doorbell software now passes
22 focused checks together with calendar and Pi bridge coverage; silent browser
checks verify moving frames, source selection and event-to-camera navigation.
The current Home Assistant installation has no camera entities, so physical
camera and doorbell acceptance is still open.
Pi Spotify software now includes a separately named receiver, explicit ALSA output,
2% initial level, current-track controls and pause-before-microphone coordination.
The ARM64 binary starts on the Pi; Linux pipe and silent UI checks pass. It is
installed disabled until an output is chosen. See [Pi Spotify](PI_SPOTIFY.md).

Pi hands-free wake and acoustic acceptance need an identified microphone and
speaker. No Pi wake-word or physical audio acceptance claim is made.
