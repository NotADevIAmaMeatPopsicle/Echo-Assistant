# Room announcements

Send a short spoken message to selected Echo receivers from **Planner → Room audio**.
The round speaker and each paired display are separate destinations. An owner
browser can send messages and configure rooms; receiving requires a paired display
or the round speaker bridge.

![Room announcement composer and delivery results, with synthetic data](images/display-announcements.png)

## Set up receivers

1. In the smart display's owner session, open **Settings → Room receivers**.
2. Give each receiver a room name, check **Enabled**, and save. Nothing is enabled
   automatically in a new installation.
3. On each paired display, open **Settings → Sound on this display** and press
   **Enable announcements here**. This allows browser audio for that session.
   Receiving starts off again after a reload. The initial level is 2%.
4. Keep the round speaker powered and connected. Its microphone mute and speaker
   volume also apply to announcements. Existing timers retain their own behavior.

An enabled receiver may be offline, busy, muted, or in quiet hours. Browser
receiving pauses while recording a voice message, chatting, playing other display
media, or while the tab is hidden. Another enabled tab for the same display must
stop receiving before a second tab can take over; a disconnected tab's receiver
lease expires after 20 seconds.

## Send, cancel, and read results

Select rooms explicitly, enter a message of up to 400 characters, then press
**Send announcement**. Retrying a lost response uses the same request identifier
and cannot create another announcement. Use **New message** for a separate request.
**Cancel delivery** stops queued deliveries and asks active receivers to stop at
their next status check.

Messages wait for up to five minutes. Quiet hours apply to every destination;
alarms' override setting does not override announcements. Expired messages do not
play later. Delivery history lasts 24 hours, with a maximum of 128 announcements.
The round speaker pauses music for delivery and follows its existing resume behavior.

| Result | Meaning |
| --- | --- |
| Waiting | Accepted and awaiting an enabled, available receiver. |
| Delivering | Claimed; synthesis or playback is in progress. |
| Played · receiver report | The receiver reported completion; this is not an audibility measurement. |
| Cancelled | The sender, receiver, quiet-hours check, or removal of access stopped delivery. |
| Failed | Audio could not be generated or played. |
| Unknown · not replayed | A claim expired or the server restarted before completion could be confirmed. |
| Expired | No receiver started delivery within five minutes. |

Messages and receipts use the host's existing encrypted storage. Raw display
credentials and delivery tokens are not stored in the outbox. Audio is synthesized
on the host, shared across the selected rooms, and held only in a bounded memory
cache. Revoked displays cannot retrieve it. Paired displays can view and cancel
their own sent messages; the owner can manage all deliveries.

## Current acceptance

API tests cover scoping, enrollment/revocation, shared synthesis, cancellation
during generation, mute, quiet hours, expiry, encrypted storage, duplicate requests,
and ambiguous delivery after restart. The round adapter uses synthetic WAV data
in tests. Browser checks simulate Web Audio without opening an audio device and
cover send/retry/cancel, assignments, receiving opt-in, interruption, and phone layout.

Physical audibility on both endpoints remains unverified. The Pi needs an
identified speaker/output and microphone for its broader voice features.
**Two-way intercom is still pending**; announcements are one-way messages.
