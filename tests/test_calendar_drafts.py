import json
import os
from pathlib import Path
from datetime import datetime
from threading import Event
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch

import httpx
from fastapi.testclient import TestClient
from backend.agent import EchoAgent,Provider,ProviderUnavailable
from backend.app import create_app
from backend.calendar_drafts import CalendarDrafts,ExtractedEvent,draft_request,extract
from backend.settings import SettingsStore,EchoSettings
from backend.linux_protection import LinuxProtector
from backend.memory import MemoryStore


EVENT={'title':'Lunch with Sam','start':'2026-09-21T12:00','end':None,'all_day':False,
       'timezone':'America/New_York','location':'','description':'','calendar_name':None,'questions':[]}


class CalendarDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        key=Path(self.temp.name)/'key';key.write_bytes(os.urandom(32));key.chmod(0o600)
        self.store=SettingsStore(protector=LinuxProtector(key));self.store.settings=EchoSettings(provider='azure',model='synthetic-model',azure_url='https://example.openai.azure.com',web_lookup='auto')
        self.store.keys={'azure':'synthetic-draft-key'}
        self.payloads=[];self.output=dict(EVENT);self.refusal=False;self.incomplete=False
        def transport(request):
            body=json.loads(request.content);self.payloads.append(body)
            content=[{'type':'refusal','refusal':'No'}] if self.refusal else [{'type':'output_text','text':json.dumps(self.output)}]
            return httpx.Response(200,json={'status':'incomplete' if self.incomplete else 'completed','output':[{'type':'message','role':'assistant','content':content}]})
        self.provider=Provider(httpx.MockTransport(transport))
        self.exp=Mock();self.exp.home._request.return_value={'time_zone':'America/New_York'}
        self.exp.sources.return_value={'items':[{'kind':'calendar','entity_id':'calendar.allowed','name':'Personal','writable':True,'available':True}]}
        self.clock=lambda:datetime.fromisoformat('2026-09-20T09:00:00-04:00').timestamp()
        self.drafts=CalendarDrafts(self.store,self.provider,self.exp,Mock(),clock=self.clock)

    def test_model_draft_has_no_tools_or_history_and_uses_server_reference(self):
        agent=EchoAgent(self.store,provider=self.provider,memory=MemoryStore(protector=self.store.protector));agent.calendar_drafts=self.drafts
        reply=agent.respond('Add lunch with Sam tomorrow at noon to my calendar',calendar_review=True)
        event=reply['calendar_draft']['event'];self.assertEqual(event['start'],'2026-09-21T12:00')
        self.assertEqual(event['end'],'2026-09-21T13:00');self.assertEqual(event['calendar'],'calendar.allowed')
        self.assertIn('Suggested duration:',reply['calendar_draft']['questions'][0])
        self.assertEqual(agent.messages('device'),[])
        body=self.payloads[0];self.assertNotIn('tools',body);self.assertFalse(body['store']);self.assertEqual(body['max_output_tokens'],self.store.settings.max_output_tokens)
        self.assertIn('2026-09-20T09:00:00-04:00',body['instructions'])
        self.assertNotIn('calendar.allowed',json.dumps(body));self.assertNotIn('synthetic-draft-key',json.dumps(body))
        self.assertTrue(body['text']['format']['strict']);self.exp.home._request.assert_called_once_with('GET','/api/config')
        self.assertTrue(draft_request('schedule lunch tomorrow at noon'))
        self.assertFalse(draft_request('What is on my calendar?'));self.assertFalse(draft_request('schedule a reminder for tomorrow'))
        before=len(self.payloads)
        self.assertNotIn('calendar_draft',agent.respond('Add lunch tomorrow to my calendar'))
        self.assertEqual(len(self.payloads),before)

    def test_incomplete_dates_and_calendar_ambiguity_stay_editable(self):
        self.output.update(start=None,calendar_name='Not approved',questions=['Do you mean 3 AM or 3 PM?'])
        self.exp.sources.return_value['items'].append({'kind':'calendar','entity_id':'calendar.other','name':'Other','writable':True,'available':True})
        result=self.drafts.respond('Add dentist tomorrow at 3 to my calendar',zone_name='America/New_York')['calendar_draft']
        self.assertEqual(result['event']['start'],'');self.assertEqual(result['event']['calendar'],'')
        self.assertIn('AM or 3 PM',result['questions'][0]);self.assertEqual(result['expires_at'],self.clock()+900)

    def test_invalid_model_output_refusal_incomplete_and_cancel_cannot_become_events(self):
        self.output['calendar']='calendar.secret'
        self.assertNotIn('calendar_draft',self.drafts.respond('event',zone_name='UTC'))
        self.output=dict(EVENT);self.refusal=True
        self.assertNotIn('calendar_draft',self.drafts.respond('event',zone_name='UTC'))
        self.refusal=False;self.incomplete=True
        self.assertNotIn('calendar_draft',self.drafts.respond('event',zone_name='UTC'))
        cancel=Event();cancel.set();count=len(self.payloads)
        self.assertNotIn('calendar_draft',self.drafts.respond('event',zone_name='UTC',cancel=cancel));self.assertEqual(count,len(self.payloads))
        self.exp.home._request.assert_not_called()

    def test_clock_changes_and_all_day_bounds(self):
        self.output.update(start='2026-03-08T02:30',end='2026-03-08T03:30')
        result=self.drafts.respond('event',zone_name='America/New_York')['calendar_draft']
        self.assertEqual(result['event']['end'],'');self.assertTrue(any('clock' in q for q in result['questions']))
        self.output.update(start='2026-11-01T01:15',end='2026-11-01T01:45')
        result=self.drafts.respond('event',zone_name='America/New_York')['calendar_draft']
        self.assertTrue(any('occurrence' in q for q in result['questions']))
        self.output.update(start='2026-09-21',end=None,all_day=True)
        self.assertEqual(self.drafts.respond('event',zone_name='UTC')['calendar_draft']['event']['end'],'2026-09-22')

    def test_api_requires_auth_allows_paired_drafts_and_does_not_grant_calendar_write(self):
        with TestClient(create_app('d'*40,settings_store=self.store,provider=self.provider,deployment_mode='validation')) as client:
            body={'text':'Lunch tomorrow at noon','timezone':'UTC'}
            self.assertEqual(client.post('/v1/display/calendar/draft',json=body).status_code,401)
            client.headers['Authorization']='Bearer '+'d'*40
            mini=client.post('/v1/text',json={'text':'Add lunch tomorrow to my calendar','calendar_review':True})
            self.assertEqual(mini.status_code,200);self.assertIn('calendar_draft',mini.json())
            legacy=client.post('/v1/text',json={'text':'Add lunch tomorrow to my calendar'})
            self.assertEqual(legacy.status_code,200);self.assertNotIn('calendar_draft',legacy.json())
            code=client.post('/v1/displays/pairing',json={'name':'Synthetic draft screen'}).json()['code']
            credential=client.post('/v1/displays/enroll',json={'code':code}).json()['credential']
            client.headers['Authorization']='Display '+credential
            result=client.post('/v1/display/calendar/draft',json=body)
            self.assertEqual(result.status_code,200);self.assertEqual(result.json()['calendar_draft']['event']['calendar'],'')
            chat=client.post('/v1/chat',json={'text':'Add lunch tomorrow to my calendar','calendar_review':True})
            self.assertEqual(chat.status_code,200);self.assertIn('calendar_draft',chat.json())
            self.assertEqual(client.get('/v1/display/source-settings').status_code,403)
            self.assertEqual(client.post('/v1/display/calendar/draft',json={**body,'timezone':'Not a zone'}).status_code,422)
            self.assertEqual(client.post('/v1/display/calendar/events',json={'revision':0,'request_id':'a'*32,
                'event':{**result.json()['calendar_draft']['event'],'calendar':'calendar.unapproved'}}).status_code,403)

    def test_anthropic_and_local_use_one_tool_free_request_and_validate_response(self):
        for provider in ('anthropic','local'):
            calls=[]
            def transport(request):
                calls.append(json.loads(request.content))
                result={'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(EVENT)}]} if provider=='anthropic' else {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(EVENT)}}]}
                return httpx.Response(200,json=result)
            settings=EchoSettings(provider=provider,model='synthetic')
            actual=extract(Provider(httpx.MockTransport(transport)),settings,{provider:'synthetic'},'lunch','2026-09-20T09:00:00Z',None)
            self.assertEqual(actual.title,EVENT['title']);self.assertEqual(len(calls),1);self.assertNotIn('tools',calls[0])


if __name__=='__main__':unittest.main()
