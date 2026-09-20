# Echo complete-package build queue

Both builds stay private until explicitly approved for release. The Pi power/video connections
are working; continue the remaining software and hardware acceptance. The verified original
card backup is separate from Git; reuse of that card is authorized.

## Build direction

**Touch entry checkpoint:** the shared text keyboard is deployed to the host and
served by the Pi bridge. Lists, notes, calendar drafts and display text settings
now support tap entry without an external keyboard. Three focused synthetic
browser flows passed, including existing chat swipe typing and calendar creation.
The Pi kiosk restarted successfully with matching asset hashes; pairing and
private settings were preserved, the listener stayed armed, and no sound played.
Physical touch acceptance of these added forms remains separate.

The Pi smart display uses its **own attached microphone and speaker**. It must not
require the round Echo speaker for voice, replies, music or alarms. The shared
host can still run the assistant and speech models. Other endpoints are optional
build choices or additional rooms, never an automatic audio fallback.

Prioritize the Pi audio path before extending round intercom. See
[build options](BUILD_OPTIONS.md) for the supported and planned configurations.

## Active software work

**Browser calling checkpoint:** Deck and browser displays now have optional
LiveKit voice/video calls with owner configuration, encrypted provider credentials,
explicit Household-display grants, two-minute one-use codes, quiet 2% playback,
microphone mute, opt-in camera and hang-up. Calls coordinate Pi audio focus and
screen wake; cancellation or lost access closes local tracks. Guest/Personal
profiles cannot call. The existing private UI/network boundary is unchanged.
Forty-one focused Python checks and two silent browser flows pass. A digest-pinned
LiveKit 1.13.7 container accepted real room creation, a scoped participant
WebSocket handshake, and deletion while denying participant admin actions.
It had no published ports and sent no media. Real provider provisioning,
Cloud failover and physical call quality remain open. See [Calling](CALLING.md).
The private host update is deployed, and the Pi has verified the new assets and
reloaded its kiosk. Calling stays disabled. Pairing, account/source settings and
Pi private files were preserved; voice remains armed at 2%, Spotify discoverable,
and no physical audio or home actions were used. Thirty related checks also pass
inside the isolated Linux host image.

**Portable recovery checkpoint:** backup creation can use a privately entered
passphrase, and existing archives can be converted locally without replacing
their originals. Portable manifests use scrypt and authenticated encryption;
photos remain encrypted. Inspect/restore auto-detect protection, reject incorrect
passphrases before host changes, and retain Windows-protected archive support.
Seventeen focused checks cover encrypted round trips, corruption, source preservation
and private terminal input. A portable backup requires the owner to retain its
passphrase separately; existing Windows backups are not converted automatically.
The portable rehearsal opened a Windows-created archive inside Linux without
Windows keys, then restored fresh API/Hermes containers and a fresh data volume.
The tools are installed in the private checkout, and its existing Windows archive
still verifies. No production data was restored and no audio was used.

**Windows/Hermes recovery checkpoint:** the actual Windows recovery helper and
a temporary Scheduled Task recovered both services after container restart.
A DPAPI archive then restored into fresh containers and a fresh data volume,
preserving synthetic pairing, notes, photos, room policy and calendar receipts;
Hermes configuration and authentication were verified. A stale host home-access
policy is now replaced from the archive. Twelve focused checks also pass.
No production service, model call or audio was used in the rehearsal. The portable
checkpoint above adds archives independent of the original Windows DPAPI keys;
fresh-OS provisioning remains open.

**Personal calendar voice checkpoint:** Deck and Mini personal sessions now answer
agenda requests for today, tomorrow and the next seven days from approved sources.
The local summary uses account/display/global grant intersections, excludes
household lists and reminders, and does not send events to a model or search.
Cancelled, locked and changed-access requests discard their result; partial
calendar failures are reported explicitly. The host update is deployed with
private settings, accounts and pairing preserved. Twenty focused tests pass on Windows
and isolated Linux, including existing personal and Mini sign-in paths. No real
calendar writes, home actions or audio were used. Personal provider sign-in and
physical spoken acceptance remain open.

