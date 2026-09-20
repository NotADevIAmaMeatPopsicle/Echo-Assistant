"""Bounded, reviewed Google COUNT-series splits with durable at-most-once steps.

Google has no atomic following-only write. We derive the ordinal from the complete
provider instance list, refuse exceptions, conditionally trim the old master, and
insert the remaining series. Receipts never contain calendar/event content.
"""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from .calendar_events import CalendarEvent, EventReference
from .calendar_reference import event_reference
from .experiences import ExperienceConflict, ExperienceUnavailable
from .google_calendar import GoogleRejected
from .google_calendar_write import editable_event
from .home import HomeUnavailable


MAX_COUNT = 366
MAX_PAGES = 16
_COPY_FIELDS = {'summary', 'description', 'location', 'colorId', 'transparency',
                'visibility', 'reminders', 'guestsCanInviteOthers',
                'guestsCanModify', 'guestsCanSeeOtherGuests', 'anyoneCanAddSelf'}
_OUTPUT_FIELDS = {'kind', 'id', 'etag', 'htmlLink', 'created', 'updated', 'creator',
                  'organizer', 'iCalUID', 'sequence', 'start', 'end', 'recurrence',
                  'recurringEventId', 'originalStartTime', 'status', 'eventType',
                  'attendees', 'attendeesOmitted', 'locked'}
_DEFAULTS = {'summary': 'Untitled event', 'description': '', 'location': '',
             'transparency': 'opaque', 'visibility': 'default',
             'reminders': {'useDefault': True}, 'guestsCanInviteOthers': True,
             'guestsCanModify': False, 'guestsCanSeeOtherGuests': True,
             'anyoneCanAddSelf': False}


def _unsupported(detail):
    return ValueError(detail + ' Use Google Calendar for this series.')


def _rule(master):
    rules = master.get('recurrence')
    if not isinstance(rules, list) or len(rules) != 1 or not isinstance(rules[0], str):
        raise _unsupported('Following changes require one finite COUNT rule without extra recurrence dates.')
    raw = rules[0]
    if not raw.startswith('RRULE:'):
        raise _unsupported('Following changes require one finite COUNT rule.')
    parts = raw[6:].split(';')
    values = {}
    for part in parts:
        pair = part.split('=')
        if len(pair) != 2 or pair[0] in values:
            raise _unsupported('The recurrence rule is ambiguous.')
        values[pair[0]] = pair[1]
    if (set(values) - {'FREQ', 'INTERVAL', 'COUNT'} or
            values.get('FREQ') not in {'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'} or
            not re.fullmatch(r'[1-9][0-9]{0,2}', values.get('COUNT', '')) or
            not re.fullmatch(r'[1-9][0-9]{0,1}', values.get('INTERVAL', '1'))):
        raise _unsupported('Only simple daily, weekly, monthly or yearly COUNT rules are supported.')
    count = int(values['COUNT'])
    if count > MAX_COUNT:
        raise _unsupported('This series exceeds the 366-occurrence review limit.')
    return raw, count


def _with_count(rule, count):
    return 'RRULE:' + ';'.join('COUNT=' + str(count) if part.startswith('COUNT=') else part
                              for part in rule[6:].split(';'))


def _point(value, all_day, zone):
    if not isinstance(value, dict):
        raise _unsupported('An occurrence has incomplete dates.')
    try:
        if all_day:
            if set(value) - {'date', 'timeZone'} or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['date']):
                raise ValueError()
            return date.fromisoformat(value['date'])
        if set(value) - {'dateTime', 'timeZone'} or value.get('timeZone', zone.key) != zone.key:
            raise ValueError()
        instant = datetime.fromisoformat(value['dateTime'].replace('Z', '+00:00'))
        if instant.tzinfo is None or instant.second or instant.microsecond:
            raise ValueError()
        return instant.astimezone(zone)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise _unsupported('This series has unsupported dates, sub-minute times or time zones.') from None


def _identity(point):
    # Datetime equality within one ZoneInfo ignores fold; compare actual instants.
    return point.timestamp() if isinstance(point, datetime) else point.toordinal()


def _wall(point):
    return point.replace(tzinfo=None) if isinstance(point, datetime) else point


def _template(item):
    if not editable_event(item) or set(item) - (_COPY_FIELDS | _OUTPUT_FIELDS):
        raise _unsupported('Guests, special events and unsupported provider fields cannot be split here.')
    if item.get('status', 'confirmed') != 'confirmed':
        raise _unsupported('Tentative or cancelled occurrences cannot be split here.')
    for key, maximum in (('summary', 200), ('description', 2000), ('location', 300)):
        if not isinstance(item.get(key, _DEFAULTS[key]), str) or len(item.get(key, _DEFAULTS[key])) > maximum:
            raise _unsupported('This series has fields longer than the display editor supports.')
    return {key: deepcopy(item.get(key, _DEFAULTS.get(key))) for key in sorted(_COPY_FIELDS)}


