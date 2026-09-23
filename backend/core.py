"""Local capabilities, independent of voice engines and home-automation integrations."""
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
import json
import math
from pathlib import Path
import re
from threading import RLock
import time
import uuid
from zoneinfo import ZoneInfo
from .audio_destination import validate_destination


def spoken_number(value):
    if value.isdigit(): return int(value)
    names = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    small = dict(zip(names, range(20)))
    tens = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
    parts = value.split()
    if len(parts) == 1: return small.get(value, tens.get(value))
    if len(parts) == 2 and parts[0] in tens and parts[1] in small and 1 <= small[parts[1]] <= 9:
        return tens[parts[0]] + small[parts[1]]
    return None

class TimerStorageUnavailable(RuntimeError):
    pass


@dataclass
class Timer:
    id: str
    label: str
    deadline: float
    notified: bool = False
    destination: str = "round"
    occurrence: str = ""


def locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock: return method(self, *args, **kwargs)
    return call

class Assistant:
    def __init__(self, clock=time.monotonic, storage: Path | None = None, wall_clock=time.time, *, time_zone=None):
        self.clock = clock
        self.wall_clock = wall_clock
        self.time_zone = time_zone
        self.lock = RLock()
        self.storage = storage
        self.timers: dict[str, Timer] = {}
        self.storage_error = False
        try:
            if storage and storage.exists(): self._load()
        except (OSError, ValueError, TypeError, KeyError):
            # Preserve damaged state for repair; never overwrite it with an empty list.
            self.timers.clear(); self.storage_error = True

    def _require_storage(self):
        if self.storage_error:
            raise TimerStorageUnavailable('Saved timers could not be read; inspect the local timer file')

    def _load(self):
        records = json.loads(self.storage.read_text(encoding='utf-8'))
        if not isinstance(records, list) or len(records) > 16: raise ValueError('Invalid saved timers')
        for record in records:
            if (not isinstance(record, dict) or not re.fullmatch(r'[0-9a-f]{32}', record.get('id', ''))
                or not isinstance(record.get('label'), str) or not 1 <= len(record['label']) <= 80
                or type(record.get('deadline')) not in {float, int} or not math.isfinite(record['deadline'])
                or type(record.get('notified', False)) is not bool
                or not re.fullmatch(r'[a-f0-9]{32}', record.get('occurrence', record.get('id', '')))):
                raise ValueError('Invalid saved timer')
            remaining = record['deadline']-self.wall_clock()
            if remaining > 86400: raise ValueError('Saved timer exceeds one day')
            self.timers[record['id']] = Timer(record['id'], record['label'], self.clock()+remaining, record.get('notified', False),
                validate_destination(record.get('destination', 'round')), record.get('occurrence') or record['id'])

    def _save(self):
        if self.storage is None: return
        self.storage.parent.mkdir(parents=True, exist_ok=True)
        records = [{'id': t.id, 'label': t.label, 'deadline': self.wall_clock()+t.deadline-self.clock(),
                    'notified': t.notified, 'destination': t.destination, 'occurrence': t.occurrence} for t in self.timers.values()]
        temporary = self.storage.with_suffix('.tmp')
        temporary.write_text(json.dumps(records), encoding='utf-8')
        temporary.replace(self.storage)

    @locked
    def timer_states(self):
        self._require_storage()
        now = self.clock()
        return [{"id": t.id, "label": t.label,
                 "remaining_seconds": max(0, round(t.deadline-now, 1)),
                 "finished": now >= t.deadline, "notified": t.notified,
                 "destination": t.destination, "occurrence": t.occurrence, "late_seconds": max(0, now-t.deadline)} for t in self.timers.values()]

    @locked
    def start_timer(self, seconds, label="Timer", *, destination="round"):
        self._require_storage()
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 86400:
            raise ValueError("Timer must be between one second and 24 hours")
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
            raise ValueError("Timer label must contain 1–80 characters")
        if len(self.timers) >= 16:
            raise ValueError("Dismiss a timer before adding another")
        timer = Timer(uuid.uuid4().hex, label.strip(), self.clock()+seconds,
                      destination=validate_destination(destination), occurrence=uuid.uuid4().hex)
        self.timers[timer.id] = timer
        try: self._save()
        except OSError as error:
            del self.timers[timer.id]
            raise TimerStorageUnavailable('Timer could not be saved') from error
        return timer.id

    @locked
    def dismiss_timer(self, timer_id):
        self._require_storage()
        timer = self.timers.pop(timer_id, None)
        if timer:
            try: self._save()
            except OSError as error:
                self.timers[timer_id] = timer
                raise TimerStorageUnavailable('Timer could not be dismissed') from error
        return timer is not None

    @locked
    def acknowledge_timer(self, timer_id, *, occurrence=None, destination=None):
        self._require_storage()
        timer = self.timers.get(timer_id)
        if not timer or timer.deadline > self.clock(): return False
        if occurrence is not None and timer.occurrence != occurrence: return False
        if destination is not None and timer.destination != destination: return False
        previous = timer.notified
        timer.notified = True
        try: self._save()
        except OSError as error:
            timer.notified = previous
            raise TimerStorageUnavailable('Timer acknowledgement could not be saved') from error
        return True

    @locked
    def snooze_timer(self, timer_id, minutes=5):
        self._require_storage()
        timer = self.timers.get(timer_id)
        if not timer or timer.deadline > self.clock(): return False
        if type(minutes) is not int or not 1 <= minutes <= 60: raise ValueError('Choose 1–60 minutes')
        previous = (timer.deadline, timer.notified, timer.occurrence)
        timer.deadline, timer.notified, timer.occurrence = self.clock()+minutes*60, False, uuid.uuid4().hex
        try: self._save()
        except OSError as error:
            timer.deadline, timer.notified, timer.occurrence = previous
            raise TimerStorageUnavailable('Timer could not be snoozed') from error
        return True

    @locked
    def timer_reply(self, action, timer_id=None, *, destination=None):
        """Resolve and report actual timer state atomically; never guess a target."""
        self._require_storage()
        candidates = {k:t for k,t in self.timers.items() if destination is None or t.destination == destination}
        if timer_id is None:
            if len(candidates) != 1:
                return {'status':'complete','capability':'timer', 'text':
                        'Choose a timer on the display.' if candidates else 'There are no active timers.'}
            timer_id = next(iter(candidates))
        timer = candidates.get(timer_id)
        result = {'status':'complete','capability':'timer','timer_id':timer_id,'timer_action':action}
        if timer is None:
            return {**result,'timer_action':'missing','text':'That timer has already been dismissed.'}
        if action == 'dismissed':
            self.dismiss_timer(timer_id)
            return {**result,'text':'Your timer is dismissed.'}
        seconds = max(0, math.ceil(timer.deadline-self.clock()))
        if seconds == 0:
            return {**result,'text':'That timer has finished.'}
        hours, rest = divmod(seconds, 3600); minutes, seconds = divmod(rest, 60)
        parts = [f'{amount} {unit}'+('s' if amount != 1 else '')
                 for amount, unit in ((hours,'hour'),(minutes,'minute'),(seconds,'second')) if amount]
        duration = ' and '.join(parts) if len(parts) < 3 else ', '.join(parts[:-1])+' and '+parts[-1]
        return {**result,'text':f'That timer has {duration} left.'}

    def respond(self, text, *, timer_context=None, destination="round"):
        if not isinstance(text, str) or not text.strip() or len(text) > 1200:
            raise ValueError("Request must contain 1–1200 characters")
        text = text.strip().lower().rstrip("?.!")
        # Pronouns require the immediately preceding result in this session.
        # A dismissed/stale target never falls through to a different active timer.
        timer_id = (timer_context.get('timer_id') if timer_context and
                    timer_context.get('capability') == 'timer' else None)
        if timer_id and text in {'cancel it','stop it','dismiss it','cancel that timer','stop that timer','dismiss that timer'}:
            return self.timer_reply('dismissed',timer_id,destination=destination)
        if timer_id and text in {'how long is left','how long left','how much time is left','how much time is remaining',
                                 'how long is left on it','how much time is left on it'}:
            return self.timer_reply('status',timer_id,destination=destination)
        if text in {'how much time is left on my timer','how much time is left on the timer','how long is left on my timer',
                    'how long is left on the timer','check my timer','timer status'}:
            return self.timer_reply('status',timer_id,destination=destination)
        if text in {'cancel my timer', 'cancel the timer', 'stop the timer', 'dismiss the timer'}:
            return self.timer_reply('dismissed',timer_id,destination=destination)
        if text in {'cancel that timer','stop that timer','dismiss that timer'}:
            return {'status':'unavailable','capability':'timer','text':'Which timer? Choose it on the display.'}
        clock_requests = {"what time is it", "what's the time", "time"}
        date_requests = {"what is today's date", "what's the date", "date"}
        if text in clock_requests | date_requests:
            # The API supplies the saved home zone, independent of Docker's TZ.
            # Resolve it per request so preference changes require no restart.
            zone = self.time_zone() if callable(self.time_zone) else self.time_zone
            now = datetime.fromtimestamp(self.wall_clock(), ZoneInfo(zone) if zone else None)
        if text in clock_requests:
            return {"status": "complete", "capability": "clock",
                    "text": now.strftime("It's %I:%M %p.").replace(" 0", " ")}
        if text in date_requests:
            return {"status": "complete", "capability": "clock",
                    "text": now.strftime("Today is %A, %B %d.")}
        match = re.fullmatch(r"(?:set |start )?(?:a )?timer (?:for )?([a-z0-9]+(?: [a-z]+)?) (seconds?|minutes?|hours?)", text)
        if match:
            amount = spoken_number(match[1])
            if amount is None: raise ValueError("Timer duration was not understood")
            seconds = amount * {"second": 1, "minute": 60, "hour": 3600}[match[2].rstrip("s")]
            timer_id = self.start_timer(seconds, destination=destination)
            return {"status": "complete", "capability": "timer", "timer_id": timer_id, "timer_action": "started",
                    "text": f"Your timer is set for {match[1]} {match[2]}."}
        return {"status": "unavailable", "capability": "conversation",
                "text": "General conversation is not configured yet. Clock and timers are available."}
