# Remaining work: bounded tasks

This is the execution plan for the remaining items in [the build queue](BUILD_QUEUE.md).
Each task has a concrete deliverable and acceptance gate. Software completion does
not close an external-service or physical acceptance task. The repository remains
private. No release, push, firmware flash, sound playback or home-device action is
part of an agent's automated checks.

## Current task index

Each ID below has its own completion boundary in the dispatch or acceptance
tables. Software marked deployed still requires the separately listed provider
or hardware acceptance. Coordinator ownership includes integration and deployment.

| ID | Work item | Current state / owner |
| --- | --- | --- |
| ECHO-01 | Direct Google writes and whole-series editing | Software deployed; calendar lane |
| ECHO-02 | Following-only series editing | Software deployed; series lane |
| ECHO-03 | Reviewed invitations | Software deployed; invitation lane |
| ECHO-04 | Private Google accounts | Software deployed; account lane |
| ECHO-05 | Separate personal Hermes routing | Software deployed; agent lane |
| ECHO-06 | Grouped music | Provider and physical acceptance; coordinator |
| ECHO-07 | Voice/video calls | Private provider deployed and TCP verified; physical two-device acceptance open; coordinator |
| ECHO-08 | Phone music receiver | Adapter and distribution packages installed; disabled; module/phone/audio setup and playback open; media lane |
| ECHO-09 | Commercial video | Ordinary YouTube deployed; installed ARM64 Widevine loads successfully; provider choice/sign-in and real playback open; media lane |
| ECHO-10 | Replacement-host provisioning | Tooling implemented; recovery lane |
| ECHO-11 | Real Google account and calendar acceptance | Owner account configuration required; coordinator |
| ECHO-12 | Install prepared Mini firmware | Original backup and 0.19.0 bundle verified; connected board identity and installation pending; coordinator |
| ECHO-13 | Pi audio acceptance | Diagnostic fix deployed; selected USB audio hardware absent; coordinator |
| ECHO-14 | Mini audio acceptance | Depends on ECHO-12 and physical testing; coordinator |
| ECHO-15 | Panel and touch acceptance | Physical panel identification/calibration open; coordinator |
| ECHO-16 | Dim, off, touch and presence acceptance | Physical checks and selected presence sensor open; coordinator |
| ECHO-17 | Camera and doorbell acceptance | Selected live sources required; coordinator |
| ECHO-18 | Cold boot and router recovery | Stable hardware and controlled outage required; coordinator |
| ECHO-19 | Final enclosures and build guide | Final hardware/fit/thermal results required; coordinator |
| ECHO-20 | Fresh-machine recovery | Disposable replacement machine required; current host has no spare VM and insufficient free memory for a new Windows guest; recovery lane |
| ECHO-21 | Integrated package review | Depends on required tasks and explicit scope decisions; coordinator |
| ECHO-22 | Personal Hermes instances | No personal accounts configured; per-person provider/tool choices and separate provisioning open; agent lane |
| ECHO-23 | Host capacity and Docker recovery | Runtime recovered; permanent storage relocation remains open; coordinator |

## Integration contract

- The coordinator owns shared application wiring, deployment, queue updates and
  integration review. Workers own only the files identified below. Preserve existing
  changes; report any required change outside that boundary before editing it.
- Echo's API owns authorization and encrypted configuration. Google credentials,
  personal accounts and provider sessions must not reach browser storage or Git.
- Household, Guest and Personal access cannot expand through a new provider.
  Every request must retain its initiating identity and discard stale results.
- The Pi owns its microphone, speaker and music output. Mini is an independent
  endpoint. No automatic cross-device audio fallback or change to the 2% Pi volume.
- Provider features start disabled/unconfigured. Preparation must not imply actual
  account approval, successful media playback or a completed physical check.
- Workers deliver changed files, the precise interface, focused verification and
  remaining limitations. The coordinator reviews the combined diff before any
  deployment. No worker commits, stages, pushes or deploys shared changes.

## Dispatch wave 1