def _no_exceptions(adapter, account, calendar, master, zone):
    # Unlike expanded instances, this endpoint returns exception records even
    # when their current visible fields happen to equal the master defaults.
    uid = master.get('iCalUID')
    if not isinstance(uid, str) or not 0 < len(uid) <= 2048 or any(ord(char) < 32 for char in uid):
        raise _unsupported('The original series has no usable iCalendar identity for exception review.')
    rows, pages, page = [], set(), None
    for _ in range(MAX_PAGES):
        result = adapter.google.get(account['id'], adapter.path(calendar),
                                    {'iCalUID': uid, 'singleEvents': 'false', 'showDeleted': 'true',
                                     'maxResults': MAX_COUNT + 1, 'timeZone': zone.key,
                                     **({'pageToken': page} if page else {})})
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            raise HomeUnavailable('Google exception review is incomplete. No change was sent.')
        rows.extend(result['items'])
        if len(rows) > 1:
            raise _unsupported('This series has stored exceptions or ambiguous iCalendar identities.')
        page = result.get('nextPageToken')
        if not page:
            break
        if not isinstance(page, str) or len(page) > 2048 or page in pages:
            raise HomeUnavailable('Google exception pagination is invalid. No change was sent.')
        pages.add(page)
    else:
        raise HomeUnavailable('Google exception review did not finish. No change was sent.')
    if len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get('id') != master['id']:
        raise _unsupported('Google could not confirm this series is free of stored exceptions.')
    if rows[0].get('etag') != master['etag'] or rows[0].get('recurringEventId'):
        raise ExperienceConflict('The original series changed during exception review. Refresh the agenda.')


def _snapshot(adapter, account, calendar, reference):
    selected = adapter.current(account, calendar, reference)
    if not selected.get('recurringEventId') or selected.get('recurrence'):
        raise _unsupported('Choose an exact occurrence to change this and following events.')
    master = adapter.google.get(account['id'], adapter.path(calendar, selected['recurringEventId']))
    if (not editable_event(master) or master.get('recurringEventId') or
            master.get('id') != selected['recurringEventId']):
        raise _unsupported('The original series is unavailable or cannot be split here.')
    rule, count = _rule(master)
    template = _template(master)
    try:
        zone = ZoneInfo(master.get('start', {}).get('timeZone') or calendar['timezone'])
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise _unsupported('This series has an unsupported time zone.') from None
    all_day = 'date' in master['start']
    master_start = _point(master['start'], all_day, zone)
    master_end = _point(master['end'], all_day, zone)
    duration = _wall(master_end) - _wall(master_start)
    instances = []
    page = None
    seen_pages = set()
    for _ in range(MAX_PAGES):
        result = adapter.google.get(account['id'], adapter.path(calendar, master['id']) + '/instances',
                                    {'showDeleted': 'true', 'maxResults': MAX_COUNT + 1,
                                     'timeZone': zone.key, **({'pageToken': page} if page else {})})
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            raise HomeUnavailable('Google returned an incomplete series. No change was sent.')
        instances.extend(result['items'])
        if len(instances) > count:
            raise _unsupported('The provider instances do not match the finite COUNT rule.')
        page = result.get('nextPageToken')
        if not page:
            break
        if not isinstance(page, str) or len(page) > 2048 or page in seen_pages:
            raise HomeUnavailable('Google series pagination is invalid. No change was sent.')
        seen_pages.add(page)
    else:
        raise HomeUnavailable('Google series pagination did not finish. No change was sent.')
    if len(instances) != count:
        raise _unsupported('The complete provider instances do not match the finite COUNT rule.')
    keyed = []
    ids = set()
    originals = set()
    for item in instances:
        if not isinstance(item, dict) or item.get('status') == 'cancelled':
            raise _unsupported('This series has a cancelled occurrence or incomplete instance.')
        if (item.get('recurringEventId') != master['id'] or item.get('recurrence') or
                _template(item) != template):
            raise _unsupported('This series has changed occurrence fields or other exceptions.')
        original = _point(item.get('originalStartTime'), all_day, zone)
        start = _point(item.get('start'), all_day, zone)
        end = _point(item.get('end'), all_day, zone)
        identity = _identity(original)
        if identity != _identity(start) or _wall(end) - _wall(start) != duration:
            raise _unsupported('This series has a moved occurrence or changed duration.')
        if item['id'] in ids or identity in originals:
            raise _unsupported('This series contains ambiguous occurrence identities.')
        ids.add(item['id'])
        originals.add(identity)
        keyed.append((identity, item))
    keyed.sort(key=lambda pair: pair[0])
    if keyed[0][0] != _identity(master_start):
        raise _unsupported('The series does not begin with its original master occurrence.')
    ordered = [item for _, item in keyed]
    matches = [index for index, item in enumerate(ordered) if item['id'] == selected['id']]
    if len(matches) != 1 or ordered[matches[0]]['etag'] != selected['etag']:
        raise ExperienceConflict('The selected occurrence changed during review. Refresh the agenda.')
    _no_exceptions(adapter, account, calendar, master, zone)
    # A master change during pagination invalidates this entire snapshot.
    latest = adapter.google.get(account['id'], adapter.path(calendar, master['id']))
    if latest != master:
        raise ExperienceConflict('The original series changed during review. Refresh the agenda.')
    version = hashlib.sha256(json.dumps({'master': master, 'instances': ordered}, sort_keys=True).encode()).hexdigest()
    prior_count = matches[0]
    return {'master': master, 'selected': selected, 'rule': rule, 'count': count,
            'prior_count': prior_count, 'remaining_count': count - prior_count,
            'version': version, 'zone': zone, 'all_day': all_day}


