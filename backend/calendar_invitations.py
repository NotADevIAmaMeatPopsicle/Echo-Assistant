"""Explicit Google guest review, volatile drafts and durable at-most-once dispatch."""
from copy import deepcopy
import hashlib
import hmac
import json
import re
import secrets
from threading import RLock
import time
from typing import Literal

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .calendar_events import EventReference
from .calendar_reference import event_version
from .experiences import ExperienceConflict, ExperienceUnavailable
from .google_calendar import GoogleRejected
from .google_calendar_write import GoogleCalendarWriter, editable_event
from .home import HomeUnavailable


MAX_GUESTS = 200
TTL_SECONDS = 300
MAX_PENDING = 64
NOTIFICATIONS = {
    'all': 'Google sends update notifications to all guests, including invitations for added guests and cancellations for removed guests.',
    'externalOnly': 'Google sends notifications only to guests who do not use Google Calendar. Google decides which guests qualify; this is not a custom recipient list.',
    'none': 'Requests no update notifications. Google warns that some emails may still be sent and guests may miss calendar updates or lose synchronization. This does not guarantee a silent change.',
}


def email_address(value):
    if not isinstance(value, str) or len(value) > 254 or not re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", value):
        raise ValueError('Use a complete email address without spaces')
    local, domain = value.rsplit('@', 1)
    if len(local) > 64 or local.startswith('.') or local.endswith('.') or '..' in value or any(
            not part or part.startswith('-') or part.endswith('-') or len(part) > 63 for part in domain.split('.')):
        raise ValueError('Use a complete email address without spaces')
    return value


def invitation_event(item):
    """Separate eligibility; ordinary writes continue to reject every guest event."""
    if (not isinstance(item, dict) or not isinstance(item.get('organizer'), dict)
            or item['organizer'].get('self') is not True):
        return False
    # A selected recurrence instance is explicit; never infer a master-series change.
    if item.get('recurrence') or item.get('attendeesOmitted'):
        return False
    attendees = item.get('attendees', [])
    if not isinstance(attendees, list) or len(attendees) > MAX_GUESTS:
        return False
    try:
        if len(json.dumps(item).encode()) > 131072:
            return False
        seen = set()
        for attendee in attendees:
            if not isinstance(attendee, dict):
                return False
            email = email_address(attendee.get('email')).casefold()
            if email in seen:
                return False
            seen.add(email)
        return editable_event({**item, 'attendees': []})
    except (ValueError, TypeError):
        return False


def reference_for(item, calendar, on_date):
    """Provider-derived invitation reference without making normal edits available."""
    from .calendar_reference import event_reference
    row = {'uid': item['id'], '_google': True, '_google_etag': item['etag']}
    if item.get('recurringEventId'):
        row['recurrence_id'] = item['recurringEventId']
    return event_reference(row, calendar, on_date)


