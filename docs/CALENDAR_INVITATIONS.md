# Reviewed Google Calendar invitations

Echo provides a separate guest editor for an existing Google event or one selected
recurrence occurrence. Open the event details, then **Guests & invitations**.
The ordinary event editor continues to reject events with attendees. Creating an
event does not automatically invite anyone.

1. Load the complete current guest list. Existing guests remain selected by default.
   Their response status, optional/resource flags and other provider metadata are
   preserved. The organizer and this account cannot be removed here.
2. Enter complete email addresses to add and explicitly select existing guests to
   remove. Choose a Google notification option; none is selected automatically.
3. Review the complete **Add**, **Remove** and **Keep** lists and the notification
   effect. Check the review acknowledgment, then **Confirm guest changes**.

Loading and reviewing never writes to Google. Confirmation PATCHes only the
reviewed `attendees` array, retaining every unchanged guest object. Event dates,
notes, location, recurrence, reminders and other event fields are not PATCHed.
Resource guests can affect room/equipment bookings. Accepted means Google accepted
the API operation, not that any invitation was delivered or accepted by a guest.

## Notification choices

The choices map directly to Google's `sendUpdates` parameter:

| Echo choice | Google value | Effect disclosed before confirmation |
| --- | --- | --- |
| All guests | `all` | Notify guests about the change, including added invitations and removed-guest cancellations. |
| Only guests who do not use Google Calendar | `externalOnly` | Google decides which guests use a different calendar. Echo does not infer this from email domains and cannot offer an arbitrary recipient subset. |
| Request no notifications | `none` | Requests no notifications. Google warns that some emails may still be sent and guest calendars may miss updates or lose synchronization. This is not a guarantee of silence. |

The review shows every retained, added and removed guest. It does not claim to know
exactly which recipients Google will notify, particularly for `externalOnly`.

## Access, freshness and storage

Only the authenticated owner and permitted paired Household displays may use this
flow. Guest, Personal and Mini/round sessions are denied. The Google connection
must already have its explicit write OAuth grant; the calendar must be in Echo's
managed calendars and still have Google writer/owner access. No grant is expanded
by opening the guest editor. Existing disabled/validation-host behavior applies.

The event must be an unlocked default Google event owned by the connected organizer,
with a complete list of at most 200 uniquely addressed guests. Missing/omitted guest
data, a different organizer, special event types and master-series changes require
Google Calendar. Repeating-event invitations affect only the selected occurrence.
Following-only and whole-series guest changes are outside this bounded feature.

The host rechecks the event ETag when loading, reviewing and confirming. The PATCH
uses `If-Match` with the reviewed ETag. A change elsewhere requires a new agenda
read and review. The returned agenda invitation reference is distinct from the
ordinary edit reference, so invitation eligibility never enables normal writes.

Pending reads and reviews remain in bounded host memory: at most 64 combined
entries, five-minute expiry, and at most 128 KiB per provider event before accepting
it for review. Every operation prunes expired entries; the app may also call
`app.state.calendar_invitations.prune()` during its existing cleanup cycle. Restart
discards drafts. Provider credentials remain in the existing encrypted host store
and never enter these responses or browser storage.

A review receives a random proof and request ID. Confirmation requires the exact
proof, request ID, original reference/source revision and literal `confirmed: true`.
The proof is bound to the initiating authenticated endpoint/principal and its
profile revision. Re-review invalidates the previous proof. Account/profile/source
changes discard the browser flow and authorization is rechecked before disclosure
and dispatch. The UI never persists attendee data or the proof to browser storage.

Before dispatch the shared encrypted receipt store saves a digest and pending status,
not attendee content. Repeating the same confirmed request returns its recorded
status without sending again, including after response loss or host restart. A
pending/unknown result remains unconfirmed. After a lost response, **Retry same
request** retains the exact confirmation body. Inspect Google Calendar before
starting a different change; an unknown result must not become a blind retry.

## Integration interface

`backend.calendar_invitations.install(app, writer, authorize, displays=None,
briefing=None)` registers the routes and returns a `CalendarInvitations` service.
Pass the same `CalendarWriter` used by the ordinary event routes. The installer also
sets `app.state.calendar_invitations` and keeps the existing lock order: account
access, writer receipts, source grants, Google state, then invitation review state.

All routes use POST under `/v1/display/calendar/invitations`:

| Suffix | Request | Response |
| --- | --- | --- |
| `/read` | `reference: EventReference`, `revision: int` | `read_id`, event title/start/end/scope, display-safe attendee fields, notification choices, expiry. |
| `/review` | `read_id`, `add: [email]`, `remove: [email]`, `send_updates: all/externalOnly/none` | Immutable review IDs/proof, original reference/revision, event, resulting attendees, added/removed/affected guest addresses, notification effect, expiry. |
| `/confirm` | `review_id`, `review_proof`, `request_id`, `reference`, `revision`, `confirmed: true` | `accepted`, `rejected` or `unconfirmed` status and explanatory text. |

Guest additions/removals are operations against the host's complete current guest
list; browsers cannot provide a replacement list or arbitrary guest metadata.
Unexpected fields, duplicate addresses, unknown removals and organizer removal are
rejected. Email matching is case-insensitive; retained objects keep their original
provider spelling and fields.

The display's classic script exposes
`openCalendarInvitations(item, {revision, onComplete})` and
`cancelCalendarInvitations()`. The item must contain `invitation_reference`; revision
is the current source revision. The script cancels stale identity/source results,
hash navigation and `echo:page` navigation away from My day. The shared identity
cleanup may call `cancelCalendarInvitations()` directly as well. Register the new JS
and CSS and show the details hook only for a currently permitted managed source.

## Verification and remaining acceptance

Run the focused fake-transport checks with:

```powershell
& '..\Round-Voice\.venv\Scripts\python.exe' -m unittest tests.test_calendar_invitations -q
node tools/check_display_calendar_invitations.cjs
```

The browser check uses a local page with synthetic API responses, refuses all
network requests, and opens no media devices. It needs the existing Playwright
package on `NODE_PATH`. It verifies explicit review/acknowledgment, exact-body retry,
notification choices, guest retention, stale-read cancellation and phone layout.

`tools/check_display_calendar_wave2.cjs` additionally exercises the full agenda
entry point on an explicitly started synthetic preview, using `ECHO_PREVIEW_URL`.
It intercepts every write and verifies guest confirmation alongside following-series
review/proof forwarding, two-step deletion, closed/stale review discard and Guest
control hiding. It refuses an origin that does not advertise `display_demo: true`.

These checks do not establish real Google invitation delivery, cancellation,
external-calendar synchronization, resource booking or recurring-exception behavior.
Those remain separate live acceptance with an explicitly approved calendar and
recipients. No real account, message or invitation is used during development.

Provider references:
[events.patch](https://developers.google.com/workspace/calendar/api/v3/reference/events/patch),
[events.update](https://developers.google.com/workspace/calendar/api/v3/reference/events/update),
[Event resource and attendees](https://developers.google.com/workspace/calendar/api/v3/reference/events),
[versioned resource updates](https://developers.google.com/workspace/calendar/api/guides/version-resources).
