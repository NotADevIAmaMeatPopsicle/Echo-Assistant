# Connect Google Calendar

The owner can connect Google Calendar directly to Echo without routing it through
Home Assistant. Connected calendars appear in **Settings → Calendars & cameras**;
selecting one adds it to **My day** and the existing local agenda/briefing replies.
Nothing is shared just because an account was connected.

Connections default to **read-only** access. An explicit optional Google editing
grant enables reviewed creation, single-event/occurrence changes and original
master-series editing, after the owner separately enables the relevant calendar
permissions in Echo. Simple counted series support reviewed following-only changes;
eligible events have separate guest and notification controls described below.
The existing Home Assistant calendar writer remains independent.

## Configure the installation

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select
   a project and enable **Google Calendar API**. Configure its OAuth consent
   screen. For an external app in Testing, add the Google accounts you plan to use
   as test users. Google may expire Testing-mode refresh tokens after seven days;
   reconnect if the grant expires.
2. Create an OAuth client with application type **Web application**. Do not use
   an Android, TV, browser-extension or service-account credential.
3. Open the owner **Display → Settings → Manage Google calendars → Google OAuth
   setup**. Its suggested callback is the current Echo origin followed by
   `/v1/calendar/google/callback`. Register that exact URI in the Google client,
   including its scheme and port. Use HTTPS for a remote/private hostname, or
   Google's permitted HTTP loopback redirect for local development.
4. Enter the client ID, client secret and callback URI in Echo and save. These are
   your installation's OAuth application credentials, not your Google password.
   The secret is encrypted on the host and is never returned to the UI. Blank
   leaves an existing secret unchanged. Disconnect linked accounts before changing
   the OAuth client or secret.

The callback must be reachable **in the browser doing Google sign-in**. A URL
using `127.0.0.1` points to that browser's own device. For remote use, the browser
must already be allowed through Echo's private HTTPS gateway. Connecting Google
does not expose Echo or Hermes publicly or grant other tailnet members access.
Use a redirect domain permitted by your Google project; production OAuth apps
can have additional verification requirements. Keep HTTP/proxy access logs from
recording callback query strings, which contain short-lived authorization codes.

## Connect, then choose what to share

1. Give the connection a label. Leave optional editing unchecked for read-only
   access, or check it to request creation, editing and deletion. Tap **Connect an account**.
2. Tap **Open Google sign-in**, choose the Google account and approve the requested
   Calendar access. Echo never handles the Google password. The callback tab tells
   you to return to the Echo tab where you started.
3. In that original tab, tap **Finish connecting**. Echo saves the encrypted
   offline grant and loads the calendar inventory. If that read fails, the
   connection remains listed with **Refresh calendar list** to retry.
4. Open **Calendars & cameras → Load sources**, select calendars, and save.
   Household displays can read these selected sources. Guest/Personal display
   grants can narrow them further under their existing access settings.

Keep the original tab open during sign-in. The flow expires after ten minutes;
reloading loses its per-tab proof and requires a new sign-in. The Google response
alone does not link an account: finishing requires the original authenticated
owner principal and random browser proof, including behind a gateway that shares
an owner API credential. Declined, cancelled, replayed and expired flows do not
create connections.

**Refresh calendar list** discovers new or renamed calendars. It does not share
new ones automatically. Calendar IDs sent to displays are local opaque identifiers,
not Google email/calendar IDs. This initial connector is household-owned; separate
private Google sign-in for each Echo personal account remains open. Shared Google
calendars can already be granted read-only to personal accounts.