**Mini personal sign-in checkpoint:** the private host now supports the same
personal accounts on Deck and Mini. Owner assignment requires connected firmware
0.19.0. Mini adds Settings → Me, a bounded account picker, masked eight-digit
keypad and Lock my session. Home cards and voice use effective account grants;
shared facts remain separate from household memory, and temporary conversations
remain separate for each login. API-owned sessions refresh asynchronously so the
host audio pump does not block on access reads. Stale access fails closed.

Sixty-five focused tests pass on Windows and isolated Linux. Native C++ checks
cover input bounds, clearing, timeouts, full-width revisions and circular rendering;
firmware 0.19.0 builds with a verified four-image bundle. Silent browser checks
cover the owner capability gate and assignment, plus existing Deck personal flows.
The host update is deployed privately, with pairing, grants and saved data preserved.
Deck's unchanged client remains armed at 2%, with Spotify discoverable and grouped
music ready. No sound or real home action was used. Mini firmware remains unflashed;
physical account/voice acceptance is open. See [Personal accounts](PERSONAL_ACCOUNTS.md).

**Personal account checkpoint:** the private host and current Pi bundle now support
owner-created accounts, explicit per-display assignment, an eight-digit touch
passcode, separate saved memory and personality, and a 15-minute personal session.
Personal conversations use the configured model directly; shared household Hermes
context and private household data remain excluded. Device/source grants intersect
with the display and global policy. Lockout persists, and old login requests cannot
write into a new account or return stale speech after synthesis.

Fifty focused tests pass on Windows and isolated Linux, including encrypted account
restore and a native listener account switch before playback. Silent browser flows
cover account creation, grants, keypad sign-in, memory, locking, existing Guest/Mini
editing and phone layout. The synthetic preview supports temporary accounts too.
The host and Pi update preserved private files and pairing; the listener returned
armed at 2%, Spotify remained discoverable, and no sound or home devices were used.
No real accounts were created. The later Mini checkpoint adds its sign-in software;
separate personal Hermes tools,
external account linking and physical account-use acceptance remain open. See
[Personal accounts](PERSONAL_ACCOUNTS.md).

**Mini access checkpoint:** encrypted Household/Guest profiles, selected home
cards, isolated conversation and optional local guest home voice commands are
implemented. Guest speaker selection does not change the household choice.
Queued requests retain their access revision; profile changes clear replies,
cards, drafts and calls. Guest mode blocks grouped music, household announcements,
calendar drafts, memory and Hermes tools. Existing settings remain Household.

Fifty-three focused tests pass on Windows and isolated Linux. The owner browser
flow covers firmware readiness, saving, cancellation, guest restrictions and
phone layout. Native C++ access checks and circular rendering pass; firmware
0.18.0 builds with a verified four-image bundle. The host update is deployed
privately. Mini firmware installation and physical guest acceptance remain open.
Pairing, private settings and source grants were preserved. The Deck serves the
matching owner UI, remains armed at 2%, and reports Spotify discovery and grouped
music readiness. No sound or home devices were used. See [Mini access](ROUND_ACCESS.md).

**Mini calendar checkpoint:** the private host now supports paginated draft review
and a separate Create confirmation on firmware 0.17.0. Full field previews include
UTC offsets, all-day bounds and repeat rules. Partial transfers, unresolved questions,
unsupported characters, stale confirmations and revoked grants cannot create an event.
Cancellation/expiry clears unsent drafts; music stays held during review.

Thirty-one focused checks pass on Windows; the corresponding Linux checks pass
with one Windows-only speech check skipped. The actual C++ state and circular
screen rendering pass, and firmware 0.17.0 builds with a verified four-image bundle.
The host deployment preserved settings, pairing and source grants. The Deck's
unchanged bundle remains armed at 2%, with Spotify discoverable. No real calendar
event, home device or audio was used. Mini firmware installation and physical
touch/creation acceptance remain open. See [Mini calendar review](ROUND_CALENDAR.md).

**Guest home voice checkpoint:** owner-enabled local guest commands are deployed
to the private host and current Pi bundle. Guests can name shared devices or room
lights for state, power, brightness, explicit-unit temperature and basic speaker
commands. The global and per-display grants intersect on every request; actions
also need current-message or owner wake permission. No device data goes to the
guest model, and no profile was opted in during deployment.