| ID | Task and completion criteria | Owner / files | Dependencies |
| --- | --- | --- | --- |
| ECHO-01 | Google create/edit/delete plus original-series review. Explicit optional write OAuth, separate Echo grants, provider ETag conflicts, durable duplicate protection; moving the whole series preserves its COUNT. Finish the existing local patch and focused API/UI checks. No invitations or following-only split in this task. | Calendar worker: `backend/google_calendar*.py`, `backend/calendar_events.py`, `backend/calendar_reference.py`, `backend/experience_api.py`, `backend/experiences.py`, `backend/display_auth.py`, `web/display/briefing.js`, `web/display/google-calendar.js`, related new tests/checks. | Read-only connector is deployed. Shared route changes must be reported for coordinator review. |
| ECHO-05 | Personal Hermes routing. Explicit owner configuration for a separate per-person agent endpoint; never reuse the household Hermes session/credentials by default. Account changes/expiry cancel or discard stale results. Personal memory and permissions remain isolated. Deliver actual integration and a focused fake-provider check. | Personal-agent worker: new `backend/member_hermes.py`, `backend/member_agent.py`, `backend/member_api.py`, `backend/members.py`, member UI/assets/tests and `docs/PERSONAL_ACCOUNTS.md`. Coordinator owns `backend/app.py` and backup-file registration. | Existing personal accounts and direct-model fallback. No live personal agent provisioned or external messages. |
| ECHO-10 | Replacement-host provisioning. Deliver an explicit preflight/bootstrap command and model-manifest restoration path for a fresh Windows/Docker host, with clear prerequisites and no secrets in generated artifacts. Default is inspect/plan; installation and production restore require an explicit invocation. | Recovery worker: new `tools/provision_host.py`, supporting new tools/tests, `docs/HOST_PROVISIONING.md`; report edits needed in existing recovery/deployment tools for coordinator integration. | Existing protected archives, Docker deployment and model import tooling. No changes to this host's installed software/configuration. |

### Wave 1 result

- **ECHO-01: software implemented and deployed to the private host.** Fifty-five
  focused calendar checks passed, including seventeen new cases, plus the silent
  master-review browser flow. Original dates, unchanged COUNT, provider conflicts,
  duplicate protection and access-lock ordering are covered. Real Google account
  and event acceptance remain ECHO-11; following-only splits and invitations stay
  in ECHO-02 and ECHO-03.
- **ECHO-05: software implemented and deployed to the private host.** Fourteen
  focused personal-agent checks and the existing account/agenda/Mini regressions
  passed, plus the new setup/opt-in and existing member browser flows. The owner
  must still provision and verify separate instances under ECHO-22.
- **ECHO-10: tooling implemented.** Provisioning/import checks and existing
  protected-recovery checks passed with one Windows symlink-creation permission
  skip; simulated reparse-point rejection passed. No real prerequisite install,
  import or restore was run. The fresh-machine rehearsal remains ECHO-20.

The combined calendar/personal-agent image passed 64 tests on isolated Linux.
The host update preserved settings, source grants and pairing. No real account,
home-device action or audio was used. The Pi was offline during post-deployment
verification, so its UI refresh and current physical status remain pending.
Deployment status does not close any hardware or live-service acceptance task.

## Dispatch wave 2

Wave 1 is committed as `6f770b1`. The coordinator owns all edits to existing shared
calendar/OAuth models, authorization lists, application registration and display
assets during this wave. Workers must send the required integration edits to the
coordinator, rather than changing another worker's interface in place.

| Task | Worker boundary and handoff contract | Completion boundary |
| --- | --- | --- |
| ECHO-02 | New `backend/google_calendar_series.py`, focused new series tests and `docs/GOOGLE_CALENDAR_SERIES.md`. Expose a following-change entry point accepting the existing Google writer adapter plus operation/reference/replacement/revision/request ID. Reuse its access lock, source policy and encrypted receipt store. Request precise core-writer/scope/UI changes from the coordinator. | Preserve earlier occurrences and the remaining COUNT through a reviewed following-only change; report partial remote outcomes and prevent blind retries. No invitations or change to other recurrence scopes. |
| ECHO-03 | New `backend/calendar_invitations.py`, new `web/display/calendar-invitations.js`/CSS, focused new checks and `docs/CALENDAR_INVITATIONS.md`. Owner/Household-only read/review/confirm routes under `/v1/display/calendar/invitations`; keep provider credentials and review state on the host. Coordinator registers routes, permits paired Household access and adds the event-details hook. | Explicit attendee/notification review, preserved existing guests and ETag conflict detection. No real invitations sent during development. Send the exact API/data contract before implementing shared integration. |
| ECHO-08 | Bounded provider investigation in `docs/CASTING_OPTIONS.md`, with source/version evidence and an implementation recommendation. Inspect existing Pi audio-focus interfaces read-only. Do not edit or install a receiver before the supported protocol and permission boundary are established. | Verify what this Pi can genuinely receive from the intended phone/apps; distinguish receiver software from senders and official Chromecast compatibility. This investigation alone does not close ECHO-08 or claim casting works. |

