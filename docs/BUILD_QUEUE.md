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
- [x] Pi local wake, cue/capture/replies, software mute and request interruption (software; installed disabled).
- [ ] Physical Pi wake and echo-control acceptance, including playback and spoken interruption with the chosen microphone.
- [x] Pi Spotify receiver, direct ALSA playback, output attenuation and endpoint-specific naming (software; real Spotify/audio acceptance pending).
- [x] Pi alarm/reminder chimes, saved destination routing and visible snooze/dismiss controls (software; physical audio pending).
- [x] Pi pairing/install/rollback client bundle; installed and OS restart verified.
- [x] Pi display visual polish: bundled typography, smooth status ring, contrast and touch spacing; deployed with dedicated kiosk sizing. Owner visual acceptance of this pass remains open.
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

Next: owner visual acceptance of the polish pass, then audio hardware acceptance
when the Pi microphone and speaker are attached.
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

Physical Pi wake and acoustic acceptance need an identified microphone and
speaker. Software coverage does not establish physical audio performance.

Pi timers, scheduled reminders and audible household messages now retain their
creating endpoint. Native Pi chimes, quiet hours, playback receipts and snooze
controls are implemented. See [Pi alerts](PI_ALERTS.md). Local wake software and the requested display visual polish are implemented. Physical microphone/speaker acceptance remains separate.

Display sharpness baseline: the connected panel advertises 1024 × 600 as its
preferred HDMI timing and X11 is using that mode. Chromium is in kiosk mode.
The dedicated kiosk now explicitly uses scale factor 1 and active monitor bounds.
A higher accepted input mode does not establish a higher native panel resolution.

The native Pi wake listener and pinned Vosk runtime are installed with listening
disabled and software mute on. A synthetic Linux pipe check exercised the cue,
command capture, reply attenuation and mute cleanup. Silent browser checks cover
native state, conversation, Talk/Send/Stop and stale-adapter handling. See
[Pi voice](PI_VOICE.md) for setup and the explicit echo-cancelled input requirement.

The first Pi polish pass is deployed: locally served Manrope, larger text and
controls, stronger blue/mint contrast, a fixed four-pixel ring with an animated
underglow, and X11 kiosk bounds that remove the default ten-pixel frame. Six
synthetic gallery images were refreshed; native-state and phone layouts were
checked. The live Pi capture confirms the new font and positioning. See
[Display design](DISPLAY_DESIGN.md) for the remaining one-pixel Chromium inset
and physical-acceptance limits. No audio or home actions were used.
