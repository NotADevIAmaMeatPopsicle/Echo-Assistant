"""Volatile Mini calendar review. Only an explicit, matching board confirmation writes."""
from copy import deepcopy
from datetime import date,timedelta
import math
import re
import textwrap
import time
import uuid
import httpx

from .calendar_events import CalendarEvent

ROWS=128
WIDTH=24


def checksum(rows,allowed):
    value=2166136261
    for byte in (str(int(allowed))+'\n'+'\n'.join(rows)+'\n').encode('ascii'):
        value=((value^byte)*16777619)&0xffffffff
    return value


def prepare(draft,sources,now):
    """Create an exact bounded preview, never turn a partial/ambiguous draft into an action."""
    if not isinstance(draft,dict) or not isinstance(draft.get('event'),dict):return None
    expiry=draft.get('expires_at')
    if type(expiry) not in (int,float) or not math.isfinite(expiry) or expiry<=now:return None
    event=deepcopy(draft['event']);questions=draft.get('questions')
    if not isinstance(questions,list) or any(not isinstance(q,str) for q in questions):return None
    chosen=next((i for i in sources.get('items',[]) if i.get('entity_id')==event.get('calendar') and i.get('kind')=='calendar'),None)
    allowed=not questions and bool(chosen and chosen.get('writable') and chosen.get('available'))
    bounds={};repeat='Does not repeat'
    try:
        validated=CalendarEvent.model_validate(event)
        event=validated.model_dump();bounds=validated.bounds()
        if validated.recurrence:repeat=validated.recurrence.rule()
    except ValueError:allowed=False
    labels=[('TITLE',event.get('title','')),('CALENDAR',chosen.get('name','') if chosen else 'Choose on the Deck'),
            ('CALENDAR ID',event.get('calendar','')),('START',bounds.get('start_date_time',event.get('start',''))),('END',bounds.get('end_date_time',event.get('end',''))),
            ('TIME ZONE',event.get('timezone','')),('ALL DAY','Yes' if event.get('all_day') else 'No'),
            ('REPEAT',repeat),('LOCATION',event.get('location','') or 'None'),('NOTES',event.get('description','') or 'None')]
    if event.get('all_day'):
        try:labels[4]=('LAST INCLUDED DAY',(date.fromisoformat(event['end'])-timedelta(days=1)).isoformat())
        except (ValueError,KeyError):allowed=False
    labels.extend(('REVIEW NEEDED',q) for q in questions)
    rows=[];faithful=True
    for label,value in labels:
        if not isinstance(value,str):return None
        if any(ord(c)>126 or ord(c)<32 and c not in '\n\r\t' for c in value):faithful=False
        rows.append(label)
        for line in value.splitlines() or ['Not supplied']:
            rows.extend(textwrap.wrap(line.expandtabs(),WIDTH,break_long_words=True,break_on_hyphens=False) or [''])
    if not faithful or len(rows)>ROWS:
        rows=['REVIEW ON THE DECK','This draft needs a','larger display or','additional characters.','Nothing is saved here.']
        allowed=False
    elif not allowed:
        rows=['REVIEW ON THE DECK','Resolve the questions','or calendar selection.','Nothing is saved here.',*rows]
        if len(rows)>ROWS:rows=rows[:4]
    revision=sources.get('revision')
    if type(revision) is not int:return None
    return {'event':event,'revision':revision,'rows':rows,'allowed':allowed,'expires_at':min(expiry,now+900)}


class RoundCalendar:
    def __init__(self,client,worker,write,clock=time.monotonic,wall=time.time):
        self.client,self.worker,self.write,self.clock,self.wall=client,worker,write,clock,wall
        self.supported=False;self.draft=None;self.future=None;self.rows=[];self.result_until=0

    def offer(self,prepared):
        self.clear()
        if not self.supported or not prepared or prepared['expires_at']<=self.wall():return
        ttl=max(1,min(900,int(prepared['expires_at']-self.wall())))
        self.draft={**deepcopy(prepared),'id':uuid.uuid4().hex,'ready':False,'reviewed':False,'sent':False,'deadline':self.clock()+ttl}
        item=self.draft;identifier=item['id'];digest=checksum(item['rows'],item['allowed'])
        self.rows=[f"CAL_BEGIN {identifier} {len(item['rows'])} {int(item['allowed'])} {ttl} {digest}\n"]
        self.rows.extend(f'CAL_ROW {identifier} {index} :{row}\n' for index,row in enumerate(item['rows']))
        self.rows.append(f'CAL_COMMIT {identifier}\n')

    def clear(self):
        if self.draft and self.supported:self.write(b'CAL_CLEAR\n')
        self.draft=None;self.rows=[];self.result_until=0
        if self.future:self.future.cancel();self.future=None

    def receive(self,line):
        if line.startswith('STATUS '):
            supported=bool(re.search(r'\bcalendar_review=1\b',line))
            if self.supported and not supported:self.clear()
            self.supported=supported;return
        match=re.fullmatch(r'EVENT calendar_(ready|reviewed|create|cancel)=([a-f0-9]{32})',line)
        if not match or not self.draft or match[2]!=self.draft['id']:return
        action=match[1];item=self.draft
        if action=='cancel':self.clear();return
        if item['expires_at']<=self.wall() or self.clock()>=item['deadline']:self.clear();return
        if action=='ready' and not self.rows:item['ready']=True
        if action=='reviewed' and item['ready']:item['reviewed']=True
        if action=='create' and item['ready'] and item['reviewed'] and item['allowed'] and not item['sent']:
            item['sent']=True
            body={'event':item['event'],'revision':item['revision'],'request_id':item['id']}
            self.future=self.worker.submit(self._create,body)

    def _create(self,body):
        try:
            response=self.client.post('/v1/display/calendar/events',json=body)
            if response.status_code in {403,409,422}:return 'rejected'
            response.raise_for_status();value=response.json().get('status')
            return value if value in {'accepted','rejected','unconfirmed'} else 'unconfirmed'
        except (httpx.HTTPError,ValueError):return 'unconfirmed'

    def pump(self):
        if not self.supported:return
        if self.future and self.future.done():
            try:result=self.future.result()
            except Exception:result='unconfirmed'
            self.future=None
            if self.draft:
                self.write(f"CAL_RESULT {self.draft['id']} {result}\n".encode('ascii'));self.result_until=self.clock()+30
        if self.draft and (self.result_until and self.clock()>=self.result_until or not self.result_until and not self.future and (self.draft['expires_at']<=self.wall() or self.clock()>=self.draft['deadline'])):self.clear()
        # Limit wire traffic per loop so audio/heartbeat handling keeps running.
        for _ in range(min(3,len(self.rows))):self.write(self.rows.pop(0).encode('ascii'))

    def prepare(self,draft):
        try:
            response=self.client.get('/v1/display/sources');response.raise_for_status()
            return prepare(draft,response.json(),self.wall())
        except (httpx.HTTPError,ValueError):return None
