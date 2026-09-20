# Personal accounts on a shared Deck

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

Install the current Pi client before assigning accounts. Existing displays remain
Household or Guest until their owner changes them; installing the feature creates
no accounts and grants no new access. Mini personal sign-in is not implemented.

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

## Verification and remaining work

Synthetic API checks cover assignment, account isolation, wrong-code lockout,
encrypted restart, deletion/reset, grant intersection, stale requests and logout
during speech generation. Recovery checks restore a saved account and its facts.
Native listener checks reject an old account's reply before playback. Silent
browser checks cover creation, access editing, touch sign-in, memory, lock and
phone layout. These checks do not establish physical keypad or spoken acceptance.

Personal Mini sign-in, voice identification, separate Hermes instances per person
and external calendar/account sign-in remain future work. Shared Home Assistant
calendar sources can be granted read-only now. The isolated display preview uses
temporary demo accounts only; closing the preview process removes them.