### Wave 2 result

- **ECHO-02: software implemented and deployed to the private host.** Following-only
  changes review every instance of a simple finite COUNT series, preserve earlier
  events and the remaining count, refuse exceptions, and report partial provider
  outcomes without repeating writes. The Pi serves the updated editor and review
  route. Real Google acceptance remains ECHO-11.
- **ECHO-03: software implemented and deployed to the private host.** The agenda
  opens a separate guest editor with explicit notification review and confirmation.
  Existing guests are preserved; Guest, Personal and Mini sessions cannot send
  invitations. Actual invitation delivery has not been tested or requested.
- **ECHO-08: investigation complete; implementation remains queued.**
  [Casting options](CASTING_OPTIONS.md) recommends a default-off Bluetooth A2DP
  receiver for the Pi and defines ECHO-08A's file/interface boundary. This adds no
  receiver yet and makes no Chromecast compatibility claim.

The combined calendar checks passed 78 tests on Windows and 91 on isolated Linux,
plus focused and full-page silent browser flows. Integration review caught and
fixed stale controls after a Google provider-role downgrade. Settings, source
grants and pairing were preserved during deployment. The Pi is online again,
serves matching assets, and its kiosk refreshed successfully. Its voice service
reports **unavailable**, with a generic microphone/speaker/runtime/host-connection
wait; that condition remains in ECHO-13. Volume stayed at 2%, Spotify remained
discoverable, and no sound or real calendar action ran.

**Next software dispatch:** ECHO-04 private Google linking and ECHO-08A's bounded
Bluetooth adapter. Their owners must first confirm account/source isolation and
Pi audio-focus interfaces respectively. ECHO-09 follows the supported media
capability decision. Hardware and real-account acceptance remain separate tasks.

## Dispatch wave 3

The coordinator owns existing Google storage hooks, account/app/authorization
wiring, agenda composition, recovery registration, Pi focus/bridge/bundle integration
and deployment. Worker code cannot change another lane's interface without a handoff.

| Task | Worker-owned scope | Shared contract / acceptance |
| --- | --- | --- |
| ECHO-04 | New member Google provider/API/UI, focused tests and `PERSONAL_GOOGLE.md`. | One encrypted member registry; read-only personal OAuth reuses the owner-configured client and public callback. Bind flows to member, endpoint and session nonce. Private selected calendars join only that person's explicitly shared sources; no household export or inherited writes. Root registers routes and recovery. |
| ECHO-08A | New Pi Bluetooth receiver/backend/preflight, focused tests and `PI_BLUETOOTH.md`. | Default off, selected existing bond only, private Pulse A2DP input to processed output. Root supplies fresh focus/access snapshots and synchronous hard-stop acknowledgment before capture; no lock inversion or automatic replay. No installation, radio changes or playback during checks. |
| ECHO-13 diagnostic fix | `deploy/pi/listener.py`, focused availability tests and the audio guide. | Report absent processed audio endpoints despite ALSA name hints, with bounded read-only probes and automatic status recovery. Preserve configured device selection and 2% volume; no fallback or live recording. |

The Pi diagnosis found that the configured physical USB audio card is absent.
Only built-in playback cards are present; capture inventory and private Pulse
sources/sinks are empty. The host speech service and wake model are available.
Hardware reconnection remains separate from this diagnostic software fix.

### Wave 3 result

- **ECHO-04: software implemented and deployed.** Personal sessions can link and
  explicitly select their own read-only Google calendars. Account changes,
  expiration and revocation discard stale flows/results. Private credentials and
  selections are included in encrypted recovery. Actual Google approval remains
  ECHO-11; no real account was connected during development.
