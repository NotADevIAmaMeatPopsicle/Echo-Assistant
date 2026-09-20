"""Private, read-only Google connections bound to actual personal sessions."""
import base64
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import re
from threading import RLock

from fastapi import HTTPException

from .display_profiles import ScopedSources
from .experiences import Experiences, ExperienceConflict, Sources
from .google_calendar import GoogleCalendars
from .home import HomeUnavailable
from .members import PersonalPrincipal


MAX_PLAIN_BYTES = 4_500_000
MAX_FILE_BYTES = 8_000_000


class _Namespace:
    """GoogleCalendars storage adapter; provider validation remains in its core."""
    def __init__(self, service, member):
        self.service, self.member = service, member

    def load(self):
        with self.service.lock:
            self.service.require()
            return deepcopy(self.service.records.get(self.member, {}).get('google'))

    def save(self, document):
        service = self.service
        # Service mutations already hold members.lock before provider.lock.
        # Never acquire either outer lock while holding the registry lock.
        with service.lock:
            service.members.item(self.member)
            records = deepcopy(service.records)
            record = records.setdefault(self.member, {'selection': {'revision': 0, 'calendars': []}})
            record['google'] = deepcopy(document)
            service.commit(records)


class MemberGoogle:
    def __init__(self, members, household_google, root, protector):
        self.members, self.household, self.protector = members, household_google, protector
        self.path = Path(root) / 'local/echo-member-google.json' if root else None
        self.lock = RLock()
        self.records, self.providers, self.flows = {}, {}, {}
        self.error = False
        if self.path and self.path.exists():
            try:
                if self.path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError()
                envelope = json.loads(self.path.read_text(encoding='utf-8'))
                if envelope['version'] != 1:
                    raise ValueError()
                raw = protector.decrypt(base64.b64decode(envelope['protected'], validate=True))
                if len(raw) > MAX_PLAIN_BYTES:
                    raise ValueError()
                records = json.loads(raw)
                if not isinstance(records, dict) or len(records) > 16:
                    raise ValueError()
                for member, record in records.items():
                    if not re.fullmatch(r'[a-f0-9]{32}', member) or not isinstance(record, dict) or set(record) - {'google', 'selection'}:
                        raise ValueError()
                    selected = record['selection']
                    if set(selected) != {'revision', 'calendars'} or type(selected['revision']) is not int or selected['revision'] < 0:
                        raise ValueError()
                    Sources.model_validate({'calendars': selected['calendars']})
                    if 'google' in record and (not isinstance(record['google'], dict) or set(record['google']) != {'config', 'accounts'}):
                        raise ValueError()
                self.records = records
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                self.error = True

    def require(self):
        if self.error:
            raise HomeUnavailable('Private Google settings are unreadable. Existing storage is preserved.')

    def commit(self, records):
        with self.lock:
            self._commit(records)

    def _commit(self, records):
        self.require()
        raw = json.dumps(records).encode()
        if len(records) > 16 or len(raw) > MAX_PLAIN_BYTES:
            raise HomeUnavailable('Private Google storage is full. Disconnect an unused account.')
        if self.path:
            try:
                envelope = json.dumps({'version': 1, 'protected': base64.b64encode(self.protector.encrypt(raw)).decode()})
                if len(envelope.encode()) > MAX_FILE_BYTES:
                    raise ValueError()
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(envelope, encoding='utf-8')
                temporary.replace(self.path)
            except (OSError, ValueError, RuntimeError):
                raise HomeUnavailable('Private Google settings could not be saved.') from None
        self.records = deepcopy(records)

    def check(self, principal, before=None):
        with self.members.lock:
            if not isinstance(principal, PersonalPrincipal):
                raise HTTPException(403, 'Sign in to your personal account to manage private calendars.')
            self.members.current(principal)
            current = self.members.profile_for(principal)
            if before is not None and current != before:
                raise HTTPException(409, 'Personal calendar access changed. Open your calendars again.')
            return current

    @staticmethod
    def binding(principal, before):
        return hashlib.sha256(json.dumps([str(principal), principal.member, principal.nonce,
                                          before['profile_revision']]).encode()).hexdigest()

    def _provider(self, member):
        self.require()
        self.members.item(member)
        if member not in self.providers:
            self.providers[member] = GoogleCalendars(None, self.protector,
                transport=self.household.transport, clock=self.household.clock,
                enabled=self.household.enabled, state_store=_Namespace(self, member))
        provider = self.providers[member]
        provider.require()
        provider.transport = self.household.transport
        provider.enabled = self.household.enabled
        with self.household.lock:
            self.household.require()
            config = self.household.config.model_copy(deep=True)
        identity = lambda value: (value.client_id, value.client_secret.get_secret_value())
        with provider.lock:
            compatible = not provider.accounts or identity(provider.config) == identity(config)
            if not compatible:
                provider.flows.clear()
                provider.access.clear()
            elif provider.config != config:
                provider.flows.clear()
                provider.access.clear()
                provider.commit(config, provider.accounts)
        return provider, compatible

    def _context(self, principal, before=None, *, allow_stale=False):
        current = self.check(principal, before)
        provider, compatible = self._provider(principal.member)
        if not compatible and not allow_stale:
            raise HomeUnavailable('The owner changed Google OAuth credentials. Disconnect this private connection and connect again.')
        return provider, current, compatible

    def selection(self, member):
        self.require()
        return deepcopy(self.records.get(member, {}).get('selection', {'revision': 0, 'calendars': []}))

    def _selection_save(self, member, calendars, revision):
        current = self.selection(member)
        if current['revision'] != revision:
            raise ExperienceConflict('Private calendar selection changed. Reload before saving.')
        Sources.model_validate({'calendars': calendars})
        records = deepcopy(self.records)
        records.setdefault(member, {})['selection'] = {'revision': revision + 1, 'calendars': list(calendars)}
        self.commit(records)
        return self.selection(member)

    def _touch(self, member, provider):
        current = self.selection(member)
        available = {calendar['entity_id'] for account in provider.accounts for calendar in account['calendars']}
        return self._selection_save(member, [value for value in current['calendars'] if value in available], current['revision'])

    def settings(self, principal):
        with self.members.lock:
            provider, before, compatible = self._context(principal, allow_stale=True)
            selection = self.selection(principal.member)
            calendars = [{'entity_id': calendar['entity_id'], 'name': calendar['name'],
                          'account_label': account['label'], 'timezone': calendar['timezone'],
                          'selected': calendar['entity_id'] in selection['calendars']}
                         for account in provider.accounts for calendar in account['calendars']]
            result = {'enabled': provider.enabled, 'configured': bool(self.household.config.client_id and
                      self.household.config.client_secret.get_secret_value() and self.household.config.redirect_uri),
                      'needs_reconnect': not compatible, 'read_only': True, 'revision': selection['revision'],
                      'accounts': [{'id': account['id'], 'label': account['label'], 'calendar_count': len(account['calendars'])}
                                   for account in provider.accounts], 'calendars': calendars}
            self.check(principal, before)
            return result

    def begin(self, principal, label, client):
        with self.members.lock:
            provider, before, _ = self._context(principal)
            flow = provider.begin(label, self.binding(principal, before), client, write_access=False)
            self.flows[(principal.member, flow['id'])] = {'principal': principal, 'before': before}
            return flow

    def _flow(self, principal, identifier, client):
        provider, before, _ = self._context(principal)
        context = self.flows.get((principal.member, identifier))
        if not context or context['principal'].nonce != principal.nonce or str(context['principal']) != str(principal):
            raise HTTPException(404, 'Sign-in expired or belongs to another personal session.')
        self.check(principal, context['before'])
        provider.flow(identifier, self.binding(principal, before), client)
        return provider, before

    def flow_status(self, principal, identifier, client):
        with self.members.lock:
            provider, before = self._flow(principal, identifier, client)
            return provider.flow_status(identifier, self.binding(principal, before), client)

    def cancel(self, principal, identifier, client):
        with self.members.lock:
            provider, before = self._flow(principal, identifier, client)
            result = provider.cancel(identifier, self.binding(principal, before), client)
            self.flows.pop((principal.member, identifier), None)
            return result

    def callback(self, state, code, error):
        """Return False for another provider's state; never guess a member."""
        digest = hashlib.sha256(state.encode()).hexdigest()
        with self.members.lock:
            found = None
            for key, context in list(self.flows.items()):
                provider = self.providers.get(key[0])
                flow = provider.flows.get(key[1]) if provider else None
                if flow and hmac.compare_digest(flow['state'], digest):
                    found = key, context, provider
                    break
            if not found:
                return False
            key, context, provider = found
            principal = context['principal']
            try:
                self._context(principal, context['before'])
                if key[1] not in provider.flows:
                    raise HTTPException(410, 'Google configuration changed. Start sign-in again.')
            except Exception:
                provider.flows.pop(key[1], None)
                self.flows.pop(key, None)
                raise
        # Google releases its lock during token exchange; session cancellation
        # can remove the flow while that network call is outstanding.
        provider.callback(state, code, error)
        with self.members.lock:
            try:
                self._context(principal, context['before'])
                if self.flows.get(key) is not context or key[1] not in provider.flows:
                    raise HTTPException(410, 'This private sign-in was cancelled.')
            except Exception:
                provider.flows.pop(key[1], None)
                self.flows.pop(key, None)
                raise
        return True

    def finish(self, principal, identifier, client):
        with self.members.lock:
            provider, before = self._flow(principal, identifier, client)
            result = provider.finish(identifier, self.binding(principal, before), client)
            self.flows.pop((principal.member, identifier), None)
            self._touch(principal.member, provider)
            self.check(principal, before)
            return result

    def sync(self, principal, identifier):
        with self.members.lock:
            provider, before, _ = self._context(principal)
            result = provider.sync(identifier)
            self.check(principal, before)
            self._touch(principal.member, provider)
            return result

    def disconnect(self, principal, identifier):
        with self.members.lock:
            provider, before, _ = self._context(principal, allow_stale=True)
            result = provider.disconnect(identifier)
            self._touch(principal.member, provider)
            self.check(principal, before)
            return result

    def select(self, principal, calendars, revision):
        with self.members.lock:
            provider, before, _ = self._context(principal)
            available = {calendar['entity_id'] for account in provider.accounts for calendar in account['calendars']}
            if not set(calendars) <= available:
                raise ValueError('Choose only calendars from your private Google connections.')
            result = self._selection_save(principal.member, calendars, revision)
            self.check(principal, before)
            return result

    def cancel_session(self, principal):
        if not isinstance(principal, PersonalPrincipal):
            return
        with self.members.lock:
            for key, context in list(self.flows.items()):
                other = context['principal']
                if str(other) == str(principal) and other.member == principal.member and other.nonce == principal.nonce:
                    provider = self.providers.get(key[0])
                    if provider:
                        with provider.lock:
                            provider.flows.pop(key[1], None)
                    self.flows.pop(key, None)
            if principal.member in self.providers:
                with self.providers[principal.member].lock:
                    self.providers[principal.member].access.clear()

    def remove_member(self, member):
        with self.members.lock:
            if not re.fullmatch(r'[a-f0-9]{32}', member):
                raise ValueError('Invalid personal account')
            provider = self.providers.pop(member, None)
            if provider:
                with provider.lock:
                    provider.flows.clear()
                    provider.access.clear()
                    provider.accounts = []
            self.flows = {key: value for key, value in self.flows.items() if key[0] != member}
            if member in self.records:
                self.commit({key: value for key, value in self.records.items() if key != member})

    def prune(self):
        with self.members.lock:
            self.require()
            for key, context in list(self.flows.items()):
                provider = self.providers.get(key[0])
                try:
                    self.check(context['principal'], context['before'])
                    if provider:
                        provider.prune()
                    if not provider or key[1] not in provider.flows:
                        raise ValueError()
                except (HTTPException, ValueError, RuntimeError):
                    if provider:
                        provider.flows.pop(key[1], None)
                    self.flows.pop(key, None)
            for member in set(self.records) | set(self.providers):
                if member not in self.members.records:
                    self.remove_member(member)

    def scoped(self, principal, experiences):
        before = self.check(principal)
        union = _UnionSources(self, principal, before, experiences)
        google = _UnionGoogle(union, experiences.google)
        return _PersonalExperiences(experiences.home, union, google=google)


