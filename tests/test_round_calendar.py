"""Silent Mini review checks using an in-memory HTTP service and fake wire."""
from concurrent.futures import Future
from copy import deepcopy
import json
import unittest

import httpx

from backend.round_calendar import RoundCalendar,checksum,prepare

EVENT={'calendar':'calendar.shared','title':'Lunch with Sam','start':'2026-09-21T12:00',
       'end':'2026-09-21T13:00','timezone':'America/New_York','all_day':False,
       'location':'Cafe','description':'Bring the project notes.'}
SOURCES={'revision':3,'items':[{'kind':'calendar','entity_id':'calendar.shared',
          'name':'Shared calendar','writable':True,'available':True}]}


class Worker:
    def __init__(self):self.jobs=[]
    def submit(self,fn,*args):
        result=Future();self.jobs.append((result,fn,args));return result
    def run(self):
        result,fn,args=self.jobs.pop(0)
        if result.set_running_or_notify_cancel():result.set_result(fn(*args))


class RoundCalendarTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.;self.wall=2000.;self.sent=[];self.requests=[];self.status=200
        self.reply={'status':'accepted'};self.network_error=False;self.worker=Worker()
        def service(request):
            self.requests.append(request)
            if self.network_error:raise httpx.ReadTimeout('Synthetic timeout',request=request)
            return httpx.Response(self.status,json=SOURCES if request.method=='GET' else self.reply)
        self.client=httpx.Client(base_url='http://test',transport=httpx.MockTransport(service))
        self.addCleanup(self.client.close)
        self.calendar=RoundCalendar(self.client,self.worker,self.sent.append,lambda:self.now,lambda:self.wall)

    def prepared(self,event=None,questions=None):
        return prepare({'event':deepcopy(event or EVENT),'questions':questions or [],'expires_at':self.wall+900},SOURCES,self.wall)

    def offer(self,prepared=None):
        self.calendar.receive('STATUS version=0.17.0 calendar_review=1')
        self.calendar.offer(prepared or self.prepared());return self.calendar.draft['id']

    def event(self,kind,identifier=None):
        self.calendar.receive('EVENT calendar_'+kind+'='+(identifier or self.calendar.draft['id']))

    def drain(self):
        while self.calendar.rows:self.calendar.pump()

    def confirm(self):
        self.drain();self.event('ready');self.event('reviewed');self.event('create')

    def test_preview_contains_complete_fields_offsets_recurrence_and_inclusive_all_day_end(self):
        item=self.prepared();rows=item['rows'];self.assertTrue(item['allowed'])
        for text in ('Lunch with Sam','calendar.shared','America/New_York','Does not repeat','Cafe'):
            self.assertIn(text,rows)
        self.assertEqual(''.join(rows[rows.index('START')+1:rows.index('END')]),'2026-09-21T12:00:00-04:00')
        event={**EVENT,'all_day':True,'start':'2026-09-21','end':'2026-09-24','recurrence':{'frequency':'weekly','interval':2,'count':5}}
        item=self.prepared(event);self.assertTrue(item['allowed']);rows=item['rows']
        self.assertEqual(rows[rows.index('LAST INCLUDED DAY')+1],'2026-09-23')
        self.assertEqual(''.join(rows[rows.index('REPEAT')+1:rows.index('LOCATION')]),'FREQ=WEEKLY;INTERVAL=2;COUNT=5')
        self.assertTrue(all(len(line)<=24 for line in rows))

    def test_unrepresentable_ambiguous_unavailable_or_invalid_drafts_cannot_be_created(self):
        cases=[self.prepared({**EVENT,'title':'Caf\u00e9'}),self.prepared({**EVENT,'description':'Line\n'*400,'location':'W'*300,'title':'W'*200}),
               self.prepared(questions=['Which time?']),self.prepared({**EVENT,'end':EVENT['start']}),self.prepared({**EVENT,'calendar':'calendar.other'})]
        for item in cases:
            with self.subTest(item=item['rows'][:1]):
                self.assertFalse(item['allowed']);self.offer(item);self.confirm();self.assertEqual(self.worker.jobs,[])
        sources=deepcopy(SOURCES);sources['items'][0]['writable']=False
        item=prepare({'event':EVENT,'questions':[],'expires_at':2900},sources,2000)
        self.assertFalse(item['allowed']);self.assertIsNone(prepare({'event':EVENT,'questions':[],'expires_at':1999},SOURCES,2000))

    def test_legacy_board_gets_no_protocol_and_capability_loss_discards_draft(self):
        self.calendar.offer(self.prepared());self.calendar.pump();self.assertEqual(self.sent,[])
        self.offer();self.calendar.receive('STATUS version=0.16.0')
        self.assertIsNone(self.calendar.draft);self.assertFalse(self.calendar.supported)
        self.assertEqual(self.sent,[b'CAL_CLEAR\n'])

    def test_wire_preview_integrity_and_explicit_confirmation_dispatch_once(self):
        identifier=self.offer();self.calendar.pump();self.assertEqual(len(self.sent),3)
        self.event('ready');self.event('reviewed');self.event('create');self.assertEqual(self.worker.jobs,[])
        self.drain();self.event('ready','f'*32);self.event('reviewed');self.event('create');self.assertEqual(self.worker.jobs,[])
        self.event('ready');self.event('create');self.assertEqual(self.worker.jobs,[])
        self.event('reviewed');self.event('create');self.event('create');self.assertEqual(len(self.worker.jobs),1)
        lines=[line.decode().rstrip('\n') for line in self.sent]
        rows=[line.split(' :',1)[1] for line in lines if line.startswith('CAL_ROW')]
        self.assertEqual(rows,self.calendar.draft['rows']);self.assertEqual(int(lines[0].split()[-1]),checksum(rows,True))
        self.worker.run();self.calendar.pump();self.assertEqual(self.sent[-1],f'CAL_RESULT {identifier} accepted\n'.encode())
        request=self.requests[0];body=json.loads(request.content)
        self.assertEqual(request.url.path,'/v1/display/calendar/events');self.assertEqual(body['request_id'],identifier)
        self.assertEqual(body['revision'],3);self.assertEqual(body['event']['title'],EVENT['title'])
        self.event('create');self.assertEqual(self.worker.jobs,[])
        self.now+=30;self.calendar.pump();self.assertIsNone(self.calendar.draft)

    def test_cancel_expiry_and_replacement_reject_stale_confirmations(self):
        old=self.offer();self.drain();self.event('cancel');self.event('create',old)
        current=self.offer();self.event('ready',old);self.event('reviewed',old);self.event('create',old)
        self.assertNotEqual(old,current);self.assertFalse(self.calendar.draft['ready']);self.assertEqual(self.worker.jobs,[])
        # Backward wall-clock changes cannot lengthen the monotonic review window.
        self.wall-=500;self.now+=901;self.calendar.pump();self.assertIsNone(self.calendar.draft)
        self.offer();self.confirm();self.calendar.clear();self.worker.run();self.assertEqual(self.requests,[])

    def test_rejection_and_uncertain_network_never_retry_creation(self):
        for status,reply,error,expected in [(403,{},False,'rejected'),(409,{},False,'rejected'),(422,{},False,'rejected'),
                                          (200,{'status':'unconfirmed'},False,'unconfirmed'),(500,{},False,'unconfirmed'),(200,{},True,'unconfirmed')]:
            with self.subTest(status=status,error=error):
                self.status,self.reply,self.network_error=status,reply,error
                identifier=self.offer();self.confirm();self.worker.run();self.calendar.pump()
                self.assertEqual(self.sent[-1],f'CAL_RESULT {identifier} {expected}\n'.encode())
                before=len(self.requests);self.event('create');self.calendar.pump();self.assertEqual(len(self.requests),before)

    def test_prepare_only_reads_sources_and_offered_data_is_not_mutable_by_worker(self):
        draft={'event':deepcopy(EVENT),'questions':[],'expires_at':2900}
        item=self.calendar.prepare(draft);self.assertEqual([r.method for r in self.requests],['GET'])
        self.offer(item);item['event']['title']='Changed after offer';item['rows'][0]='Changed'
        self.assertEqual(self.calendar.draft['event']['title'],EVENT['title']);self.assertEqual(self.calendar.draft['rows'][0],'TITLE')


if __name__=='__main__':unittest.main()