Thirty-eight focused checks pass on Windows and isolated Linux, including real
API authorization with simulated devices, cancellation, ambiguous names, revoked
access, unsupported values and spoken request routing. The browser flow covers
the optional grant and per-message consent. Pi settings/pairing were preserved,
its listener is armed at 2%, Spotify is discoverable and echo cancellation remains
active. No real home device or audio was used. See [Display access](DISPLAY_ACCESS.md).

**Calendar occurrence checkpoint:** the private host and Pi browser now support
explicit occurrence/following edits and occurrence/following/whole-series deletion.
The existing repeat rule stays intact; counted or unknown series keep their start
fixed to avoid a confirmed upstream event-loss bug. Unsupported master edits and
invitations remain in the calendar app. Owner write grants were preserved; no real
calendar event was changed. The Pi serves matching assets and its listener remains
armed at 2%, with pairing and private files unchanged and no sound played.

Forty-five focused checks pass on Windows and isolated Linux. Two synthetic browser
flows cover existing forms, scope selection, cancellation, deletion confirmation,
fixed-start fields, Guest restrictions and phone layout. An in-memory check using
Home Assistant's actual calendar library confirms the supported operations preserve
remaining occurrences. The privacy guard reports no findings. See [Calendars](CALENDARS.md).

**Mini music integration checkpoint:** the private host now includes an opt-in
Sendspin receiver, owner name/volume/calibration settings, connection/clock status,
metadata and shared-output controls for Mini buttons and basic voice music intents.
Cues, replies, alarms, calls and Spotify take local priority; buffered group audio
is discarded while held. The receiver is disabled pending matching firmware and
physical acceptance. Private settings and pairing were preserved during deployment.
The Pi serves the updated assets, its listener remains armed at 2%, and no sound
was played. The Mini is not registered as a grouped player yet.

Forty-six focused Windows tests plus 26 existing voice/recognition checks pass;
37 focused checks pass in an isolated Linux container. These include the actual
pinned SDK against a synthetic server and fake firmware wire, with clock sync,
PCM format, gain, clear/disconnect, redirects and owner revocation. The browser
check covers owner settings, grouping, library/queue selection and Guest access.
The optional host runtime is wheel-hash pinned; no live audio was used.

Firmware 0.16.0 and a host sender support
timestamped 48 kHz PCM over the existing board transport. The firmware timing
core passed its silent native C++ check; eleven Python timing/legacy-sender tests
passed, and the ESP32 build plus four-image bundle verification passed. The
bundle is local only; no board was flashed and no audio played. Physical timing and latency
calibration remain unverified. See [Mini grouped music](ROUND_GROUP_MUSIC.md).

**Grouped-music player checkpoint:** Music Assistant 2.10.4 runs privately without
published ports. The native Pi client is installed, registered as Echo Deck and
clock-synchronized through the existing authenticated Echo gateway. No Music
Assistant token is stored on the Pi. Its local output ceiling is 2%, voice ducking
reduces amplitude by 80%, and voice/alerts or local Spotify can silence only this
endpoint. An in-memory check of the pinned audio engine verified those levels;
no audio chunks were sent during the connection check. The existing listener
remains armed and Spotify remains available. Mini firmware installation and
physical multi-speaker playback/timing remain open.

The Together page now also has provider browsing, track/album/playlist/radio search,
queue pages and explicit selection to play on the chosen output. Provider setup
remains in Music Assistant; existing Spotify Connect credentials are not imported.
The update is deployed to the private host and Pi browser. Thirty-eight focused
tests pass across Windows and isolated Linux checks; the synthetic browser flow
covers library/search/queue selection, grouping, keyboard entry, native settings,
Guest restrictions and phone layout. Pi browsing and queue reads returned
successfully, matching assets were served after the kiosk refresh, and pairing
and private settings were preserved. No real playback or home actions were used.
See [Grouped music](GROUP_MUSIC.md).

