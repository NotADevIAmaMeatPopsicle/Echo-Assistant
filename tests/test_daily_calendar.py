import json,os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch
import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.calendar_events import CalendarEvent,CalendarWriter
from backend.daily_briefing import DailyBriefing
from backend.experiences import Experiences,SourceStore,ExperienceConflict,ExperienceUnavailable
from backend.home import HomeBridge,HomeConfig,HomeUnavailable
from backend.linux_protection import LinuxProtector
from backend.settings import SettingsStore


class DailyCalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        key=self.root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600);self.protector=LinuxProtector(key)
        self.requests=[];self.fail=False
        self.state={'entity_id':'calendar.demo','state':'off','attributes':{'friendly_name':'Demo','supported_features':1}}
        def transport(request):
            self.requests.append(request)
            if request.url.path=='/api/states':return httpx.Response(200,json=[self.state])
            if request.url.path=='/api/states/calendar.demo':return httpx.Response(200,json=self.state)
            if request.url.path=='/api/services/calendar/create_event':return httpx.Response(503 if self.fail else 200,json=[])
            if request.url.path=='/api/calendars/calendar.demo':return httpx.Response(200,json=[])
            return httpx.Response(404)
        self.home=HomeBridge(HomeConfig(True,'http://127.0.0.1:8123','synthetic-calendar-token',{'weather':'weather.demo'}),httpx.MockTransport(transport))
        self.sources=SourceStore(self.root,self.protector);self.exp=Experiences(self.home,self.sources)
        self.event={'calendar':'calendar.demo','title':'Synthetic appointment','start':'2026-09-22T10:00','end':'2026-09-22T11:00','timezone':'America/New_York'}
        self.writer=CalendarWriter(self.exp,self.root,self.protector)

    def grant(self,write=True):
        return self.exp.save_sources({'calendars':['calendar.demo'],'writable_calendars':['calendar.demo'] if write else []},self.sources.revision)

    def posts(self):return [r for r in self.requests if r.method=='POST']

    def test_separate_write_permission_live_capability_and_payload(self):
        self.grant(False)
        with self.assertRaises(PermissionError):self.writer.create(self.event,1,'a'*32,'display:a')
        self.assertEqual(self.posts(),[]);self.grant()
        self.state['attributes']['supported_features']=0
        with self.assertRaises(HomeUnavailable):self.writer.create(self.event,2,'a'*32,'display:a')
        self.state['attributes']['supported_features']=1
        result=self.writer.create(self.event,2,'a'*32,'display:a');self.assertEqual(result['status'],'accepted')
        self.assertEqual(json.loads(self.posts()[0].content)['start_date_time'],'2026-09-22T10:00:00-04:00')
        self.assertNotIn(b'Synthetic appointment',self.writer.path.read_bytes())
        self.assertNotIn(b'synthetic-calendar-token',self.writer.path.read_bytes())

    def test_restart_retry_and_uncertain_delivery_never_duplicate(self):
        self.grant();self.fail=True
        self.assertEqual(self.writer.create(self.event,1,'a'*32,'old-session')['status'],'unconfirmed')
        reloaded=CalendarWriter(self.exp,self.root,self.protector);self.fail=False
        self.assertEqual(reloaded.create(self.event,1,'a'*32,'new-session')['status'],'unconfirmed');self.assertEqual(len(self.posts()),1)
        with self.assertRaises(ExperienceConflict):reloaded.create({**self.event,'title':'Changed'},1,'a'*32,'new-session')
        with self.assertRaises(ExperienceConflict):reloaded.create(self.event,0,'b'*32,'new-session')
        self.grant(False)
        with self.assertRaises(PermissionError):reloaded.create(self.event,2,'c'*32,'new-session')
        self.assertEqual(len(self.posts()),1)

    def test_receipt_write_failure_stops_dispatch_and_corruption_is_preserved(self):
        self.grant()
        with patch.object(Path,'replace',side_effect=OSError):
            with self.assertRaises(ExperienceUnavailable):self.writer.create(self.event,1,'a'*32,'device')
        self.assertEqual(self.posts(),[])
        self.writer.path.write_text('broken')
        with self.assertRaises(ExperienceUnavailable):CalendarWriter(self.exp,self.root,self.protector).create(self.event,1,'a'*32,'device')
        self.assertEqual(self.writer.path.read_text(),'broken')

    def test_all_day_exclusive_end_and_clock_changes(self):
        event=CalendarEvent.model_validate({**self.event,'all_day':True,'start':'2026-09-22','end':'2026-09-23'})
        self.assertEqual(event.bounds(),{'start_date':'2026-09-22','end_date':'2026-09-23'})
        with self.assertRaises(ValueError):CalendarEvent.model_validate({**self.event,'start':'2026-03-08T02:30','end':'2026-03-08T03:30'})
        event=CalendarEvent.model_validate({**self.event,'start':'2026-11-01T01:15','end':'2026-11-01T01:45','start_fold':1,'end_fold':1})
        self.assertTrue(event.bounds()['start_date_time'].endswith('-05:00'))
        with self.assertRaises(ValueError):CalendarEvent.model_validate({**self.event,'end':self.event['start']})

    def test_api_paired_creation_validation_denial_and_source_default(self):
        for mode in ('device','validation'):
            settings=SettingsStore(protector=self.protector)
            with TestClient(create_app('a'*40,home=self.home,settings_store=settings,deployment_mode=mode)) as client:
                client.headers['Authorization']='Bearer '+'a'*40
                code=client.post('/v1/displays/pairing',json={'name':'Synthetic screen'}).json()['code']
                credential=client.post('/v1/displays/enroll',json={'code':code}).json()['credential']
                policy=client.get('/v1/display/source-settings').json();self.assertEqual(policy['sources']['writable_calendars'],[])
                self.assertEqual(client.put('/v1/display/source-settings',json={'revision':0,'sources':{'calendars':['calendar.demo'],'writable_calendars':['calendar.demo']}}).status_code,200)
                client.headers['Authorization']='Display '+credential
                self.assertEqual(client.put('/v1/display/source-settings',json={'revision':1,'sources':{}}).status_code,403)
                response=client.post('/v1/display/calendar/events',json={'revision':1,'request_id':'b'*32,'event':self.event})
                self.assertEqual(response.status_code,200 if mode=='device' else 403)
        self.assertEqual(len(self.posts()),1)

    def test_briefing_uses_selected_day_and_reports_partial_sources(self):
        self.grant(False)
        now=datetime.fromisoformat('2026-09-22T09:00:00-04:00').timestamp()
        self.exp.agenda=Mock(return_value={'status':'available','events':[
            {'title':'Already finished','start':'2026-09-22T07:00:00-04:00','end':'2026-09-22T08:00:00-04:00','all_day':False},
            {'calendar':'calendar.demo','title':'Today','start':'2026-09-22T10:00:00-04:00','end':'2026-09-22T11:00:00-04:00','all_day':False},
            {'title':'Yesterday','start':'2026-09-21','end':'2026-09-22','all_day':True}]})
        schedules=Mock();schedules.snapshot.return_value={'items':[],'events':[]}
        lists=Mock();lists.snapshot.return_value={'items':[{'id':'1','kind':'tasks','text':'Water plants','done':False},{'id':'2','kind':'shopping','text':'Coffee','done':False}]}
        briefing=DailyBriefing(self.exp,self.home,schedules,lists,clock=lambda:now)
        result=briefing.get('America/New_York')
        self.assertEqual(result['event_count'],1);self.assertEqual(result['events'][0]['title'],'Today')
        self.assertTrue(result['partial']);self.assertEqual(result['sources']['weather'],'unavailable')
        self.assertIn('Water plants',result['text']);self.assertEqual(result['shopping_count'],1)
        briefing.get('America/New_York');self.assertEqual(self.exp.agenda.call_count,1)
        self.sources.save({},1);self.assertEqual(briefing.get('America/New_York')['event_count'],0);self.assertEqual(self.exp.agenda.call_count,2)

    def test_spoken_and_typed_briefings_bypass_models_and_private_history(self):
        from backend.agent import EchoAgent
        from backend.memory import MemoryStore
        agent=EchoAgent(SettingsStore(protector=self.protector),provider=Mock(),memory=MemoryStore(protector=self.protector))
        agent.briefing=Mock();agent.briefing.get.return_value={'status':'complete','text':'A private briefing','sources':{'calendar':'available'}}
        for phrase in ('Give me my daily briefing',"What's on my agenda today?"):
            result=agent.respond(phrase)
            self.assertEqual(result['capability'],'briefing');self.assertEqual(result['text'],'A private briefing')
            self.assertNotIn('sources',result)
        agent.provider.complete.assert_not_called();self.assertEqual(agent.messages('device'),[])


if __name__=='__main__':unittest.main()
