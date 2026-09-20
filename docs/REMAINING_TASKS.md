# Remaining work: bounded tasks

This is the execution plan for the remaining items in [the build queue](BUILD_QUEUE.md).
Each task has a concrete deliverable and acceptance gate. Software completion does
not close an external-service or physical acceptance task. The repository remains
private. No release, push, firmware flash, sound playback or home-device action is
part of an agent's automated checks.

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

## Dependent software tasks

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
| ECHO-07 | Calling: configure the chosen LiveKit service and verify a two-device call, camera opt-in, mute/hang-up and endpoint audio focus. | Provider credentials and available mic/camera endpoints. Signalling/UI software already exists. |
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