def _editor(snapshot, entity):
    item = snapshot['selected']
    fields = {}
    for name in ('start', 'end'):
        point = _point(item[name], snapshot['all_day'], snapshot['zone'])
        fields[name] = point.isoformat() if snapshot['all_day'] else point.strftime('%Y-%m-%dT%H:%M')
        fields[name + '_fold'] = point.fold if isinstance(point, datetime) else 0
    return CalendarEvent.model_validate({'calendar': entity, 'title': item.get('summary', 'Untitled event'),
                                        'description': item.get('description', ''), 'location': item.get('location', ''),
                                        'all_day': snapshot['all_day'], 'timezone': snapshot['zone'].key,
                                        **fields}).model_dump()


def review_following(adapter, reference, revision):
    """Review the selected occurrence, full finite series and original master."""
    reference = EventReference.model_validate(reference)
    if not adapter.google or not adapter.google.owns(reference.calendar):
        raise ValueError('Following-series review is available for direct Google calendars')
    with adapter.access_lock, adapter.writer.lock, adapter.writer.experiences.store.lock, adapter.google.lock:
        account, calendar = adapter.policy(reference.calendar, revision)
        adapter.provider(account, calendar)
        snapshot = _snapshot(adapter, account, calendar, reference)
        editor = _editor(snapshot, reference.calendar)
        reviewed = event_reference(adapter.google.event_row(snapshot['selected']), reference.calendar, reference.on_date)
        reviewed['following_version'] = snapshot['version']
        adapter.policy(reference.calendar, revision)
        return {'reference': reviewed, 'editor_event': editor, 'repeat_summary': snapshot['rule'],
                'prior_count': snapshot['prior_count'], 'remaining_count': snapshot['remaining_count'],
                'following_start_locked': False, 'provider': 'google'}


def _result(receipt):
    step = receipt.get('series_step', 'unknown')
    status = receipt['status'] if receipt['status'] in {'accepted', 'rejected'} else 'unconfirmed'
    if status == 'accepted':
        message = 'Google accepted the change to this and following occurrences. Earlier occurrences were retained. Refresh the agenda.'
    elif status == 'rejected':
        message = 'Google rejected the first series change. No later step was sent. Refresh and review the series in Google Calendar.'
    elif step in {'trim_accepted', 'insert_blocked', 'insert_rejected'}:
        message = ('The original series was shortened, but the replacement series was not created. '
                   'The earlier occurrences remain. Restore or finish the following occurrences in Google Calendar.')
    elif step in {'insert_pending', 'insert_unconfirmed'}:
        message = ('The original series was shortened. Creation of the replacement series is unconfirmed. '
                   'Check Google Calendar for both series before making another change.')
    else:
        message = 'The original series change is unconfirmed. Check Google Calendar before making another change.'
    if status != 'accepted':
        message += ' This request will not send or resume any write again.'
    return {'status': status, 'capability': 'calendar', 'text': message,
            'series_step': step, 'prior_count': receipt.get('prior_count'),
            'remaining_count': receipt.get('remaining_count')}