class ReadInvitations(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    reference: EventReference
    revision: int = Field(ge=0)


class ReviewInvitations(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    read_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    add: list[str] = Field(default_factory=list, max_length=MAX_GUESTS)
    remove: list[str] = Field(default_factory=list, max_length=MAX_GUESTS)
    send_updates: Literal['all', 'externalOnly', 'none']

    @field_validator('add', 'remove')
    @classmethod
    def addresses(cls, values):
        checked = [email_address(v) for v in values]
        if len({v.casefold() for v in checked}) != len(checked):
            raise ValueError('List each guest only once')
        return checked


class ConfirmInvitations(ReadInvitations):
    review_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    review_proof: str = Field(pattern=r'^[a-f0-9]{64}$')
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('Explicit confirmation is required')
        return value


def guest_view(attendee):
    return {'email': attendee['email'], 'display_name': str(attendee.get('displayName') or '')[:200],
            'response_status': str(attendee.get('responseStatus') or 'needsAction')[:40],
            'optional': attendee.get('optional') is True, 'resource': attendee.get('resource') is True,
            'protected': attendee.get('self') is True or attendee.get('organizer') is True}


def event_view(item):
    return {'title': str(item.get('summary') or 'Untitled event')[:300],
            'start': deepcopy(item['start']), 'end': deepcopy(item['end']),
            'scope': 'occurrence' if item.get('recurringEventId') else 'single'}


class CalendarInvitations:
    def __init__(self, writer, clock=time.time):
        self.writer, self.clock, self.lock = writer, clock, RLock()
        self.reads, self.reviews = {}, {}

    def prune(self):
        with self.lock:
            now = self.clock()
            self.reads = {k: v for k, v in self.reads.items() if v['expires_at'] > now}
            self.reviews = {k: v for k, v in self.reviews.items() if v['expires_at'] > now}

    def pending(self, entries, identifier, binding):
        self.prune()
        found = entries.get(identifier)
        if not found or found['expires_at'] <= self.clock() or not hmac.compare_digest(found['binding'], binding):
            raise ExperienceConflict('This invitation review expired or belongs to another session. Open the event again.')
        return found

    @staticmethod
    def current(adapter, account, calendar, reference):
        item = adapter.google.get(account['id'], adapter.path(calendar, reference.uid))
        if not invitation_event(item):
            raise ValueError('Use Google Calendar for this event: complete guest data and organizer access are required; whole-series guest changes are not supported here.')
        row = {'uid': item['id'], '_google': True, '_google_etag': item['etag']}
        if (item['id'] != reference.uid or event_version(row) != reference.version
                or (item.get('recurringEventId') or None) != reference.recurrence_id):
            raise ExperienceConflict('The event or its guests changed elsewhere. Refresh the agenda and review again.')
        return item

    def read(self, body, binding, validate=None, access_lock=None):
        body = ReadInvitations.model_validate(body)
        adapter = GoogleCalendarWriter(self.writer, validate, access_lock)
        if not adapter.google:
            raise PermissionError('Google Calendar invitations are unavailable')
        with adapter.access_lock, self.writer.lock, self.writer.experiences.store.lock, adapter.google.lock, self.lock:
            account, calendar = adapter.policy(body.reference.calendar, body.revision)
            self.prune()
            if len(self.reads) + len(self.reviews) >= MAX_PENDING:
                raise ExperienceUnavailable('Invitation review capacity reached. Wait five minutes before opening another review.')
            adapter.provider(account, calendar)
            item = self.current(adapter, account, calendar, body.reference)
            adapter.policy(body.reference.calendar, body.revision)
            identifier, expiry = secrets.token_hex(16), self.clock() + TTL_SECONDS
            self.reads[identifier] = {'binding': binding, 'reference': body.reference.model_dump(),
                                     'revision': body.revision, 'item': deepcopy(item), 'expires_at': expiry}
            return {'read_id': identifier, 'event': event_view(item),
                    'attendees': [guest_view(a) for a in item.get('attendees', [])],
                    'notification_choices': deepcopy(NOTIFICATIONS), 'expires_at': expiry}

    def review(self, body, binding, validate=None, access_lock=None):
        body = ReviewInvitations.model_validate(body)
        adapter = GoogleCalendarWriter(self.writer, validate, access_lock)
        if not adapter.google:
            raise PermissionError('Google Calendar invitations are unavailable')
        with adapter.access_lock, self.writer.lock, self.writer.experiences.store.lock, adapter.google.lock, self.lock:
            draft = self.pending(self.reads, body.read_id, binding)
            reference = EventReference.model_validate(draft['reference'])
            account, calendar = adapter.policy(reference.calendar, draft['revision'])
            adapter.provider(account, calendar)
            item = self.current(adapter, account, calendar, reference)
            old = {a['email'].casefold(): a for a in item.get('attendees', [])}
            added = {v.casefold(): v for v in body.add}
            removed = {v.casefold() for v in body.remove}
            if not added and not removed:
                raise ValueError('Add or remove a guest before reviewing')
            if set(added) & (set(old) | removed) or not removed <= set(old):
                raise ValueError('Add new guests and remove only listed existing guests; a guest cannot appear in both lists')
            if any(guest_view(old[v])['protected'] for v in removed):
                raise ValueError('The organizer and this account cannot be removed here')
            attendees = [deepcopy(a) for key, a in old.items() if key not in removed]
            attendees.extend({'email': value} for value in added.values())
            if len(attendees) > MAX_GUESTS:
                raise ValueError('Use Google Calendar for more than 200 guests')
            self.prune()
            previous = draft.get('review_id')
            if not previous and len(self.reads) + len(self.reviews) >= MAX_PENDING:
                raise ExperienceUnavailable('Invitation review capacity reached. Open the event again later.')
            adapter.policy(reference.calendar, draft['revision'])
            identifier, proof, request_id = secrets.token_hex(16), secrets.token_hex(32), secrets.token_hex(16)
            expiry = min(draft['expires_at'], self.clock() + TTL_SECONDS)
            response = {'review_id': identifier, 'review_proof': proof, 'request_id': request_id,
                        'reference': draft['reference'], 'revision': draft['revision'], 'expires_at': expiry,
                        'event': event_view(item), 'attendees': [guest_view(a) for a in attendees],
                        'added': list(added.values()), 'removed': [old[v]['email'] for v in sorted(removed)],
                        'send_updates': body.send_updates, 'notification_effect': NOTIFICATIONS[body.send_updates],
                        'affected_guests': [a['email'] for a in item.get('attendees', [])] + list(added.values())}
            confirmation = {k: response[k] for k in ('review_id', 'review_proof', 'request_id', 'reference', 'revision')}
            confirmation['confirmed'] = True
            self.reviews.pop(previous, None)
            self.reviews[identifier] = {'binding': binding, 'expires_at': expiry, 'confirmation': confirmation,
                                        'attendees': attendees, 'etag': item['etag'], 'send_updates': body.send_updates}
            draft['review_id'] = identifier
            return deepcopy(response)

    @staticmethod
    def digest(body, binding):
        return hashlib.sha256(json.dumps({'operation': 'google_invitations', 'binding': binding,
            'confirmation': body.model_dump()}, sort_keys=True).encode()).hexdigest()

    def confirm(self, body, binding, validate=None, access_lock=None):
        body = ConfirmInvitations.model_validate(body)
        adapter = GoogleCalendarWriter(self.writer, validate, access_lock)
        if not adapter.google:
            raise PermissionError('Google Calendar invitations are unavailable')
        key = hashlib.sha256(body.request_id.encode()).hexdigest()
        digest = self.digest(body, binding)
        with adapter.access_lock, self.writer.lock, self.writer.experiences.store.lock, adapter.google.lock, self.lock:
            account, calendar = adapter.policy(body.reference.calendar, body.revision)
            prior = self.writer.receipts.get(key)
            if prior:
                if not hmac.compare_digest(prior['digest'], digest):
                    raise ExperienceConflict('This request identifier belongs to another reviewed change')
                return self.result(prior['status'])
            review = self.pending(self.reviews, body.review_id, binding)
            if body.model_dump() != review['confirmation']:
                raise ExperienceConflict('The confirmation does not match the reviewed guests and notification choice')
            if len(self.writer.receipts) >= 4096:
                raise ExperienceUnavailable('Calendar receipt capacity reached')
            adapter.provider(account, calendar)
            item = self.current(adapter, account, calendar, body.reference)
            if item['etag'] != review['etag']:
                raise ExperienceConflict('The event changed. Review its guests again.')
            token, _ = adapter.google.token(account['id'])
            adapter.policy(body.reference.calendar, body.revision)
            self.pending(self.reviews, body.review_id, binding)
            receipt = {'digest': digest, 'status': 'pending'}
            self.writer.commit({**self.writer.receipts, key: receipt})
            try:
                result = adapter.google.transport.json('PATCH', 'https://www.googleapis.com/calendar/v3/' + adapter.path(calendar, item['id']),
                    headers={'Authorization': 'Bearer ' + token, 'If-Match': review['etag']},
                    params={'sendUpdates': review['send_updates']}, json={'attendees': deepcopy(review['attendees'])})
                expected = {a['email'].casefold() for a in review['attendees']}
                if (not invitation_event(result) or result['id'] != item['id']
                        or {a['email'].casefold() for a in result.get('attendees', [])} != expected):
                    raise HomeUnavailable('Google returned an unexpected guest list')
                status = 'accepted'
            except GoogleRejected:
                status = 'rejected'
            except HomeUnavailable:
                status = 'unconfirmed'
            self.writer.commit({**self.writer.receipts, key: {**receipt, 'status': status}})
            self.reviews.pop(body.review_id, None)
            try:
                adapter.policy(body.reference.calendar, body.revision)
            except (HTTPException, PermissionError, ExperienceConflict, HomeUnavailable):
                raise ExperienceUnavailable('Calendar access changed during confirmation. Check Google Calendar; retry only the same request identifier.') from None
            return self.result(status)

    @staticmethod
    def result(status):
        return {'status': status if status in {'accepted', 'rejected'} else 'unconfirmed', 'capability': 'calendar',
                'text': ('Google accepted the guest changes and requested notification choice. Refresh the agenda. Delivery is not verified.' if status == 'accepted' else
                         'Google rejected the guest changes. Refresh the agenda and review again.' if status == 'rejected' else
                         'Completion is unconfirmed. Check Google Calendar before making another change. This request will not be sent again.')}


def install(app, writer, authorize, displays=None, briefing=None):
    service = CalendarInvitations(writer)
    app.state.calendar_invitations = service

    def context(request, principal):
        from .members import PersonalPrincipal
        before = displays.profile_for(principal) if displays else None
        if isinstance(principal, PersonalPrincipal) or before and (
                before['profile']['mode'] != 'household' or before['profile'].get('personal')):
            raise HTTPException(403, 'Guest invitations are available only to the owner and permitted Household displays')
        if principal == 'round':
            raise HTTPException(403, 'Use the owner workspace or a permitted Household display')
        def validate():
            if authorize(request) != principal or displays and displays.profile_for(principal) != before:
                raise ExperienceConflict('Account access changed. Open the event again.')
        binding = hashlib.sha256(json.dumps({'principal': str(principal), 'profile': before}, sort_keys=True).encode()).hexdigest()
        access_lock = (displays.members.lock if displays.members else displays.lock) if displays else None
        return binding, validate, access_lock

    def call(action):
        try:
            return action()
        except ExperienceConflict as error:
            raise HTTPException(409, str(error)) from None
        except (HomeUnavailable, ExperienceUnavailable) as error:
            raise HTTPException(503, str(error)) from None
        except PermissionError as error:
            raise HTTPException(403, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.post('/v1/display/calendar/invitations/read')
    def read(body: ReadInvitations, request: Request, principal=Depends(authorize)):
        return call(lambda: service.read(body, *context(request, principal)))

    @app.post('/v1/display/calendar/invitations/review')
    def review(body: ReviewInvitations, request: Request, principal=Depends(authorize)):
        return call(lambda: service.review(body, *context(request, principal)))

    @app.post('/v1/display/calendar/invitations/confirm')
    def confirm(body: ConfirmInvitations, request: Request, principal=Depends(authorize)):
        result = call(lambda: service.confirm(body, *context(request, principal)))
        if briefing:
            briefing.invalidate()
        return result

    return service