class _UnionSources:
    def __init__(self, service, principal, before, shared):
        self.service, self.principal, self.before, self.shared = service, principal, before, shared
        self.lock = service.members.lock

    def check(self):
        return self.service.check(self.principal, self.before)['profile']

    def parts(self):
        service = self.service
        with service.members.lock:
            profile = self.check()
            shared = ScopedSources(self.shared.store, lambda: profile).snapshot()
            provider, compatible = service._provider(self.principal.member)
            selection = service.selection(self.principal.member)
            available = {calendar['entity_id'] for account in provider.accounts for calendar in account['calendars']}
            private = [value for value in selection['calendars'] if value in available]
            return shared, provider, private, selection, compatible

    def snapshot(self):
        shared, _, private, selection, _ = self.parts()
        source = shared['sources']
        source['calendars'] = list(dict.fromkeys([*source['calendars'], *private]))
        source['writable_calendars'] = []
        source['managed_calendars'] = []
        # Include configuration changes so a late result cannot survive changing
        # owner OAuth setup, private selection or explicit household sharing.
        revision = int(hashlib.sha256(json.dumps([shared['revision'], selection['revision'],
            self.before['profile_revision'], self.service.household.config.revision,
            self.service.household.enabled]).encode()).hexdigest()[:13], 16)
        return {'revision': revision, 'sources': source}