- **ECHO-08A: receiver and integration installed, disabled.** The Pi bundle now
  includes selected-bond A2DP handling, Spotify priority, ducking and synchronous
  focus-stop acknowledgment. No Bluetooth packages, radio settings or pairing
  changed. Supported prerequisites, phone setup and audible playback remain
  ECHO-08; installation of adapter code does not establish receiver readiness.
  Read-only Pi inspection confirms the Bluetooth PulseAudio module is absent and
  Bluetooth is radio-blocked; the local package cache offers a matching module.
  These prerequisites were recorded without changing them.
- **ECHO-13: diagnostic fix installed; physical acceptance open.** Voice status
  now identifies missing actual processed audio routes even when their ALSA names
  still exist. The selected USB card is absent, so reconnecting the intended audio
  hardware and restoring its audio service are still necessary. No microphone
  capture or sound was used during these checks; volume remains 2%.

The integrated candidate passed 147 tests on isolated Linux, focused Windows
checks including passphrase recovery, and the silent private-calendar browser
flow. Actual application checks cover separate people, Household/Guest isolation,
callback completion, account removal, revision races and restoration into a fresh
application. The private host and Pi serve the verified update; the kiosk was
refreshed, Spotify remains discoverable, and pairing/configuration were preserved.

### ECHO-09 research handoff and next boundaries

The media worker completed [official-provider research](VIDEO_PROVIDER_OPTIONS.md).
An ordinary YouTube embed is a documented permitted route; it does not establish
paid-video support or actual Pi playback. Netflix and Prime remain unverified on
this Pi. No provider sign-in, installation or playback occurred.

The implementation is split into two bounded subtasks:

- **ECHO-09A, native browser audio admission:** define and implement a local
  browser-output stop/attenuation boundary with the coordinator-owned focus
  service. Preserve the 2% ceiling and confirm actual output silence before
  capture. An iframe's pause event is insufficient. Own new Pi adapter/tests;
  request shared bridge/Spotify integration from the coordinator. This task
  cannot change provider UI, global mixers or other audio sources.
- **ECHO-09B, ordinary YouTube UI:** depends on ECHO-09A's precise interface.
  Follow the researched owner configuration, per-display permission, explicit
  load, official player and narrow referrer/CSP contract. Own new backend/UI
  provider modules and focused checks; request shared route/asset registration
  from the coordinator. No paid catalogs, arbitrary embedded URLs or claimed
  provider acceptance. Real playback remains a separate ECHO-09 gate.

Both subtasks are dispatched with confirmed interfaces. Paid subscription video
requires a supported browser/provider test or a decision to use an external
supported device; ordinary YouTube playback cannot silently replace that scope.

### Dispatch wave 4: connected video feature

The native media worker owns new `browser_video.py` / `browser_video_backend.py`
and their tests/guide. The provider worker owns new `backend/video_provider.py`
and focused/app tests. The UI worker owns the new provider/player assets and
silent browser check. The coordinator owns `video_session.py`, existing
bridge/focus/screen/app/header registration, recovery, bundle and deployment.

The agreed native interface is `start(lease_id, video_id)`, `heartbeat(lease_id)`,
`hard_stop(reason) -> confirmed`, `snapshot()` and read-only `check()`. A fresh
32-hex lease opens only the fixed local player URL; it expires after 15 seconds,
with the player renewing every two seconds. Separate null-only browser audio is
attenuated before the existing processed speaker. Account changes, stale host
permission, focus, Spotify and Stop close the output; old leases cannot restart it.
The owner API grants one strict YouTube ID to explicitly selected Household
displays. Personal, Guest and Mini do not inherit it. Only the player page gets
the required YouTube script/frame and origin-referrer policy; other pages retain
their existing policies. No real provider playback is part of automatic checks.

### Wave 4 software checkpoint; deployed

The native adapter, provider permissions, owner settings, player UI and shared
routes are installed on the private host and Pi. The final Linux image passed
114 integration tests plus both real null-audio tests, with no skips; the silent
browser flow passed at desktop and phone sizes. Startup freshness,
cancelled leases, process-stop acknowledgment, account/source changes, encrypted
recovery and narrow player-only response headers are covered. The Pi inventory
confirms Chromium, PulseAudio and libpulse are present, but its selected USB
audio endpoint remains absent.

