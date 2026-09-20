# Personal accounts on Deck and Mini

Each person can have their own saved facts, personality preferences and temporary
conversation. Sign-in is deliberate: Echo does not identify people by their voice.
A personal session lasts 15 minutes, or until someone chooses **Lock personal
session**. Anyone physically using that screen can use the unlocked session.

## Set it up

1. In the owner smart-display workspace, open **Settings → Personal accounts →
   Manage accounts** and create an account. Save the eight-digit passcode shown
   once. Echo stores a salted scrypt hash, not a recoverable passcode.
2. Use **Access** beside the account to choose its home devices and read-only
   calendar, camera and presence sources. Conversation is enabled by default;
   home voice commands require a separate opt-in. No home devices are granted
   automatically.
3. In **Settings → Your displays → Access**, select the accounts allowed to sign
   in on that Deck. A room label does not assign accounts or devices.
4. On the Deck, tap **Sign in**, choose the account and enter the passcode on the
   touch keypad. The header identifies the active person.
5. Tap the account name to manage saved facts, export memory, adjust personality
   and memory preferences, or lock the session. You can also ask Echo to remember
   or forget a fact during conversation.

Install the current Pi client before assigning Deck accounts. Existing displays remain
Household or Guest until their owner changes them; installing the feature creates
no accounts and grants no new access.

## Sign in on Mini

Mini firmware **0.19.0 or newer**, with the matching host, adds **Settings → Me**.
The owner creates the account as above, then selects it in **Settings → Share the
round speaker → Mini access → Personal sign-in**. New assignments are disabled
until Mini reports the required firmware capability.

On Mini, choose the account and use the eight-digit keypad. Only masked digits
appear. Cancel, navigation away and a 60-second entry timeout clear the entered
code. Successful sign-in shows the person's name and a **Lock my session** button;
voice and the native home cards then use that account's grants. The same saved
facts can be used from Deck or Mini, with separate temporary conversations for
each login. Manage preferences and individual facts on Deck, or ask Mini to
remember or forget a fact.

Mini uses the same 15-minute host session. API checks, background access refresh
and an additional post-synthesis check discard obsolete requests and audio.
Unreadable or stale access state disables conversation instead of restoring
household privileges. Passcodes travel over the existing trusted USB or paired
TLS connection and are not written to firmware preferences or host status.
Firmware installation and physical keypad/voice acceptance remain open.

## Ask about your calendar

While signed in on Deck or Mini, ask **“What's on my agenda today?”**, **“Read my
calendar tomorrow”**, or **“Check my schedule this week.”** A personal daily
briefing request also reads the permitted calendar agenda. “This week” covers
the next seven days; the reply says that explicitly. Dates and times use the
host's Home Assistant time zone, with Echo's configured schedule time zone as
the fallback.

The local summary reads only calendars allowed by the account, display and global
source settings. It names up to five remaining events and reports unavailable
calendars rather than claiming the day is empty. It does not include household
tasks, reminders or shopping lists, and sends no calendar content to the model
or web search. Turn off the lookup toggle for a private agenda request. Locking
the session or changing its grants during a request discards the result.

Calendar accounts are still connected through Home Assistant and assigned by
the owner. This feature does not add personal Google sign-in, invitations, or
calendar writes from a personal session.

## What is separate

- Saved facts belong to the account. Up to 200 facts are supported per person,
  with up to 16 accounts on a host. Pausing conversational memory leaves saved
  facts available for deliberate review and deletion.
- Conversation history is temporary and belongs to the current login. Locking,
  expiry or a host restart ends the login and clears that conversation. Saved
  memory remains available after the next sign-in.
- Account device/source grants intersect with Guest display grants and the
  owner's global grants. A personal login cannot expand a Guest display's access.
- Personal conversations use the configured provider/model and public lookup
  with that person's memory and preferences. They do not inherit household
  personality, memory, lists, routines, photos or the shared Hermes tool session.
  An owner can optionally connect a separate personal Hermes instance, which
  the person must also enable in their preferences (see below).
- Timers and media remain functions of the physical endpoint. Signing in does
  not route audio to another speaker or create a private music-provider account.

Provider keys stay on the host. Personal facts relevant to a model answer are
sent to the selected model provider, just as household memory is; “personal”
describes account separation, not an offline-model guarantee. The host owner
remains trusted and controls the storage key, provider and application.

## Locking, recovery and removal

Five unsuccessful passcode attempts lock that account for five minutes. The
lockout survives a host restart. The owner can replace a passcode; this locks
active sessions. Account deletion removes its saved memory and locks sessions.
Existing exported files and older recovery archives are separate copies and
are not erased by deleting an account.

Requests retain the access revision captured before typing or recording is
submitted. A changed or expired login cannot write into the next person's
account. Replies are checked again after speech synthesis, and the Pi rechecks
before opening audio output. Active playback is interrupted when its periodic
access check observes a change; sound already played cannot be recalled.
The browser clears the personal screen at expiry even if the host is unreachable.