**Calendar management checkpoint:** event details, single-event editing/deletion
and bounded recurring creation are deployed to the private host and Pi browser.
Changes to existing events require a new owner grant, which remains off for all
current calendars. Before changes, the backend checks the current event and
preserves durable retry receipts. The Windows suite passed 483 tests with seven
platform-specific skips; 34 focused Linux tests passed. Browser checks cover
calendar changes, repeat forms, existing drafts and guest restrictions. The Pi
serves matching assets and remains armed at 2%; settings and pairing were preserved.
No real calendar events, home-device state or audio were changed. The occurrence
checkpoint above extends this work; invitations remain open. Mini review software
is covered by its newer checkpoint above.

**Display access checkpoint:** owner-assigned Household/Guest profiles are deployed
to the private host and current Pi client. Guests receive only selected devices
and read-only sources, with separate temporary conversation and no household
memory or Hermes tools. The Pi clears stale replies after access changes. Existing
Household pairings and private settings were preserved; the listener is armed,
Spotify is discoverable, and the echo-cancellation service remains active.
The full Windows suite passed 476 tests with seven platform-specific skips;
64 focused Linux tests and the synthetic voice pipeline passed. Browser checks
cover profile editing, guest layout and existing home/calendar/keyboard flows.
No sound or home actions were used. The later personal-account checkpoint adds
Deck sign-in and separate memory; local guest
home commands are covered in the checkpoint above.

**Calendar drafting checkpoint:** model-assisted drafts now run on the private host
and the current Deck client. Both the event form and smart-display conversations
offer editable fields before explicit creation. Twenty-seven focused Windows
checks, thirteen Linux calendar checks and the synthetic native voice pipeline
passed. Browser checks cover form/chat drafts, timed/all-day submission, permissions
and phone layout. A synthetic Azure request and the live draft API returned event
fields; neither created calendar events or played sound. The update preserved
pairing and audio settings, and the Pi listener returned armed at 2%.

**Pi audio checkpoint:** the optional WebRTC echo-cancellation service is installed
on the Pi. The native recorder receives processed microphone frames, while
Spotify, replies, alerts and the kiosk select the same playback-reference output.
The listener is armed, Spotify is discoverable, and the existing hardware mixer
gain and 2% output setting are preserved. Module startup was also checked with
null audio devices. No test sound was played during this deployment. Actual
music/wake/cue, echo reduction and spoken interruption still need human acceptance;
the earlier headset playback confirmation predates this processing route.
The listener recovered fresh frames in under four seconds after an audio-service
restart. Nine focused configuration/bundle tests passed; this is not a cold-boot
or physical listening result.
Setup, privacy boundaries and rollback are in [Pi echo cancellation](PI_ECHO_AUDIO.md).

**Recovery checkpoint:** archive version 2 now includes shared encrypted photos,
room-audio settings, doorbell state and calendar dispatch receipts. A fresh
network-isolated API, container restart and restore into a new volume passed,
including persistent pairing and owner/display separation. Eight focused recovery
tests passed on Windows and Linux. Production data and running services were not
changed by that rehearsal. Full Windows/Hermes disaster recovery remains open.

**Current handoff:** Deck screen protection, optional presence wake and in-memory
voice troubleshooting are deployed. Known generated speech passes both wake phrases and the live host
transcription/assistant path without playback. This does not verify room pickup:
the observed USB-headset input is quiet and no owner wake event was observed in
the latest diagnostic window. Use the input meter and stage history during the
next real attempt. Mini firmware 0.18.0 includes Screen settings, idle OLED
protection, calendar review and access profiles; installation remains pending.
Presence wake now supports owner-approved Home Assistant motion/occupancy sensors
and per-display selection. No qualifying sensors are currently exposed by Home
Assistant, so physical presence-wake acceptance remains open.
One quiet 2% headphone-to-microphone wake check produced no detected wake; its
question was therefore not played. This does not establish a microphone fault
or human-speech pickup. The next test needs someone speaking near the microphone.

