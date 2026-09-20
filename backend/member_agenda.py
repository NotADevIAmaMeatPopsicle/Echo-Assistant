"""Read approved calendars for a personal conversation without calling a model."""
from datetime import datetime, time as daytime, timedelta
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from .daily_briefing import briefing_request
from .display_profiles import ScopedSources
from .experiences import Experiences, ExperienceUnavailable
from .home import HomeUnavailable
from .schedules import ScheduleUnavailable


def agenda_request(text):
    query = re.sub(r'\s+', ' ', text.casefold().strip().rstrip('.?!')).replace('’', "'")
    if briefing_request(query):
        return 'today'
    match = re.fullmatch(
        r"(?:please )?(?:(?:what is|what's) on (?:my |the )?(?:calendar|agenda|schedule)|"
        r"(?:read|show|check)(?: me)? (?:my |the )?(?:calendar|agenda|schedule)|"
        r"(?:my )?(?:calendar|agenda|schedule))(?: for)?(?: (today|tomorrow|this week))?", query)
    return (match.group(1) or 'today') if match else None


class MemberAgenda:
    def __init__(self, experiences, displays, schedules, clock=time.time):
        self.experiences, self.displays, self.schedules = experiences, displays, schedules
        self.clock = clock

    def respond(self, period, principal, before, *, lookup=False, cancel=None):
        def unavailable(text):
            return {'status':'unavailable', 'capability':'calendar_agenda', 'text':text}

        def check():
            if cancel is not None and cancel.is_set():
                raise HTTPException(409, 'The calendar request was cancelled.')
            current = self.displays.profile_for(principal)
            if current != before or not current['profile'].get('personal'):
                raise HTTPException(409, 'Personal calendar access changed. Please try again.')
            return current['profile']

        check()
        if lookup:
            return unavailable('Turn off web lookup to read your approved calendars privately.')
        if not before['profile']['calendars']:
            return unavailable('No calendars are shared with your account. The owner can select them under Personal accounts → Access.')
        scoped = Experiences(self.experiences.home, ScopedSources(self.experiences.store, check))
        try:
            source_revision = self.experiences.store.snapshot()['revision']
            # The host time zone is configuration, not household agenda data.
            try:
                zone_name = self.experiences.home._request('GET', '/api/config').get('time_zone')
            except HomeUnavailable:
                zone_name = None
            zone = ZoneInfo(zone_name or self.schedules.snapshot()['quiet']['timezone'])
            now = self.clock()
            today = datetime.fromtimestamp(now, zone).date()
            first = today + timedelta(days=1 if period == 'tomorrow' else 0)
            days = 7 if period == 'this week' else 1
            last = first + timedelta(days=days)
            start_at = max(now, datetime.combine(first, daytime.min, zone).timestamp())
            end_at = datetime.combine(last, daytime.min, zone).timestamp()
            check()
            agenda = scoped.agenda(first.isoformat(), days)
            check()
            if self.experiences.store.snapshot()['revision'] != source_revision:
                return unavailable('Calendar sharing changed while I was checking. Please try again.')
            events = []
            for event in agenda['events']:
                keep = (event['start'] < last.isoformat() and event['end'] > first.isoformat()) if event['all_day'] else (
                    datetime.fromisoformat(event['start']).timestamp() < end_at and
                    datetime.fromisoformat(event['end']).timestamp() > start_at)
                if keep:
                    events.append({key:event[key] for key in ('title','start','end','all_day','calendar_name')})
        except (ExperienceUnavailable, HomeUnavailable, ScheduleUnavailable, ZoneInfoNotFoundError, ValueError, TypeError, KeyError):
            check()
            return unavailable('I couldn’t read your approved calendars. Check the calendar connection and host time zone.')
        check()
        if agenda['status'] in {'not_configured','not_selected'} or not scoped.store.snapshot()['sources']['calendars']:
            return unavailable('No approved calendar is currently connected for your account.')
        partial = agenda['status'] != 'available'
        label = 'over the next seven days' if days == 7 else period
        if events:
            parts = [f'{len(events)} event' + ('s' if len(events) != 1 else '') + f' on your shared calendars {label}.']
            for event in events[:5]:
                when = 'All day' if event['all_day'] else datetime.fromisoformat(event['start']).astimezone(zone).strftime('%I:%M %p').lstrip('0')
                if days == 7:
                    when = event['start'][:10] + ', ' + when if event['all_day'] else datetime.fromisoformat(event['start']).astimezone(zone).strftime('%A') + ', ' + when
                title = re.sub(r'\s+', ' ', event['title']).strip()[:100]
                parts.append(f'{when}: {title}.')
            if len(events) > 5: parts.append('Open My day for the rest.')
        else:
            parts = [f'No remaining events {label} on your shared calendars.'] if not partial else []
        if partial: parts.append('Some calendars could not be refreshed, so this may be incomplete.')
        return {'status':'complete' if events or not partial else 'unavailable', 'capability':'calendar_agenda',
                'text':' '.join(parts), 'partial':partial, 'date':first.isoformat(), 'days':days,
                'timezone':str(zone), 'events':events[:20], 'event_count':len(events)}
