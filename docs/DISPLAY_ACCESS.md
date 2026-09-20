# Household and guest displays

Each paired display can have a named access profile and room label. Existing
displays remain **Household** until the owner changes them. A room label does not
automatically share devices in that room.

Open the smart display from the **owner workspace**, go to **Settings → Your
displays**, and choose **Access** beside a paired device. Only the owner can save
its profile; the paired device cannot promote itself.

## Choose what is shared

**Household** is for a trusted shared device. It keeps Echo's existing household
memory, lists, planning, routines and assistant tools, subject to the normal home
permissions. **Guest** starts with no shared home devices or calendar/camera
sources. Select each item deliberately:

- **Home devices:** Not shared, View, or View & control. The owner's global
  Devices permissions remain the upper limit. Guest room controls use these
  individual devices; broad legacy room and speaker shortcuts are unavailable.
  Scenes are excluded because they can affect devices outside the selected set.
- **Calendars and cameras:** choose from sources already shared in Display
  settings. Guest calendars are read only. Removing a global source also removes
  guest access, including an open camera stream.
- **Presence sensors:** choose globally approved motion/occupancy sensors, then
  select the desired wake sensor in that display's Screen comfort settings.
- **Conversation:** optionally allow general questions and public web lookup
  through the configured provider. It uses separate temporary history and Echo's
  default personality. Household memory, private personality text, lists, routines,
  calendar drafts and Hermes tools are not passed to the guest model.
- **Local guest home voice commands:** a separate option, off by default. When
  enabled, clear typed/spoken commands can read or control only the selected home
  devices. Processing is local to Echo; device names and state are not sent to a
  model. The normal conversation provider has no home tools.

## Guest home commands

Enable **Allow local guest home voice commands** in that display's owner-managed
Access page. Conversation must also be enabled. Examples:

- “What devices are shared?” or “What is the status of Guest lamp?”
- “Turn off Guest lamp” or “Set Guest room lights to 20 percent.”
- “Set Guest thermostat to 21 Celsius.” Temperature units must be explicit.
- “Pause Guest speaker,” “Unmute Guest speaker,” or “Set Guest speaker volume to 15 percent.”

Use the actual names shown on Rooms. Room-light commands include only shared
lights in that room. Unclear or duplicate names ask for clarification; pronouns,
conditions, scenes, routines and arbitrary Home Assistant services are not
interpreted as guest commands. Complex requests can use the explicit Rooms controls.

Changes also require **Allow home actions** on the current typed/push-to-talk
message. Native Pi wake requests use the owner's saved wake home-action setting.
Both paths recheck global and display permissions before dispatch; View never
becomes Control. Device capability/range validation and observed-state receipts
use the same action engine as household controls. Cancellation or revocation
stops new commands; an action already sent cannot be undone. Request results are
not inserted into the general guest model's history.

The current Pi client forwards push-to-talk permission only when this option is
enabled. Older clients keep guest push-to-talk home actions disabled. No existing
profile is opted in by the update, and no real home actions are used during installation.

Guest displays retain their own local Spotify playback, clock, screen controls,
and timers/alerts addressed to that display. Existing alerts for that endpoint
continue after a profile change. Music, microphone and alert hardware setup remain
owner-managed; microphone mute and ordinary playback controls remain available.
Shared photos, household notifications, room calls, research tasks and global
planning pages are not exposed in Guest mode.

## Changes and saved data

Saving access requires the current profile revision. If a conversation is active,
Echo requests a stop and asks the owner to save again after it finishes. A successful
change clears that endpoint's host conversation history. The display reloads when
its regular session refresh detects the new revision. The current Pi client also
discards old reply text and interrupts speech when its speech-status check observes
the change. Already accepted home actions are not undone.

Use the current Pi client bundle before assigning Guest mode. Earlier bundles do
not know how to discard a reply left in local memory after a profile change.
New backend and client code remain compatible with existing Household pairings;
there is no need to enroll them again.

Profiles are encrypted alongside display credentials in `local/echo-displays.json`
and included in the existing recovery archive. Provider keys never enter the
display page. Removing a profile grant does not delete household data.

## Scope and remaining work

These are **per-device access profiles**, not per-person sign-in or voice
identification. Anyone using a Household display receives its household access.
[Personal accounts](PERSONAL_ACCOUNTS.md) add explicit Deck sign-in and separate
member memory and conversations. External calendar-account sign-in remains open.
[Mini profiles](ROUND_ACCESS.md) use the same grants with native home cards;
their firmware is built and awaits installation. Local guest home commands
are implemented with the explicit scope described above.

Synthetic API checks exercise denied direct routes, isolated typed and spoken
conversation, selected-source filtering, global revocation, timer ownership,
encryption/restart behavior and profile changes during a reply. Guest command checks
cover exact device/room matching, current-message consent, read-only access,
revocation before dispatch, unsupported values, cancellation and validation mode.
Browser checks cover the owner editor, optional voice consent and guest layout;
these do not establish physical guest
use or replace the remaining hardware acceptance.

The private host and current Pi client include this feature. Existing pairings
remain Household; deployment did not assign any real display to Guest. The
listener returned armed with existing private settings, Spotify discovery and
echo cancellation preserved. Physical guest use remains unverified.
