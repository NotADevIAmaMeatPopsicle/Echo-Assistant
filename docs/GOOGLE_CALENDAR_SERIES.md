# Google Calendar: this and following occurrences

Echo supports reviewed following-only changes for a bounded set of finite Google
series. The selected occurrence's start and end can move. Earlier occurrences
retain their original master dates and the replacement series retains the correct
remaining COUNT. This software path has synthetic coverage; an approved real
Google calendar rehearsal remains unverified under ECHO-02/ECHO-11.

## Review and supported series

Select an actual occurrence and choose **This and following occurrences**. Echo
loads the selected dates and reviews the complete series before opening the editor
or deletion confirmation. The review reports the number of earlier occurrences
and the number affected. Editing preserves the recurrence frequency and interval,
the all-day setting, and the IANA time zone. Changing the selected start is allowed.

The current supported rules contain exactly one `RRULE`, with `FREQ=DAILY`,
`WEEKLY`, `MONTHLY`, or `YEARLY`, optional `INTERVAL=1..99`, and `COUNT=1..366`.
There must be no other rule parts, recurrence dates, exclusions, cancelled or
customized occurrences. A rule containing `BYDAY`, `UNTIL`, multiple rules, or
other unsupported fields requires Google Calendar. The original master must
include its provider `iCalUID` so stored exceptions can be checked.

Echo follows every page of `events.instances`, with `showDeleted=true`, without a
date window. It orders the complete provider list by `originalStartTime`, requires
exactly COUNT unique instances, and locates the selected provider ID. The count is
not inferred from elapsed days, the display date, the replacement start, or a
locally guessed recurrence sequence. Monthly dates that Google skips and offsets
across daylight saving time therefore do not change the count calculation. An
incomplete, ambiguous, or oversized response fails before any write.

Every instance must retain the master fields and duration and must still begin
at its original start. A separate complete `events.list` query, filtered by the
master `iCalUID` with `singleEvents=false` and `showDeleted=true`, must contain
only the master. This also refuses stored exceptions whose visible fields happen
to match the master. Both earlier and following exceptions block the operation;
Echo does not silently reset or copy them. The two queries are each bounded to
16 pages, and repeated/invalid continuation tokens fail closed.

Events with attendees, omitted attendee data, provider locks, special types,
tentative status, attachments, conferencing, extended properties, unspecified
ends, or other unsupported provider fields require Google's editor. Safe master
properties such as reminders, colour, visibility, transparency and guest-setting
flags are carried to the new series. Description and location remain editable.
Sub-minute dates, unsupported time zones, longer editor fields, or inconsistent
instance durations also require Google's editor. This path sends no invitations.

## What the provider changes

For a six-occurrence weekly series, selecting the third occurrence produces two
earlier occurrences and four remaining occurrences. If its start moves from
Tuesday to Wednesday, Echo performs:

1. A conditional PATCH of the original master, changing only its rule to
   `COUNT=2`. Its original start, end and event properties are retained.
2. An insert of a new master at the reviewed Wednesday start, with the same
   frequency/interval and `COUNT=4`. The provider event ID is deterministically
   derived from the request ID, and no original `iCalUID` is copied.

The new start may be earlier or later than the selected original start; the
reviewed first date drives the new series, while the preserved earlier series
is unchanged. Local time and offset are supplied together with the original
IANA zone. Nonexistent replacement times are refused; the selected daylight
saving fold is retained.

Deleting this and following occurrences performs only the conditional trim.
For the first occurrence, there is no earlier series: an edit is one conditional
master PATCH that keeps the original COUNT, and a deletion is one conditional
master DELETE. A split of the final occurrence creates a `COUNT=1` master.

The optional Google write scope, provider owner/writer access, initiating
Owner/Household identity, and Echo management grant are rechecked. An edit that
inserts a second master also requires Echo's separate **Allow event creation**
grant before trimming and again before insertion. Following deletion and edits
of the first occurrence do not require creation permission. Guest and Personal
sessions do not gain write access.

## Versions, partial completion and recovery

The review reference includes `following_version`, a SHA-256 digest of the
original master and the complete instance snapshot. A mutation rereads both
lists and the master, checks the selected occurrence version, and compares the
review digest. The original write uses the reviewed master ETag as `If-Match`.
The writer takes locks in the existing order: initiating access, calendar
receipts, source permissions, then Google accounts. It validates access again
before returning any review or operation result.

