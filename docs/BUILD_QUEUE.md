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
- [x] Answered two-way intercom for paired displays and the round speaker (software; round firmware installation and physical audio acceptance pending).
- [x] Pi push-to-talk/ALSA adapter and request-specific reply routing (software; simulated audio only).
- [x] Pi local wake, cue/capture/replies, software mute and request interruption (software; USB headset listener configured).
- [ ] Physical Pi wake and echo-control acceptance, including playback and spoken interruption with the chosen microphone.
- [x] Pi Spotify receiver, ALSA playback, output attenuation and endpoint-specific naming (initial headset playback owner-confirmed; shared-output listening and session recovery remain acceptance).
- [x] Pi alarm/reminder chimes, saved destination routing and visible snooze/dismiss controls (software; physical audio pending).
- [x] Pi pairing/install/rollback client bundle; installed and OS restart verified.
- [x] Pi display visual polish: bundled typography, smooth status ring, contrast and touch spacing; deployed with dedicated kiosk sizing. Owner visual acceptance of this pass remains open.
- [x] Home tile selection and saved positions, Music tile with artwork/control, and horizontal page swipes that leave keyboard/control gestures intact (software).
- [x] Native Pi wake recognition during Spotify, optional 80% music ducking and shared-output setup (software; live wake/cue/restore acceptance pending).
- [x] Integrated software verification, fresh Docker build, repeatable browser suite, and refreshed screenshots/documentation. Physical and external-service acceptance below remains open.

## Hardware acceptance when the owner returns

- [x] Stable Pi power, HDMI at 1024 × 600, USB touch, owner visual check.
- [ ] Exact panel model and complete touch calibration.
- [ ] Identify and configure the microphone and speaker to be attached to the Pi; physical mute/indicator wiring.
- [x] Deploy the current display software and restricted gateway; Pi pairing and restart recovery.
- [x] Live access revocation and re-enrollment through a temporary Pi bridge; primary pairing preserved.
- [x] Recovery after a 90-second loss of the Pi's Echo connection, with the original pairing retained.
- [ ] Full power-off cold boot and recovery after Wi-Fi/router restart.
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
The optional round intercom adapter and firmware controls are implemented; see
[Round intercom](ROUND_INTERCOM.md). They do not replace the Pi's own audio path.

The host and paired-display call UI
now support answered live audio, local microphone mute, hang-up and connection-loss
cleanup. Synthetic API, worklet and browser checks pass. Calls are off by default;
round firmware installation and physical audio acceptance remain open.

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

Round intercom now has opt-in room selection, answer/decline, local mute and
hang-up, contextual physical buttons, and a bounded duplex host adapter. Consent
is scoped to a call and microphone forwarding waits for the firmware's capture
acknowledgement. Wake recognition pauses during calls. Thirty-seven focused
Python checks, shared firmware layout/consent checks and the ESP32 build pass.
The matching host support is deployed with calls disabled and private settings
preserved. The round board is currently absent from USB; no flash or acoustic
test was performed. The compiled firmware and install notes are ready for its
return. The Pi bridge remains connected and serves the polished display.

## Complete-package software checkpoint

The full Windows host suite completed **431 tests with seven platform-specific
skips**. A fresh Docker image built from the tracked source, including the native
audio dependencies. In an isolated Linux container with no network or devices,
36 Pi/storage/supervisor/native-echo tests and the synthetic wake/reply and
Spotify output pipelines passed. Twelve browser flows passed against separate
temporary previews; microphone and intercom worklet checks also passed. These
results cover software behavior, not real sound, external accounts or physical
assembly. See [repeatable package checks](PACKAGE_CHECKS.md).

The setup path now supports a Pi-only Windows host without starting the round
listener. Docker context generation excludes ignored private files and preserves
the previous generated context separately. The round Docker override explicitly
passes the verified board identity into its container. Music controls disable
immediately when switching to an unavailable receiver. The README presents both
builds, their independent audio paths and their setup guides.

The Pi now has a USB headset selected for microphone and playback. Spotify output
through the headset has owner confirmation. Wake accuracy, microphone gain,
cue/reply audibility and music ducking still need acoustic acceptance. This does
not establish far-field performance for the final speaker/microphone assembly.

A temporary bridge using the installed Pi client completed live enrollment,
revocation and fresh enrollment against the running host. Revocation denied both
bridge and direct credential access; the replacement credential restored scoped
display access while the old credential remained denied. Owner settings and
display administration stayed inaccessible. The private gateway also rejected
cookie-only requests as intended. The primary kiosk pairing was unchanged and
the temporary enrollments were removed. This does not establish cold-boot or
extended network-outage recovery, and exercised no audio or home devices.

The primary Pi subsequently recovered from a **90-second Echo endpoint outage**.
A temporary packet-drop rule targeted only the configured Echo HTTPS destination;
a separate automatic cleanup timer was armed before the rule was installed.
The live screen showed “Host unreachable · retrying” and disabled sending.
After removing the rule, the original bridge session returned successfully with
the pairing file unchanged and all prior firewall tables preserved. No audio,
home commands, browser reload or fresh pairing was used. This covers loss of
the Echo connection; physical power cycling and Wi-Fi/router restart remain open.

That live check exposed a stale speech-availability caption after connectivity
returned. The display now clears automatic service/microphone warnings when
availability recovers, while retaining cancellation and request-result messages.
The focused silent browser check covers service recovery, microphone removal
and return, and delayed permission cancellation without opening an audio device.