def change_following(adapter, operation, reference, event, revision, request_id):
    """Apply one reviewed following change; a retry only reads its saved receipt."""
    if operation not in {'edit', 'delete'} or not re.fullmatch(r'[a-f0-9]{32}', request_id):
        raise ValueError('Invalid following-series change')
    reference = EventReference.model_validate(reference)
    if not adapter.google or not adapter.google.owns(reference.calendar):
        raise ValueError('Following-series changes are available for direct Google calendars')
    reviewed_version = getattr(reference, 'following_version', None)
    if not reviewed_version:
        raise ValueError('Load and review this and following occurrences before changing the series')
    replacement = CalendarEvent.model_validate(event) if operation == 'edit' else None
    if replacement and (replacement.calendar != reference.calendar or replacement.recurrence):
        raise ValueError('Keep the calendar and existing repeat pattern')
    if operation == 'delete' and event is not None:
        raise ValueError('Deletion does not accept replacement fields')
    intent = {'provider': 'google', 'operation': operation, 'scope': 'following',
              'reference': reference.model_dump(), 'event': replacement.model_dump() if replacement else None}
    digest = hashlib.sha256(json.dumps(intent, sort_keys=True).encode()).hexdigest()
    key = hashlib.sha256(request_id.encode()).hexdigest()
    writer = adapter.writer
    with adapter.access_lock, writer.lock, writer.experiences.store.lock, adapter.google.lock:
        account, calendar = adapter.policy(reference.calendar, revision)
        prior = writer.receipts.get(key)
        if prior:
            if prior['digest'] != digest:
                raise ExperienceConflict('This request identifier belongs to another calendar change')
            return _result(prior)
        if len(writer.receipts) >= 4096:
            raise ExperienceUnavailable('Calendar receipt capacity reached')
        adapter.provider(account, calendar)
        snapshot = _snapshot(adapter, account, calendar, reference)
        if snapshot['version'] != reviewed_version:
            raise ExperienceConflict('The original series or an occurrence changed. Refresh and review following occurrences again.')
        if replacement and (replacement.all_day != snapshot['all_day'] or replacement.timezone != snapshot['zone'].key):
            raise ValueError('Keep the series all-day setting and time zone when rescheduling following occurrences')
        split = operation == 'edit' and snapshot['prior_count'] > 0

        def policy():
            adapter.policy(reference.calendar, revision)
            if split:
                adapter.policy(reference.calendar, revision, create=True)

        policy()
        token, _ = adapter.google.token(account['id'])
        policy()
        master = snapshot['master']
        master_path = adapter.path(calendar, master['id'])
        if snapshot['prior_count']:
            method, payload = 'PATCH', {'recurrence': [_with_count(snapshot['rule'], snapshot['prior_count'])]}
        elif replacement:
            method, payload = 'PATCH', adapter.fields(replacement)
        else:
            method, payload = 'DELETE', None
        receipt = {'digest': digest, 'status': 'pending', 'series_step': 'trim_pending',
                   'prior_count': snapshot['prior_count'], 'remaining_count': snapshot['remaining_count']}

        def save(stage, status):
            nonlocal receipt
            receipt = {**receipt, 'series_step': stage, 'status': status}
            writer.commit({**writer.receipts, key: receipt})

        def dispatch(verb, path, body, etag=None):
            options = {'headers': {'Authorization': 'Bearer ' + token, **({'If-Match': etag} if etag else {})},
                       'params': {'sendUpdates': 'none'}}
            if body is not None:
                options['json'] = body
            result = adapter.google.transport.json(verb, 'https://www.googleapis.com/calendar/v3/' + path, **options)
            if verb != 'DELETE':
                expected = body['id'] if verb == 'POST' else path.rsplit('/', 1)[1]
                if not editable_event(result) or result['id'] != expected:
                    raise HomeUnavailable('Google returned an unexpected series result.')
                if 'recurrence' in body and result.get('recurrence') != body['recurrence']:
                    raise HomeUnavailable('Google did not confirm the requested series count.')

        save('trim_pending', 'pending')
        try:
            dispatch(method, master_path, payload, master['etag'])
        except GoogleRejected:
            save('trim_rejected', 'rejected')
        except HomeUnavailable:
            save('trim_unconfirmed', 'unconfirmed')
        else:
            if not split:
                save('complete', 'accepted')
            else:
                save('trim_accepted', 'pending')
                try:
                    policy()
                    adapter.provider(account, calendar)
                    policy()
                except (HTTPException, PermissionError, ExperienceConflict, HomeUnavailable):
                    save('insert_blocked', 'unconfirmed')
                else:
                    new_series = {field: deepcopy(master[field]) for field in _COPY_FIELDS if field in master}
                    new_series.update(adapter.fields(replacement))
                    new_series['id'] = 'echo' + hashlib.sha256(('following:' + request_id).encode()).hexdigest()
                    new_series['recurrence'] = [_with_count(snapshot['rule'], snapshot['remaining_count'])]
                    save('insert_pending', 'pending')
                    try:
                        dispatch('POST', adapter.path(calendar), new_series)
                    except GoogleRejected:
                        save('insert_rejected', 'unconfirmed')
                    except HomeUnavailable:
                        save('insert_unconfirmed', 'unconfirmed')
                    else:
                        save('complete', 'accepted')
        try:
            policy()
        except (HTTPException, PermissionError, ExperienceConflict, HomeUnavailable):
            raise ExperienceUnavailable('Calendar access changed during the request. Check Google Calendar; any retry must use the same request identifier.') from None
        return _result(receipt)