Accounts, hashed passcodes, lockout state, preferences and saved facts are encrypted
in ignored `local/echo-members.json`. The existing encrypted recovery archive
includes this store. Restoring it does not restore unlocked sessions. Keep recovery
archives and the required protection keys private.

## Optional personal Hermes agent

This software supports the Hermes gateway's native asynchronous runs API:
`POST /v1/runs`, `GET /v1/runs/{run_id}`, and `POST /v1/runs/{run_id}/stop`.
The protocol was checked against upstream
[`api_server_runs.py` at 2ed6387d87b4](https://github.com/NousResearch/hermes-agent/blob/2ed6387d87b4db091af2f05db32faab6e0dbb9a2/gateway/platforms/api_server_runs.py).
Each turn submits only this login's bounded text history, personal preferences
and relevant saved facts. Echo does not send a household provider key, shared
session identifier, device/source grants, action credential or household memory.
It does not use a remote session continuation or resume history from a previous login.

1. Provision a separate Hermes instance for the person outside Echo. Give it a
   separate `HERMES_HOME`, storage, API key and provider credentials. Do not copy
   the household instance's configuration, Echo home connector, mounts or secrets.
2. Configure only server-enforced read-only personal tools on that instance.
   Disable messaging, write/control tools, arbitrary terminal execution and
   household connectors. Configure Hermes memory and user-profile writes off
   (`memory.memory_enabled: false`, `memory.user_profile_enabled: false` and
   `memory.nudge_interval: 0`), so Echo's deliberate saved facts remain the memory
   contract. Remote logs and provider retention still require separate operator
   management; deleting an Echo account cannot erase them.
3. In **Settings → Personal accounts → Manage accounts → Personal agent**, enter
   the instance's HTTPS origin and separate API credential. Loopback HTTP is
   supported for an owner-managed local instance or authenticated tunnel. No URL
   credentials, paths, query strings, profile aliases or redirects are supported.
   Confirm the instance separation and read-only tool configuration, then save.
   Saving does not contact, provision or verify the remote service; active sessions
   for that account lock. A blank key preserves it only for the same origin.
4. Sign in as that person. Open their account preferences, enable **Use my personal
   Hermes agent**, and save. Both owner availability and this personal opt-in are
   required. The choice applies to subsequent Deck and Mini logins; configure it on Deck.

The gateway's generic runs API has no supported per-request tool allowlist. Its
tools and persistent state come from the configured instance. Echo therefore
requires the trusted owner to enforce that boundary on the server; instruction
text is not an authorization control. Distinct origin and API-key checks reject
known household endpoints and reuse across personal accounts, including common
loopback aliases. Different DNS names or proxies can still point to the same
instance; the owner must verify that they do not. A unique run ID alone does not
isolate Hermes tools or files. Personal Echo home and calendar commands continue
to use the existing account/display/global grant intersection locally.

Public lookup keeps the existing direct-provider citation path. With no personal
connection, or either opt-in disabled, normal conversations retain the direct
model path. An enabled personal agent's error does not silently reroute private
text to another agent. Waiting for a remote approval stops the run and reports
that the read-only instance needs attention; Echo never approves it automatically.

Lock, expiry, account switch, access revision and configuration changes cancel
polling and discard obsolete replies. When an admitted run ID is known, Echo
requests that run's stop without retrying admission. A lost admission response
may leave an unidentified remote run; an unreachable stop cannot prove it stopped.
The UI reports that uncertainty. Stopping does not undo any work already performed
by a misconfigured remote instance. No raw run diagnostics, tool payloads or API
credentials are returned to the browser. Endpoint settings and keys live inside
the existing encrypted `local/echo-members.json` and its protected recovery archive;
owner status reveals the configured origin and whether a key is saved, never the key.
**Remove connection** erases the active stored endpoint/key and locks sessions.
Older archives remain separate copies.

## Verification and remaining work

Synthetic API checks cover assignment, account isolation, wrong-code lockout,
encrypted restart, deletion/reset, grant intersection, stale requests and logout
during speech generation. Recovery checks restore a saved account and its facts.
Native listener checks reject an old account's reply before playback. Silent
browser checks cover creation, access editing, touch sign-in, memory, lock and
phone layout. These checks do not establish physical keypad or spoken acceptance.

Fake-provider checks cover native run admission/poll/stop, owner-only setup,
default-off and per-person opt-in, credential redaction and encrypted restart,
distinct endpoint/key checks, local memory commands, direct lookup fallback and
discard after switch, expiry, grant/settings changes or memory edits. These are
software checks; no live personal Hermes instance has been provisioned or accepted.
The owner still needs to provision each separate service, verify its tools and
storage isolation, then explicitly test a read-only conversation.

Voice identification remains future work. Personal accounts can now link and
select private read-only Google calendars using [My Google calendars](PERSONAL_GOOGLE.md).
Private selections do not become household sources or inherit write grants.
Actual Google sign-in remains an external-service acceptance item. Shared Home Assistant
and owner-linked [Google Calendar](GOOGLE_CALENDAR.md)
sources can be granted read-only now. The isolated display preview uses
temporary demo accounts only; closing the preview process removes them.