Google does not offer an atomic transaction covering a master and all instances,
or a transaction spanning the trim and insert. An external edit after the final
read can race the operation; `If-Match` protects the master resource, not every
separate instance. This implementation does not claim a provider-wide lock or
automatic rollback. Live concurrency and provider exception behavior still need
the approved test-calendar rehearsal.

An encrypted receipt is committed before each provider write and between steps.
It contains only a request digest, status, step name and counts. It contains no
event text, provider IDs, calendar addresses, dates, token or recovery payload.
The ordinary receipt format and its existing statuses remain compatible with
restart and protected backup. Both provider writes use `sendUpdates=none`.

| Saved stage/result | Meaning on retry |
| --- | --- |
| `complete` / accepted | Google confirmed the whole change. |
| `trim_rejected` / rejected | The first write was definitively rejected; insertion was not sent. |
| `trim_pending` or `trim_unconfirmed` | The original series may have changed; insertion was not sent. |
| `trim_accepted`, `insert_blocked` or `insert_rejected` | The original series was shortened; the new series was not created by this operation. |
| `insert_pending` or `insert_unconfirmed` | The original series was shortened; creation of the new series is unconfirmed. |

Partial completion returns `status=unconfirmed`, an explicit `series_step`, and
plain-language guidance. A retry with the same request ID returns the saved
outcome without sending or resuming any write, even after a process restart.
Changing the reviewed intent while retaining the request ID is rejected. A
permission change after dispatch returns the existing retry-safe access error;
an authorized subsequent read of the same receipt retains the partial outcome.

For any partial or unconfirmed outcome, inspect the original and possible new
series in Google Calendar. Restore or finish the following occurrences there as
appropriate. Do not invent a new Echo request ID to replay the old split. A
failed checkpoint write can leave the preceding stage as the last durable
evidence, so the result remains conservative. Echo never automatically rolls
back the trim or retries a possibly completed insert.

## Integration and verification

The worker module exposes:

```python
review_following(adapter, reference, revision)
change_following(adapter, operation, reference, event, revision, request_id)
```

`adapter` is the existing `GoogleCalendarWriter`. `operation` is `edit` or
`delete`; edits accept the existing `CalendarEvent`, while deletion requires
`event=None`. `EventReference.following_version` is optional for other scopes
and required for this mutation. Existing single/occurrence/master receipt digests
must continue to exclude that newly added optional field.

The review returns `reference`, `editor_event`, `repeat_summary`, `prior_count`,
`remaining_count`, `following_start_locked=false`, and `provider=google`. The
coordinator registers `POST /v1/display/calendar/following` with the existing
master-review identity guard, routes the Google `following` change scope to this
module, and makes the display review the returned reference before confirmation.
Other recurrence scopes and the Home Assistant writer remain independent.

Focused checks: `python -m unittest tests.test_google_calendar_series -q`.
The new synthetic cases cover complete pagination and provider ordering, COUNT
conservation after real date moves, month-end skipped dates, all-day events,
daylight saving offsets/folds/gaps, last and first occurrences, following deletion,
stored and visible exceptions, unsupported fields/rules, stale review versions,
separate grants, access-lock ordering, source revocation, ETag rejection, lost
responses, malformed confirmations, checkpoint crashes/failures, concurrent
same-ID retries, encrypted receipts and restart recovery. No real account,
invitation, device action or audio is used.

Official references checked on 2026-09-20:

- [Recurring events and instances](https://developers.google.com/workspace/calendar/api/guides/recurringevents)
  documents `originalStartTime`, unexpanded exception listings and the warning
  against modifying every instance independently for a following-only change.
- [events.instances](https://developers.google.com/workspace/calendar/api/v3/reference/events/instances)
  documents deleted-instance inclusion, pagination and optional time bounds.
- [events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)
  documents the `iCalUID` filter, unexpanded results and continuation tokens.
- [Event resource](https://developers.google.com/workspace/calendar/api/v3/reference/events)
  documents shared series `iCalUID`, original instance identity, cancelled
  exceptions, recurrence properties and user-supplied event IDs.
- [Versioned resources](https://developers.google.com/workspace/calendar/api/guides/version-resources)
  documents conditional modification using `If-Match` and ETags.
