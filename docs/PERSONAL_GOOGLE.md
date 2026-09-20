# Private Google calendars for personal accounts

A person can connect a private Google account and select its calendars while
signed in to their Echo personal account. These connections and selections are
independent of household calendar sharing. My day and personal agenda replies
combine that person's selected private calendars with any household calendars
explicitly shared through their existing account and endpoint grants.

Private Google connections are read-only. ECHO-04 does not enable private event
creation, edits, deletion or invitations. Google sign-in and a real calendar
rehearsal remain unverified; development uses synthetic provider responses only.

## Connect and select

1. The owner first configures the installation's Google web OAuth client using
   [the Google setup guide](GOOGLE_CALENDAR.md). This defines only the OAuth
   application; it does not link the owner's Google account to a person.
2. Sign in to the intended Echo personal account on a permitted screen. Select
   **My Google calendars** beside the personal-session control.
3. Enter a connection label and select **Connect my account**. Follow **Open
   Google sign-in**, choose your own Google account and approve read access.
4. Return to the same Echo tab and select **Finish connecting** while that same
   personal session is still active. Echo loads the calendar inventory. If that
   read fails, use **Refresh calendar list**.
5. Check the calendars to show in your personal agenda, then choose **Save my
   selection**. A new connection selects nothing automatically.

Keep the initiating tab open. Reloading loses its browser proof. Locking,
switching personal accounts, changing account access, or session expiry cancels
pending sign-in. Start again from the intended account. A person can remove
calendars from their selection or disconnect their own connection. Disconnecting
removes its private source selection and stored grant from Echo, without deleting
Google events or changing household grants.

The shared screen and Echo host remain trusted: anyone using an unlocked
personal session can see its selected agenda and manage its private connection.
Lock the personal session when finished. Private storage does not hide data from
the host administrator or an authorized protected-backup restoration.

## Isolation and storage

The host stores private provider state and calendar selection in one encrypted
file, `local/echo-member-google.json`. Each member has a separate namespace with
its own provider accounts, refresh tokens, calendar inventory and selected source
IDs. The registry is limited to 16 member namespaces and 4.5 MB of plaintext;
the encrypted envelope is bounded to 8 MB. Each namespace retains the existing
Google provider limits of eight connections, 100 calendars per connection and
250 KB of provider state. A person can select at most 12 private calendars.

The registry uses Echo's existing host protector and atomic file replacement.
Its protected-backup registration is owned by the application/recovery wiring.
An unreadable registry is preserved and private access fails closed. Member
deletion removes that namespace and clears its volatile provider state; pruning
also removes namespaces whose member no longer exists.

The provider reuses the owner's OAuth client ID, secret and registered callback
URI. It never reuses a household refresh token, linked Google account, calendar
selection or write scope. Only the two existing read scopes are requested.
Even if Google returns a broader previously approved scope, the private account
is recorded as read-only and the personal agenda strips event-write and
invitation references. Private sources are never added to the household source
store, owner source inventory, Guest agenda or another member's inventory.

Tokens, client secrets and OAuth code verifiers never reach browser storage or
Git. The browser retains only an in-memory proof and currently displayed settings;
the dialog clears on session change or expiry and ignores stale requests. Event
contents are fetched on demand and are not stored in the registry or model
memory. Account identifiers returned to the UI are opaque Echo connection IDs;
raw Google calendar addresses are kept on the host.

If the owner changes the OAuth client credentials, pending private flows become
invalid and incompatible private grants require disconnection and reconnection.
Echo does not silently apply a different OAuth client to an old refresh token.
Changing otherwise compatible OAuth configuration invalidates existing flow state
and refreshes the stored application configuration.

## Authorization and stale results

Only an actual `PersonalPrincipal` can use the private API. The server checks the
member ID, endpoint, session nonce and current profile revision. An owner or
Household session must deliberately sign in as a person first. Guest sessions
cannot use the private API. Another member on the same endpoint cannot finish,
cancel or inspect the previous person's pending sign-in, even with its flow ID.

Each private provider has its own volatile OAuth state. The existing public
Google callback dispatches to the private service only when its state matches a
known private flow; otherwise the household connector handles it. Matching does
not guess a member from an endpoint or the last signed-in person. The callback
checks the initiating personal session and application configuration before and
after token exchange. Revocation during exchange discards the grant; tokens are
not persisted until the original session and browser proof finish the flow.

The combined personal source view preserves the existing household/member/device
intersection for shared calendars. It adds only the current member's explicitly
selected private sources. Private-only selection works even when the household
calendar grant list is empty. The combined view exposes no calendar writing
capabilities. Its revision includes shared source selection, private selection,
personal access and Google configuration. Reads recheck that revision and the
session after provider calls, discarding data from a switched account, changed
selection, disconnected provider or expired session.

Service operations acquire the member lock before provider locks. The registry
lock only protects registry reads and atomic persistence; no provider calls are
made while holding that lock. OAuth token exchange permits session cancellation
while the network call is outstanding.

## API and application integration

`MemberGoogle(members, household_google, runtime_root, protector)` owns the
registry, provider namespaces, selections and private OAuth flow context.
`member_google_api.install(app, service, authorize)` registers:

| Method and path below `/v1/member/calendar/google` | Body or purpose |
| --- | --- |
| `GET /` | Private account list, calendar inventory and selection revision. |
| `POST /flows` | `{label, client}`; write-scope requests are rejected. |
| `GET /flows/{id}?client=...` | Read the initiating session's pending status. |
| `DELETE /flows/{id}` | `{client}`; cancel the matching private flow. |
| `POST /flows/{id}/finish` | `{client}`; persist the approved private grant. |
| `POST /accounts/{id}/sync` | Refresh only that person's connection inventory. |
| `DELETE /accounts/{id}` | Disconnect only that person's connection. |
| `PUT /selection` | `{revision, calendars}` with only their private source IDs. |

The first route is exactly `/v1/member/calendar/google`, without a required
trailing slash. Settings return `enabled`, `configured`, `needs_reconnect`,
`read_only`, `revision`, `accounts` and `calendars`, with no OAuth credentials.

The core Google provider's optional `state_store` has `load()` and
`save(document)` methods. Its original validation and provider-size limit remain
authoritative. The namespace adapter handles only encrypted persistence and
member ownership. The original household file path is unchanged.

Application wiring calls `service.callback(state, code, error)` before the
household callback, `cancel_session(principal)` on session lock,
`remove_member(id)` on deletion, and `prune()` during housekeeping. Personal
display and voice-agenda routes use `service.scoped(principal, experiences)`.
The display loads `member-google.js` after `members.js`, with its matching CSS.

## Verification

Run `python -m unittest tests.test_member_google -q` for the focused synthetic
provider checks. They cover read-only OAuth reuse, private state dispatch,
per-tab proof, nonce isolation, independent selections, explicit shared/private
union, no household/Guest/other-member export, encrypted restart, malformed
provider state, no automatic selection, session expiry/deletion, configuration
changes, cancellation during token exchange, late agenda results and the
private-only personal voice-agenda path.

`tools/check_display_member_google.cjs` requires the isolated loopback preview
and intercepts every private API call. It checks the read-only form, explicit
selection after linking, phone layout and removal of stale member data. It
blocks all non-loopback network requests and uses no real sign-in, audio or
calendar write. Application authorization and protected-recovery integration
have separate coordinator-owned seam checks.
