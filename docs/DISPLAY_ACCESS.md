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
  calendar drafts and Hermes tools are not passed to the guest model. Use Rooms
  for approved home actions; guest speech does not call household tools.

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
Separate member identities, individual memory/calendar accounts, guest voice
control through scoped tools, and profiles on the Mini remain open work.

Synthetic API checks exercise denied direct routes, isolated typed and spoken
conversation, selected-source filtering, global revocation, timer ownership,
encryption/restart behavior and profile changes during a reply. Browser checks
cover the owner editor and guest layout; these do not establish physical guest
use or replace the remaining hardware acceptance.

The private host and current Pi client include this feature. Existing pairings
remain Household; deployment did not assign any real display to Guest. The
listener returned armed with existing private settings, Spotify discovery and
echo cancellation preserved. Physical guest use remains unverified.