The isolated Linux null-audio build stalled when the host system drive reached
zero free space. A download-cache file was copied to a separate drive, verified
by size and SHA-256, then removed from the cache to recover about 2.8 GB. Installed
software and application data were preserved. The owner subsequently authorized
Docker recovery. Its stalled application processes and WSL VM were stopped,
then Docker Desktop restarted. Echo and Hermes are healthy, pairing remains
present, and the Pi again receives successful session and music responses.
No images, volumes or application data were deleted; no host reboot was needed.

The resumed Linux check exposed real PulseAudio JSON format differences in the
native sink/module validation. These are fixed, with 34 focused synthetic tests
also passing. Host and Pi asset hashes match the verified source, the Pi kiosk
refreshed, and private settings, pairing and grants were preserved. Spotify is
discoverable at 2%; Bluetooth and video remain disabled. No real YouTube playback,
recording or physical audio was used. The Pi still has no microphone capture
device attached, and provider/hardware acceptance remains open.

**ECHO-23** retains permanent storage relocation to the larger drive. Docker's
supported settings workflow and verified cold-backup procedure are documented in
[Host provisioning](HOST_PROVISIONING.md#if-dockers-system-drive-fills-up).
The temporary cache relocation does not close the long-term capacity task.

## Dependent software tasks

### ECHO-07: private calling deployed; physical acceptance open

The pinned LiveKit server is installed on the existing private Docker host.
The API uses an exact deployment binding for internal administration, encrypted
saved credentials and an owned private provider volume. The normal launcher
preserves the optional service. Existing pairing, user settings and the five-node
Tailscale allowlist are unchanged. No new cloud account is needed.

The gateway forwards only the exact v0/v1 signalling and validation routes;
its TCP 7881 listener verifies the same source IP and stable node identity before
connecting to Docker's loopback publication. The browser omits public STUN for
this private route. No UDP publication or provider admin endpoint was added.

Two synthetic browser participants established nominated, selected TCP pairs
through the final deployed route, with the expected remote address and port.
Capture and playback counters stayed zero. Owner start/end and paired Deck
calling permission were verified, and the Deck kiosk was refreshed. Temporary
rehearsal resources were removed. The code passed 41 focused Linux tests and
34 gateway tests. [Private calling](PRIVATE_CALLING.md) records setup and recovery.

Calling is enabled only for the owner and selected paired Deck. Physical duplex
sound/video, camera opt-in, phone behavior and audio focus remain ECHO-07, with
the Pi microphone absent at the last hardware check. This does not close the
whole calling acceptance task or claim telephone/public guest support.

### Hardware and provider preparation

The latest hardware preparation verified the retained 16 MiB Mini backup against
its saved SHA-256 and validated the four-image 0.19.0 firmware bundle. The Mini
is not connected over USB, so its current identity and state remain unverified
and no flash was attempted. The Pi's matching Bluetooth module and SBC library
are installed; radio, module loading, phone selection and reception remain off.
The Bluetooth module-ID compatibility correction passed 30 synthetic checks on
both Windows and the Pi, plus a read-only check of actual Pi module IDs. The
original hardware inventory does not identify the attached HDMI panel model.

A fresh connection inventory still finds no Mini USB device on the laptop and
no USB capture device on the Pi. The owner has been asked to reconnect both.
The Pi's browser inventory and actual Widevine module-loading check succeeded;
no media, account login or audio was used. A provider selection is pending before
the paid-video acceptance path is chosen. See [video findings](VIDEO_PROVIDER_OPTIONS.md).

The private Windows host has Hyper-V available but no registered spare VM and
about 0.7 GiB of free memory at inspection. Starting a fresh Windows recovery VM
there is not suitable under current resources. ECHO-20 still needs a disposable
replacement environment; no unrelated workload was stopped to create one.

Personal Hermes readiness was checked separately: no personal accounts or agent
connections are configured. A roster and per-person provider/tool choices are
needed before creating separate instances; the household agent remains active.

| ID | Bounded deliverable | Depends on | Acceptance gate |
| --- | --- | --- | --- |
| ECHO-02 | Following-only rescheduling of counted Google series. Preserve the correct remaining count and prior occurrences; recover/report partial multi-step provider writes without blind retries. | ECHO-01 | Synthetic count/DST/exception cases and one approved real-calendar rehearsal. |
| ECHO-03 | Guest invitations and attendee changes with an explicit recipient/send-notification review. Existing guests must not be silently dropped. | ECHO-01 | Fake-provider payload/consent checks; real invitations only when explicitly requested. |
| ECHO-04 | Private per-person Google account linking and calendar selection; no household grant inheritance. | ECHO-01, ECHO-05 account contract | Account-switch, revocation and source-intersection checks; actual sign-in separate. |
| ECHO-08 | Supported casting receiver choice and integration. First verify a maintained provider compatible with Pi/Linux and the intended sending apps. Implement only the documented supported route; label Chromecast/AirPlay limitations accurately. | Pi independent audio contract | A concrete supported protocol and end-to-end real sender/receiver acceptance; no placeholder claiming Chromecast support. |
| ECHO-09 | Commercial-video provider support and account/control UX for a provider that permits playback on this Pi/browser. | ECHO-08 capability findings | Actual authorized provider playback, or a documented external incompatibility requiring a product decision. Local video alone does not close this task. |

## Configuration and acceptance tasks

| ID | Task / clear finish condition | Prerequisite |
| --- | --- | --- |
| ECHO-06 | Grouped music: connect the intended Music Assistant provider, register both supported endpoints, verify synchronized playback and source interruption/recovery. | Mini firmware installed; actual provider available. Software adapters already exist. |
| ECHO-07 | Calling: configure the chosen LiveKit service and verify a two-device call, camera opt-in, mute/hang-up and endpoint audio focus. | Private provider deployed and TCP verified; available mic/camera endpoints are still needed for physical acceptance. |
| ECHO-11 | Google live acceptance: OAuth sign-in, explicit source sharing, agenda reads, reviewed creates/edits/deletes on a test calendar. | Owner Google OAuth client, ECHO-01. |
| ECHO-12 | Install the prepared Mini firmware after checking board identity and original backup; verify account, calendar, intercom and grouped-music pages on the physical board. | Board connected and verified; deployment coordinator. |
| ECHO-13 | Final Pi microphone/speaker/mute wiring and quiet acoustic acceptance: wake, cue, intelligible capture/reply, 80% music ducking, interruption and no feedback. | Final chosen audio hardware; owner available. Existing headset Spotify playback is confirmed. |
| ECHO-14 | Final Mini acoustic acceptance: comfortable level, wake/capture/reply, music interruption and duplex intercom. | ECHO-12, physical endpoint. |
| ECHO-15 | Identify the panel and finish physical touch/edge calibration and final visual acceptance. | Pi/display hardware access. Preferred mode is already 1024 × 600. |
| ECHO-16 | Screen comfort acceptance: verify physical dim/off, wake-only touch, and an explicitly selected presence sensor without unintended control activation. | Suitable approved sensor for presence; display hardware. Software is installed. |
| ECHO-17 | Camera/doorbell live acceptance using selected real sources and current permissions. | Owner-selected configured sources. View/permission software already exists. |
| ECHO-18 | Full power-off cold boot plus Wi-Fi/router restart recovery, with pairing/settings retained and no queued audio replay. | Stable final power/network. The 90-second endpoint-outage check already passed. |
| ECHO-19 | Enclosure fit, thermal check, final assembly/BOM instructions and photos for both builds. | Final hardware and ECHO-13–15. Existing Mini enclosure models remain available. |
| ECHO-20 | Fresh replacement-machine recovery rehearsal: install prerequisites, restore portable backup and models, then verify scoped services without touching production. | ECHO-10 and a disposable/fresh Windows machine or VM. Existing same-account and isolated-container rehearsals have passed. |
| ECHO-22 | Provision and connect separate personal Hermes instances, then verify their actual tools and identity isolation through Echo. Distinct configured URLs alone do not prove distinct server storage or credentials. | ECHO-05; chosen host resources and explicit server-side tool configuration. |
| ECHO-21 | Final integrated package review: reconcile all task results, current README/build instructions and unresolved limitations. | All required tasks resolved or an explicit owner decision changing scope. No automatic public release. |

When a worker finishes, record its evidence and handoff here. Do not start an
unrelated feature inside a task. Dependencies that require the owner or hardware
remain visible instead of generating more speculative implementation work.
