# Calendars on Echo

Connect a calendar integration in Home Assistant or [Google Calendar directly](GOOGLE_CALENDAR.md).
In the owner workspace,
open **Smart display → Settings → Calendars & cameras → Load sources**. Choose
which calendars appear on the displays. There are three independent choices:

- **Share the calendar:** show its agenda and event details.
- **Allow event creation:** enable New event and reviewed conversation drafts.
- **Allow edits and deletion:** enable supported changes to existing events and occurrences.

The last choice starts off, including on existing installations. Home Assistant's
integration must advertise support for each operation. Direct Google changes
also require optional editing consent and current provider writer/owner access.
Guest and Personal sessions remain read-only even when a calendar has these
household permissions.

Direct Google connections default to read-only. Editing consent does not select
calendars or enable either Echo write grant automatically.

## Create an event or a repeating schedule

On **My day → New event**, enter the title, dates, time zone and optional location
or notes. You can describe an event to Echo to fill an editable draft. Review it
before pressing **Create event**. A draft is never submitted automatically.

**Repeat** offers daily, weekly, monthly and yearly schedules. Choose an interval
and a total of 2–366 occurrences, including the first event. A monthly schedule on
the 31st skips months without that date; a yearly leap-day schedule skips non-leap
years. Through Home Assistant, timed repeating events must use its configured time zone so
its calendar integration can keep the intended local time across clock changes.
The form reports a different host time zone before dispatch. All-day events use
an inclusive last day in the form.

Repeating creation uses Home Assistant's calendar WebSocket API because its
ordinary create-event service does not accept recurrence rules. Some integrations
may still reject recurrence; Echo reports that rejection and does not substitute
multiple individual events. Creation is accepted by Home Assistant before the
external calendar may finish syncing. Direct Google creation uses Google's event
API with the reviewed time zone and repeat rule. Refresh the agenda to check the result.

## Review, edit or delete

Tap **Details** beside an agenda entry to see its time, calendar, location and
notes. On a calendar approved for changes, **Edit event** opens the same form.
The calendar stays fixed. Review the replacement fields and press **Save changes**.

**Delete…** opens a second confirmation with the event details. **Keep event**
cancels; **Delete event** sends the change. Deletion affects everyone sharing that
calendar. Echo reads the event again before dispatch and refuses a change if its
contents have changed since the displayed version.

### Repeating events

Opening a repeating event adds an **Apply to** choice before editing or deletion.
For the Home Assistant integration:

| Scope | Edit | Delete |
| --- | --- | --- |
| Only this occurrence | Change this occurrence without changing its siblings. | Remove this occurrence. |
| This and following occurrences | Change the selected occurrence and later events, preserving the repeat pattern. | Remove the selected occurrence and later events. |
| Every occurrence in the series | Use the calendar's app; Echo has no master-event view. | Remove the whole series, including past events and changed exceptions, after confirmation. |

The integration must supply an exact occurrence identifier for occurrence or
following changes. Echo does not infer one from the displayed date. If only a
stable series identifier is available, the editor can offer whole-series deletion.
Google Calendar currently advertises creation and deletion through Home Assistant,
but not editing; Echo follows the integration's capabilities.

For **following** edits, keep the all-day setting and use Home Assistant's time
zone. If the series has a fixed occurrence count, or its repeat rule is unavailable,
its start stays fixed. You can change the title, notes, location and end time.
This avoids a confirmed issue in Home Assistant's `ical` 14.2.0 dependency, where
moving a counted series later can discard its final occurrence. Move one occurrence
instead, or reschedule the series in its calendar app. Replacing repeat rules,
editing the master event, and invitations/attendees remain unsupported through
the Home Assistant path.

Direct Google supports **Only this occurrence**, **This and following occurrences**
and **Every occurrence in the series** for edits and deletion. Whole-series editing first loads the original
master dates and fields, even when you selected a later occurrence. Review those
dates and the displayed repeat pattern; the change includes past and future events.
Moving the entire series preserves the existing recurrence rule and COUNT. The
all-day setting stays fixed, and recurrence rules cannot be replaced here.
[Following-only changes](GOOGLE_CALENDAR_SERIES.md) support simple finite COUNT
rules after a full series review; exceptions and more complex patterns require
Google's editor. [Guest changes](CALENDAR_INVITATIONS.md) use a separate attendee
and notification review. Ordinary event edits continue to reject attendee events.

An integration that supplies no stable event identifier remains read-only.
Unusually long event fields must be edited in the calendar
app so the compact display editor does not truncate their contents.

## Connection loss and saved data

Calendar writes use an encrypted receipt saved before dispatch. Retrying the same
request, including after a host restart, does not send it twice. When the connection
is lost after dispatch, Echo reports an unconfirmed result. Check the calendar
before starting another request. Receipts contain request digests and status rather
than event titles, notes or calendar credentials, and are included in recovery
archives. Display pairing does not expose the Home Assistant token.

Changing source permissions does not change the calendar itself. Calendar
permissions and event contents are rechecked for each edit or deletion. All model
assisted drafts still require explicit review. No event writes are permitted in
Echo's validation deployment mode.

## Verification and limits

Synthetic checks cover creation, recurrence scopes, edit/delete permissions, event
freshness, source filtering, guest denial, clock changes, uncertain responses and
restart-safe retry behavior. Touch-browser checks cover the forms, separate owner
grants, series deletion confirmation, fixed-start controls and phone layout.
Direct Google checks additionally cover optional OAuth writes, provider ETags,
original-master dates, unchanged recurrence payloads, malformed responses and
revocation during a request. All provider checks use synthetic responses.
An in-memory check of the actual `ical` 14.2.0 engine confirms that the supported
following detail/duration edits preserve the event count, single moves preserve
sibling events, and following/whole-series deletion handles exceptions. No real
calendar was changed. These checks do not establish
that a particular external calendar integration supports every operation.

The implementation follows Home Assistant's
[calendar entity API](https://developers.home-assistant.io/docs/core/entity/calendar/)
and [calendar WebSocket handlers](https://github.com/home-assistant/core/blob/dev/homeassistant/components/calendar/__init__.py).
Google invitation and following-only software checks use synthetic providers.
Real Google OAuth and reviewed event changes remain live-service acceptance
items. [Mini calendar review](ROUND_CALENDAR.md) supports paginated drafts and a
separate creation confirmation; its firmware installation and physical acceptance
remain pending.
