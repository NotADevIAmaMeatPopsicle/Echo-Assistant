# Calendars on Echo

Connect a calendar integration in Home Assistant first. In the owner workspace,
open **Smart display → Settings → Calendars & cameras → Load sources**. Choose
which calendars appear on the displays. There are three independent choices:

- **Share the calendar:** show its agenda and event details.
- **Allow event creation:** enable New event and reviewed conversation drafts.
- **Allow edits and deletion:** enable supported changes to existing single events.

The last choice starts off, including on existing installations. Home Assistant's
integration must advertise support for each operation. Guest displays remain
read-only even when a calendar has these household permissions.

## Create an event or a repeating schedule

On **My day → New event**, enter the title, dates, time zone and optional location
or notes. You can describe an event to Echo to fill an editable draft. Review it
before pressing **Create event**. A draft is never submitted automatically.

**Repeat** offers daily, weekly, monthly and yearly schedules. Choose an interval
and a total of 2–366 occurrences, including the first event. A monthly schedule on
the 31st skips months without that date; a yearly leap-day schedule skips non-leap
years. Timed repeating events must use Home Assistant's configured time zone so
its calendar integration can keep the intended local time across clock changes.
The form reports a different host time zone before dispatch. All-day events use
an inclusive last day in the form.

Repeating creation uses Home Assistant's calendar WebSocket API because its
ordinary create-event service does not accept recurrence rules. Some integrations
may still reject recurrence; Echo reports that rejection and does not substitute
multiple individual events. Creation is accepted by Home Assistant before the
external calendar may finish syncing. Refresh the agenda to check the result.

## Review, edit or delete

Tap **Details** beside an agenda entry to see its time, calendar, location and
notes. On a calendar approved for changes, **Edit event** opens the same form.
The calendar stays fixed. Review the replacement fields and press **Save changes**.

**Delete…** opens a second confirmation with the event details. **Keep event**
cancels; **Delete event** sends the change. Deletion affects everyone sharing that
calendar. Echo reads the event again before dispatch and refuses a change if its
contents have changed since the displayed version.

Existing recurring series and their individual occurrences remain read-only in
this editor. Use the calendar's own app for those changes, invitations, attendees
and unsupported fields. An integration that supplies no stable event identifier
also remains read-only. Unusually long event fields must be edited in the calendar
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

Synthetic checks cover creation, recurrence, edit/delete permissions, event
freshness, source filtering, guest denial, clock changes, uncertain responses and
restart-safe retry behavior. Touch-browser checks cover the forms, separate owner
grants, deletion confirmation and phone layout. These checks do not establish
that a particular external calendar integration supports every operation.

The implementation follows Home Assistant's
[calendar entity API](https://developers.home-assistant.io/docs/core/entity/calendar/)
and [calendar WebSocket handlers](https://github.com/home-assistant/core/blob/dev/homeassistant/components/calendar/__init__.py).
Invitations, editing existing recurring series, and the Mini's calendar review
screen remain planned work.
