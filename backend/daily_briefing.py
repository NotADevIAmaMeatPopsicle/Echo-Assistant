"""A local, source-grounded daily overview; never sends household data to a model."""
from datetime import datetime,time as daytime,timedelta,timezone
import re
from threading import Lock
import time
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

from .experiences import ExperienceUnavailable
from .home import HomeUnavailable
from .household import HouseholdUnavailable
from .schedules import ScheduleUnavailable


def briefing_request(text):
    query=re.sub(r'\s+',' ',text.casefold().strip().rstrip('.?!'))
    return query in {'daily briefing','my daily briefing','give me my daily briefing','give me a daily briefing',
        'what does my day look like','what does today look like','what is on my agenda today',
        "what's on my agenda today",'brief me on my day','give me my morning briefing'}


class DailyBriefing:
    def __init__(self,experiences,home,schedules,household,clock=time.time):
        self.experiences,self.home,self.schedules,self.household=experiences,home,schedules,household
        self.clock=clock;self.lock=Lock();self.cache=None;self.cache_key=None;self.until=0

    def invalidate(self):self.until=0

    def get(self,zone_name=None):
        if not self.lock.acquire(blocking=False):
            return {'status':'loading','capability':'briefing','text':'I’m gathering your day. Try again in a moment.'}
        try:
            now=self.clock()
            if zone_name is None:
                try:zone_name=self.home._request('GET','/api/config').get('time_zone')
                except HomeUnavailable:pass
                if not zone_name:zone_name=self.schedules.snapshot()['quiet']['timezone']
            try:zone=ZoneInfo(zone_name)
            except (ZoneInfoNotFoundError,ValueError,TypeError):raise ValueError('Choose an IANA time zone') from None
            today=datetime.fromtimestamp(now,zone).date()
            try:revision=self.experiences.store.snapshot()['revision']
            except ExperienceUnavailable:revision='unavailable'
            key=(str(today),zone_name,revision)
            if self.cache is not None and key==self.cache_key and now<self.until:return self.cache
            until=datetime.combine(today+timedelta(days=1),daytime.min,zone).timestamp()
            parts={};events=[];reminders=[];tasks=[];shopping=0;weather=None
            try:
                agenda=self.experiences.agenda(today.isoformat(),1);parts['calendar']=agenda['status']
                for event in agenda['events']:
                    if event['all_day']:
                        keep=event['start']<=today.isoformat()<event['end']
                    else:
                        keep=datetime.fromisoformat(event['start']).timestamp()<until and datetime.fromisoformat(event['end']).timestamp()>now
                    if keep:events.append(event)
            except (HomeUnavailable,ExperienceUnavailable,ValueError):parts['calendar']='unavailable'
            try:
                state=self.home._state('weather');attrs=state['attributes'];temperature=attrs.get('temperature')
                weather={'condition':state['state'].replace('_',' '),'temperature':temperature if type(temperature) in (int,float) else None,
                         'unit':str(attrs.get('temperature_unit',''))[:8]};parts['weather']='available'
            except (HomeUnavailable,ValueError,KeyError):parts['weather']='unavailable' if self.home.config.enabled else 'not_configured'
            try:
                scheduled=self.schedules.snapshot();parts['reminders']='available'
                for item in scheduled['items']:
                    if item['enabled'] and item['next_at'] is not None and now<=item['next_at']<until:
                        reminders.append({'id':item['id'],'title':item['title'],'kind':item['kind'],'at':item['next_at']})
                for event in scheduled['events']:
                    if event['status'] in {'due','snoozed'} and event['due_at']<until:
                        reminders.append({'id':event['id'],'title':event['title'],'kind':event['kind'],'at':event['due_at']})
                reminders.sort(key=lambda item:item['at'])
            except ScheduleUnavailable:parts['reminders']='unavailable'
            try:
                items=self.household.snapshot()['items'];parts['lists']='available'
                tasks=[{'id':i['id'],'text':i['text']} for i in items if i['kind']=='tasks' and not i['done']]
                shopping=sum(i['kind']=='shopping' and not i['done'] for i in items)
            except HouseholdUnavailable:parts['lists']='unavailable'
            try:allowed=set(self.experiences.store.snapshot()['sources']['calendars'])
            except ExperienceUnavailable:allowed=set();parts['calendar']='unavailable'
            events=[event for event in events if event.get('calendar') in allowed]
            sentences=[f'Here’s your day for {today.strftime("%A, %B")} {today.day}.']
            if weather:
                sentence=f'It’s {weather["condition"]}'
                if weather['temperature'] is not None:sentence+=f', {weather["temperature"]:g}{weather["unit"]}'
                sentences.append(sentence+'.')
            if events:
                event=events[0];when='All day' if event['all_day'] else datetime.fromisoformat(event['start']).astimezone(zone).strftime('%I:%M %p').lstrip('0')
                sentences.append(f'{len(events)} calendar event'+('s remain' if len(events)!=1 else ' remains')+f' today. {when}: {event["title"]}.')
            elif parts['calendar']=='available':sentences.append('Your selected calendars have no more events today.')
            if reminders:sentences.append(f'{len(reminders)} alarm or reminder'+('s' if len(reminders)!=1 else '')+f' today. Next: {reminders[0]["title"]}.')
            if tasks:sentences.append(f'{len(tasks)} unfinished task'+('s' if len(tasks)!=1 else '')+f'. First: {tasks[0]["text"]}.')
            if shopping:sentences.append(f'{shopping} item'+('s' if shopping!=1 else '')+' on your shopping list.')
            missing=[name for name,state in parts.items() if state in {'unavailable','partial'}]
            if missing:sentences.append('I couldn’t fully refresh '+', '.join(missing)+'.')
            if parts['calendar'] in {'not_configured','not_selected'}:sentences.append('No calendar is shared with Echo yet.')
            self.cache={'status':'complete' if 'available' in parts.values() else 'unavailable','partial':bool(missing),'capability':'briefing','text':' '.join(sentences)[:1200],
                'date':today.isoformat(),'timezone':zone_name,'generated_at':now,'sources':parts,'weather':weather,
                'events':events[:20],'event_count':len(events),'reminders':reminders[:20],
                'tasks':tasks[:8],'task_count':len(tasks),'shopping_count':shopping}
            self.cache_key=key;self.until=now+30
            return self.cache
        finally:self.lock.release()