class _UnionGoogle:
    def __init__(self, sources, household):
        self.sources, self.household = sources, household

    def owns(self, entity):
        return GoogleCalendars.owns(self, entity)

    def catalog(self):
        shared, private, selected, _, compatible = self.sources.parts()
        shared_ids = set(shared['sources']['calendars'])
        rows = [row for row in self.household.catalog() if row['entity_id'] in shared_ids] if self.household else []
        rows += [{**row, 'available': row['available'] and compatible}
                 for row in private.catalog() if row['entity_id'] in selected]
        self.sources.check()
        return [{**row, 'can_create': False, 'can_edit': False, 'can_delete': False} for row in rows]

    def events(self, entity, since, until):
        start_revision = self.sources.snapshot()['revision']
        shared, private, selected, _, compatible = self.sources.parts()
        if entity in selected:
            if not compatible:
                raise HomeUnavailable('Reconnect your private Google account after OAuth configuration changed.')
            rows = private.events(entity, since, until)
        elif self.household and entity in shared['sources']['calendars']:
            rows = self.household.events(entity, since, until)
        else:
            raise HomeUnavailable('This calendar is not selected for your personal account.')
        if self.sources.snapshot()['revision'] != start_revision:
            raise ExperienceConflict('Personal calendar selection changed during the request. Refresh again.')
        # The combined personal agenda is read-only, including explicitly shared
        # household events whose provider connection has a separate write grant.
        for row in rows:
            row.pop('uid', None)
            row.pop('_google_invitation_uid', None)
        return rows


class _PersonalExperiences(Experiences):
    def _fresh(self, action):
        revision = self.store.snapshot()['revision']
        result = action()
        if self.store.snapshot()['revision'] != revision:
            raise ExperienceConflict('Personal calendar access changed during the request. Refresh again.')
        return result

    def sources(self):
        return self._fresh(super().sources)

    def agenda(self, start, days=7):
        return self._fresh(lambda: super(_PersonalExperiences, self).agenda(start, days))