**Disconnect** removes Echo's stored grant and calendar inventory. In-flight reads
recheck connection and sharing before returning events. Existing sharing selections
become unavailable rather than being reassigned to a different account. You may
also revoke the application in [Google Account permissions](https://myaccount.google.com/permissions).
Disconnecting in Echo does not revoke grants held elsewhere or delete Google events.

## Enable and review changes

For an existing read-only connection, connect again with optional editing selected.
The new connection has its own source IDs; select its calendars and permissions
explicitly before removing the old connection. Existing grants never upgrade
themselves. Google must grant the requested editing scope, and the calendar must
still have writer or owner access at dispatch.

Under **Calendars & cameras**, **Allow event creation** and **Allow edits and
deletion** are separate owner choices. Both default off. Guest and Personal
sessions remain read-only; a household connection does not grant them writing.
The form and confirmation controls are described in [Calendars on Echo](CALENDARS.md).

For a repeating event, choose **Only this occurrence**, **This and following
occurrences**, or **Every occurrence in the series**. Entire-series editing loads the original master dates, time zone,
fields and repeat rule before opening the editor. Moving those dates affects the
whole series, including past events. The PATCH leaves the recurrence rule and
its COUNT unchanged. All-day status stays fixed for a series. Additional recurrence
dates, sub-minute master times and oversized fields require Google's editor.
Existing exceptions remain subject to Google's series behavior; live acceptance
of that behavior is still pending.

Echo sends the reviewed event ETag as `If-Match` when editing or deleting. A
change elsewhere requires a refresh and new review. Ordinary event edits exclude
attendees, omitted attendee data, special event types and provider locks.
Ordinary Google writes request `sendUpdates=none`.

[Following-only changes](GOOGLE_CALENDAR_SERIES.md) review the complete finite
COUNT series before editing or deleting its remaining occurrences. Earlier events
and the remaining count are preserved. Stored exceptions and more complex rules
require Google's editor; a partially completed split is reported without blind retries.

[Guests & invitations](CALENDAR_INVITATIONS.md) is a separate review for organizer-owned
single events or one selected occurrence. It preserves existing guests and requires
an explicit notification choice and confirmation. Google controls delivery; even
its no-notification option cannot guarantee silence. Whole-series invitations
and real-account acceptance remain separate.

An encrypted receipt is saved before dispatch. The same request ID is not sent
again after a timeout or restart, even if the first result is unknown. Inserts
also use a deterministic Google event ID. If completion is unconfirmed, inspect
Google Calendar before starting a new request. Receipts hold digests and status,
not event content, in `local/echo-calendar-receipts.json` and protected backups.

## Storage and limits

Client secrets, refresh tokens, connection labels and the calendar inventory are
encrypted in `local/echo-google-calendar.json` and included in protected backups.
Access tokens and pending sign-ins stay only in memory. Pending flows are pruned
after expiry. Google Calendar events are fetched on demand and are not saved in
this account file, copied into model memory, or sent to web search by agenda replies.

The connector uses PKCE S256 and random one-use OAuth state. Refresh/access tokens
never enter the browser. Only the Google authorization and token hosts and Calendar
API endpoints are used; redirects and environment proxy discovery are disabled
for host requests. Browser sign-in uses Google's official page in a separate tab.

The initial limits are eight connections, 100 calendars per account, and 300
events per requested calendar window. Choose fewer days if that window is too
large. Errors are reported rather than presenting an incomplete page as complete.
Calls to Google require internet access; the existing local Home Assistant path
continues to work independently when its connection is available.

References: [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
[Calendar scopes](https://developers.google.com/workspace/calendar/api/auth),
[calendarList.list](https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list),
and [events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list).

## Verification

Synthetic Python checks cover PKCE, one-use state, per-tab/session completion,
cancel/expiry/declined scopes, encrypted restart, token redaction, revocation during
reads, optional write consent, separate grants, conditional CRUD, original-master
dates, unchanged COUNT, uncertain responses and duplicate protection after restart.
API checks deny Guest/Personal writes and discard revoked-session master reads.
The silent browser checks cover setup, approval/finish, optional write consent,
original-series review, same-ID retry, cancelled reads, phone layout and owner-only
configuration. The preview refuses real sign-in. No Google account was connected
and no real event or invitation was sent. Actual OAuth, reads and reviewed writes
on an approved test calendar remain live-service acceptance items.