- [x] Recurring alarms, reminders, snooze, quiet hours, restart/DST behavior (software).
- [x] Voice/text list commands; list editing and ordering (software).
- [x] Detailed lights, climate modes and speaker playback controls (software; simulated devices only).
- [x] Persistent, revocable display pairing and unattended Pi loopback bridge (software).
- [x] Opt-in Home Assistant calendar agenda (read-only software).
- [x] Daily briefing composition, spoken/typed briefing requests and calendar event creation forms (software; actual calendar writes untested).
- [x] Model-assisted calendar drafts from smart-display text/voice and the event form; explicit review, date validation and existing write grants (software; real calendar creation and Mini firmware acceptance remain open).
- [x] Camera discovery and opt-in refreshing snapshots (software).
- [x] Live MJPEG camera streams and persistent silent doorbell event cards (software; real camera/doorbell acceptance pending).
- [x] Encrypted shared photo albums and supported local/radio media playback (software).
- [x] Rich Spotify now-playing display: artwork, metadata, seeking, shuffle/repeat, input level and home-speaker controls (software; live listening acceptance pending).
- [x] Persistent notification inbox and opt-in announcements on the existing audio endpoint.
- [x] Per-room announcement routing, opt-in display/round receivers and delivery receipts (software; physical listening pending).
- [x] Answered two-way intercom for paired displays and the round speaker (software; round firmware installation and physical audio acceptance pending).
- [x] Pi push-to-talk/ALSA adapter and request-specific reply routing (software; simulated audio only).
- [x] Pi local wake, cue/capture/replies, software mute and request interruption (software; USB headset listener configured).
- [x] Optional Pi WebRTC echo cancellation and a shared playback reference for music, voice and kiosk audio (installed; acoustic performance unverified).
- [ ] Physical Pi wake and echo-control acceptance, including playback and spoken interruption with the chosen microphone.
- [x] Pi Spotify receiver, ALSA playback, output attenuation and endpoint-specific naming (initial headset playback owner-confirmed; shared-output listening and session recovery remain acceptance).
- [x] Pi alarm/reminder chimes, saved destination routing and visible snooze/dismiss controls (software; physical audio pending).
- [x] Pi pairing/install/rollback client bundle; installed and OS restart verified.
- [x] Complete saved-data recovery archive, legacy archive reading, photo integrity, room policy and calendar receipts; isolated API restart/restore verified with synthetic data.
- [x] Pi display visual polish: bundled typography, smooth status ring, contrast and touch spacing; deployed with dedicated kiosk sizing. Owner visual acceptance of this pass remains open.
- [x] Home tile selection and saved positions, Music tile with artwork/control, and horizontal page swipes that leave keyboard/control gestures intact (software).
- [x] Shared touchscreen keyboard for lists, notes, calendar drafts and display text settings, with modal focus, field navigation, local suggestions and explicit save actions (software; phone keyboards and browser date/number controls preserved).
- [x] Native Pi wake recognition during Spotify, optional 80% music ducking and shared-output setup (software; live wake/cue/restore acceptance pending).
- [x] Deck configurable idle dim/sleep and wake-only first touch; native HDMI Off/On reported by X11. Physical backlight/touch acceptance pending.
- [x] Opt-in Deck presence wake, owner source permissions, per-display sensor selection, stale/offline fallback and manual-sleep behavior (software; no physical sensor configured).
- [x] Pi input meter and bounded, volatile wake/capture/reply diagnostics; no recordings or ambient transcripts saved.
- [x] Mini OLED idle dim/dark settings, touch wake and audio-preserving screen state (compiled and rendered; firmware installation pending).
- [x] Integrated software verification, fresh Docker build, repeatable browser suite, and refreshed screenshots/documentation. Physical and external-service acceptance below remains open.

## Hardware acceptance when the owner returns

- [x] Stable Pi power, HDMI at 1024 × 600, USB touch, owner visual check.
- [ ] Exact panel model and complete touch calibration.
- [x] Provisional USB headset selected for Pi microphone/playback; Spotify playback owner-confirmed.
- [ ] Final microphone/speaker assembly and physical mute/indicator wiring.
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

## Remaining feature parity work

The completed software checkpoints above do not mean full Nest Hub/Echo Show
parity. Known gaps documented in the smart-display guide remain:

- [x] Supported single-event editing/deletion and bounded recurring creation, with separate owner permissions and explicit review (software; external calendar writes untested).
- [x] Explicit occurrence/following edits and occurrence/following/whole-series deletion, preserving repeat patterns (software; live provider writes untested).
- [x] Mini calendar draft review, explicit creation, cancellation and expiry (host deployed; firmware built, installation and physical acceptance pending).
- [ ] Calendar master-event editing, counted-series rescheduling and invitations.
- [ ] Synchronized grouped music across endpoints.
      Music Assistant connection, library/queue selection, shared-output permissions,
      the native Pi player, private stream transport and local voice coordination
      and the opt-in Mini host client are implemented. Mini firmware installation,
      actual provider playback and physical timing remain open; see [Grouped music](GROUP_MUSIC.md).
- [ ] External calling with a supported provider.
      LiveKit browser signalling, controls, permissions and provider setup software
      are implemented and tested with isolated signalling. Real provider setup
      and two-device media acceptance remain open; see [Calling](CALLING.md).
- [ ] Household/guest profiles and per-user/per-room source policies.
      Per-display Household/Guest profiles, selected home-device and read-only
      source grants, isolated guest conversation and opt-in local guest home
      voice commands and Mini profile software are implemented. Deck and Mini personal
      identities and separate memory/accounts are implemented. Separate personal
      Hermes tools and external accounts remain open. Mini installation and
      physical acceptance are pending. See [Display access](DISPLAY_ACCESS.md).
- [ ] Supported casting/commercial-video integrations, subject to provider access
      and licensing; current local media and Spotify do not establish those features.
- [ ] Full Windows host and Hermes disaster-recovery rehearsal.
      Same-account Windows task recovery and fresh-container/volume API/Hermes
      archive restoration are verified with synthetic data. Fresh Windows/Docker
      provisioning and model restoration remain open. Portable passphrase archives
      provide an alternative to Windows-account-bound backups; see [Deployment](DEPLOYMENT.md).

These are separate from the physical and live-service acceptance above. Do not
mark the overall goal complete while the required feature set remains open.

## Earlier software checkpoints

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

Next: observe a real Pi voice attempt using the new diagnostic meter/history,
then install the built Mini firmware when its USB connection is available.
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
initially installed disabled until an output was chosen; the current headset
receiver is enabled. See [Pi Spotify](PI_SPOTIFY.md).

Physical Pi wake and acoustic acceptance need an identified microphone and
speaker. Software coverage does not establish physical audio performance.

Pi timers, scheduled reminders and audible household messages now retain their
creating endpoint. Native Pi chimes, quiet hours, playback receipts and snooze
controls are implemented. See [Pi alerts](PI_ALERTS.md). Local wake software and the requested display visual polish are implemented. Physical microphone/speaker acceptance remains separate.

Display sharpness baseline: the connected panel advertises 1024 × 600 as its
preferred HDMI timing and X11 is using that mode. Chromium is in kiosk mode.
The dedicated kiosk now explicitly uses scale factor 1 and active monitor bounds.
A higher accepted input mode does not establish a higher native panel resolution.

The native Pi wake listener and pinned Vosk runtime were initially installed with
listening disabled and software mute on; listening is now enabled for the selected
USB headset. A synthetic Linux pipe check exercised the cue,
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

Deck screen comfort is installed: adjustable 2-minute dim / 10-minute sleep
defaults, a black sleep cover, wake-only first touch/key, and opt-in X11 HDMI
sleep. Voice requests and active calls/video keep the display awake; music alone
does not. Synthetic checks cover timers, persistence, validation and preventing
the wake tap from pressing a control underneath. The Pi reported DPMS Off and
On during a silent sleep/wake check, and its native microphone remained armed.
Physical backlight extinction and a real touch wake after idle remain unverified.
Presence wake is implemented using approved Home Assistant motion/occupancy sensors,
with explicit selection on each display. Ten focused Python checks and two silent
browser flows cover permission removal, bounded caching, unavailable sensors,
manual sleep, persistence and first-touch protection. No actual sensor is configured,
so physical presence wake remains unverified. Mini firmware does not inherit these
Deck settings.
