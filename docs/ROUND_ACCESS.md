# Share Echo Mini

Mini can be a trusted **Household** speaker or a **Guest** speaker with selected
home controls and optional conversation. The owner manages this in the smart
display workspace: **Settings → Share the round speaker → Mini access**.
Existing installations stay Household. The first switch to Guest requires a
connected Mini advertising the profile support in firmware **0.18.0 or newer**.

## Choose its controls

Give the profile a name and an optional room label, then select individual devices
as **View** or **View & control**. The global Devices permissions remain the upper
limit. A room label never grants access by itself.

- The four light buttons contain only shared lights assigned to those rooms.
  A room with any View-only light cannot be toggled from the room button.
- The thermostat card uses the configured thermostat if shared, or the sole
  shared thermostat. Multiple candidates require an explicit configured choice.
- The speaker picker contains only shared speakers. Guest selection is separate
  from the household speaker selection. Physical volume/temperature buttons
  require Control; View displays state without sending a command.
- Weather appears only when its entity is shared. Unsupported or unavailable
  devices stay unavailable; there is no fallback to an unshared device.

## Choose conversation access

**Allow guest conversation** enables general questions and public web lookup using
the configured provider and separate temporary history. It does not share
household memory, private personality instructions, lists, research tasks or
Hermes tools. Provider use can still involve cloud processing if that is the
owner's chosen provider.

**Allow local guest home voice commands** is a separate owner opt-in and requires
conversation. It enables the bounded named-device and room commands described in
[Display access](DISPLAY_ACCESS.md#guest-home-commands). These commands stay local
to Echo and can reach only shared entities. Physical controls remain usable with
conversation off; the microphone stream and wake/Talk recognition are disabled.

Spotify playback, local volume, screen settings and timers addressed to Mini stay
available. Existing Mini timers continue across profile changes. Calls, household
announcements, grouped music and calendar drafting are unavailable in Guest mode.
Mini has no Guest camera or calendar-source viewer. Use Deck for those sources.

## Changing access

Mini shows **ECHO / GUEST** in its header. The current host checks saved access
regularly, cancels pending replies and clears old cards, call state and drafts
when it changes. Requests retain the revision they started with; queued controls
cannot inherit a newer profile's grants. Global grants are rechecked before home
dispatch. An action already admitted cannot be undone by changing the profile.

The owner cannot switch profiles during an active assistant request: Echo first
requests cancellation. Saved restrictions remain editable while Mini is offline.
An unreadable profile disables access instead of silently restoring Household.

The host stores the profile encrypted in `local/echo-round-profile.json`; recovery
archive version 2 includes it. Credentials and owner keys remain on the host,
outside the firmware and browser. This is per-device access, not personal sign-in
or voice identification. Anyone using a Household Mini has its household access.

## Verification and installation status

Synthetic API checks cover private-route denial, isolated conversation, shared
home actions, read-only controls, changed speaker bindings, temperature units,
global revocation, timers, encrypted persistence and immutable queued identities.
The owner editor is checked at display and phone sizes. Native C++ checks render
the Guest header and verify control/microphone defaults; firmware 0.18.0 builds
and has a verified four-image archive.

The host feature is deployed privately. The new Mini firmware has **not been
flashed**; physical Guest use, touch controls and microphone behavior remain
unverified. No real profile was switched to Guest during deployment, and no
test sound or home-device action was used.
