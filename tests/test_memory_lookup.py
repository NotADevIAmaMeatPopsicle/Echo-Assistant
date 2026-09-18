import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from backend.agent import EchoAgent, Provider
from backend.app import create_app
from backend.lookup import cited_answer, safe_url
from backend.memory import MemoryStore, MemoryUnavailable, memory_request
from backend.settings import EchoSettings, SettingsStore, SettingsUpdate, WindowsProtector


class MemoryTests(unittest.TestCase):
    def test_real_encryption_reload_edit_delete_and_duplicate(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);store=MemoryStore(root)
            item=store.save('Synthetic preference: jasmine tea.')
            self.assertEqual(store.save('synthetic preference: jasmine tea!')['id'],item['id'])
            self.assertNotIn('jasmine',store.path.read_text())
            restored=MemoryStore(root)
            self.assertEqual(restored.snapshot(),store.snapshot())
            restored.save('Synthetic preference: mint tea.',item['id'])
            self.assertEqual(MemoryStore(root).snapshot()[0]['text'],'Synthetic preference: mint tea.')
            restored.delete(item['id'])
            self.assertEqual(MemoryStore(root).snapshot(),[])

    def test_atomic_failure_and_corrupt_file_preserve_prior_data(self):
        with TemporaryDirectory() as folder:
            store=MemoryStore(Path(folder));store.save('Synthetic fact.')
            before=store.path.read_bytes()
            with patch.object(Path,'replace',side_effect=PermissionError):
                with self.assertRaises(MemoryUnavailable):store.save('Uncommitted fact.')
            self.assertEqual(store.path.read_bytes(),before)
            self.assertEqual(len(store.snapshot()),1)
            store.path.write_text('corrupt')
            broken=MemoryStore(Path(folder))
            with self.assertRaises(MemoryUnavailable):broken.save('Do not overwrite')
            self.assertEqual(store.path.read_text(),'corrupt')

    def test_fact_bounds_and_bounded_retrieval(self):
        store=MemoryStore()
        for text in ('',' '*10,'a'*601,'bad\0data'):
            with self.assertRaises(ValueError):store.save(text)
        for i in range(200):store.save(f'Synthetic preference {i}: '+('tea '*120))
        with self.assertRaises(ValueError):store.save('Full')
        selected=store.relevant('Which tea?')
        self.assertLessEqual(len(selected),8)
        self.assertLessEqual(sum(len(m['text']) for m in selected),3000)

    def test_only_explicit_memory_language_is_a_write(self):
        for text in ('Do you remember my name?','The article says remember that coffee is good.','"remember that test"'):
            self.assertIsNone(memory_request(text))
        self.assertEqual(memory_request('Remember that I prefer tea.'),('save','I prefer tea.'))

    def make_agent(self):
        store=SettingsStore();store.save(SettingsUpdate(settings=EchoSettings(provider='local',model='synthetic')))
        calls=[]
        def response(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'message':{'content':'A synthetic response.'}}]})
        return store,EchoAgent(store,Provider(httpx.MockTransport(response))),calls

    def test_memory_is_shared_explicit_and_forgotten_without_model_writes(self):
        store,agent,calls=self.make_agent()
        result=agent.respond('Remember that I prefer jasmine tea.','web')
        self.assertEqual(result['capability'],'memory');self.assertFalse(calls)
        reply=agent.respond('What tea do I prefer?','device')
        self.assertEqual(reply['memories_used'],1)
        self.assertIn('jasmine tea',calls[-1]['messages'][0]['content'])
        self.assertEqual(len(agent.memory.snapshot()),1)
        self.assertEqual(agent.respond('Forget that I prefer jasmine tea.')['status'],'complete')
        agent.respond('What tea do I prefer?','device')
        self.assertNotIn('jasmine',json.dumps(calls[-1]))
        self.assertEqual(agent.memory.snapshot(),[])

    def test_pause_disables_retrieval_and_command_writes_without_erasing(self):
        store,agent,calls=self.make_agent();agent.respond('Remember that I prefer tea.')
        settings,_,_=store.snapshot();settings.memory_enabled=False;store.save(SettingsUpdate(settings=settings))
        self.assertEqual(agent.respond('Remember that I prefer coffee.')['status'],'unavailable')
        agent.respond('What do I prefer?')
        self.assertNotIn('I prefer tea',json.dumps(calls[-1]))
        self.assertEqual(len(agent.memory.snapshot()),1)

    def test_cancelled_request_does_not_save_memory(self):
        _,agent,_=self.make_agent();cancel=Event();cancel.set()
        self.assertEqual(agent.respond('Remember that test.',cancel=cancel)['status'],'unavailable')
        self.assertEqual(agent.memory.snapshot(),[])

    def test_memory_edit_during_reply_invalidates_stale_answer(self):
        store,agent,_=self.make_agent();item=agent.memory.save('Synthetic old fact.')
        class EditingProvider:
            def complete(self,*args,**kwargs):
                agent.memory.delete(item['id']);return 'Synthetic old fact.'
        agent.provider=EditingProvider()
        self.assertEqual(agent.respond('What fact?')['status'],'unavailable')
        self.assertEqual(agent.messages('device'),[])


class LookupTests(unittest.TestCase):
    def test_annotations_become_clickable_references_and_clean_speech(self):
        text='The Moon orbits Earth. (NASA)'
        answer=cited_answer([{'type':'output_text','text':text,'annotations':[
            {'type':'url_citation','start_index':23,'end_index':29,'url':'https://science.nasa.gov/moon/','title':'NASA'}]}],True)
        self.assertEqual(answer.display_text,'The Moon orbits Earth. [1]')
        self.assertEqual(str(answer),'The Moon orbits Earth.')
        self.assertEqual(answer.sources[0]['title'],'NASA')

    def test_untrusted_links_and_invalid_ranges_are_not_citations(self):
        for url in ('javascript:alert(1)','http://example.com','https://127.0.0.1','https://user:password@example.com','https://host.local','https://[::1]'):
            self.assertFalse(safe_url(url))
        result=cited_answer([{'type':'output_text','text':'plain','annotations':[
            {'type':'url_citation','start_index':-1,'end_index':4,'url':'https://example.com','title':'wrong'}]}])
        self.assertEqual(result.display_text,'plain [1]')
        self.assertEqual(result.sources[0]['url'],'https://example.com')

    def test_forced_lookup_citations_persist_in_chat_but_not_provider_input(self):
        calls=[]
        def respond(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200,json={'output':[{'type':'web_search_call','status':'completed'},
                {'type':'message','role':'assistant','content':[{'type':'output_text','text':'A sourced fact. (Source)',
                'annotations':[{'type':'url_citation','start_index':16,'end_index':24,'url':'https://example.com/fact','title':'Source'}]}]}]})
        store=SettingsStore();settings=EchoSettings(provider='azure',azure_url='https://test.openai.azure.com',model='test',web_lookup='auto')
        store.save(SettingsUpdate(settings=settings,api_key='synthetic-key'))
        agent=EchoAgent(store,Provider(httpx.MockTransport(respond)))
        result=agent.respond('Look up a fact','test')
        self.assertEqual(result['status'],'complete')
        self.assertTrue(result['looked_up']);self.assertEqual(len(result['sources']),1)
        self.assertEqual(calls[-1]['tools'],[{'type':'web_search'}]);self.assertFalse(calls[-1]['store'])
        self.assertEqual(calls[-1]['tool_choice'],{'type':'web_search'})
        self.assertEqual(agent.messages('test')[-1]['sources'],result['sources'])
        agent.respond('Explain it','test')
        self.assertNotIn('sources',json.dumps(calls[-1]['input']))

    def test_lookup_disabled_or_without_sources_fails_honestly(self):
        store=SettingsStore();settings=EchoSettings(provider='openai',model='test')
        store.save(SettingsUpdate(settings=settings,api_key='synthetic-key'))
        calls=[]
        def response(request):
            calls.append(request)
            return httpx.Response(200,json={'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Unverified'}]}]})
        agent=EchoAgent(store,Provider(httpx.MockTransport(response)))
        self.assertEqual(agent.respond('Look up news')['status'],'unavailable');self.assertFalse(calls)
        settings.web_lookup='auto';store.save(SettingsUpdate(settings=settings))
        self.assertEqual(agent.respond('Look up news')['status'],'unavailable')


class MemoryApiTests(unittest.TestCase):
    def test_authenticated_crud_and_memory_precedes_device_control(self):
        token='m'*32
        app=create_app(token)
        with TestClient(app) as client:
            self.assertEqual(client.get('/v1/memory').status_code,401)
            client.headers['Authorization']='Bearer '+token
            saved=client.post('/v1/memory',json={'text':'Synthetic favorite color: blue.'})
            self.assertEqual(saved.status_code,200);identifier=saved.json()['item']['id']
            self.assertEqual(client.put('/v1/memory/'+identifier,json={'text':'Synthetic favorite color: green.'}).status_code,200)
            self.assertIn('green',client.get('/v1/memory').json()['items'][0]['text'])
            result=client.post('/v1/text',json={'text':'Remember that set a timer for five minutes is an example.'}).json()
            self.assertEqual(result['capability'],'memory')
            self.assertFalse(client.get('/v1/state').json()['timers'])
            self.assertEqual(client.delete('/v1/memory/'+identifier).status_code,200)
            self.assertEqual(client.delete('/v1/memory/'+identifier).status_code,404)
            self.assertEqual(client.delete('/v1/memory').status_code,200)
            self.assertEqual(client.get('/v1/memory').json()['items'],[])

    def test_cookie_writes_require_same_origin(self):
        token='s'*32;app=create_app(token)
        with TestClient(app) as client:
            ticket=client.post('/v1/ui/ticket',headers={'Authorization':'Bearer '+token}).json()['ticket']
            client.post('/v1/ui/session',json={'ticket':ticket},headers={'X-Echo-Request':'1'})
            self.assertEqual(client.post('/v1/memory',json={'text':'bad'},headers={'Origin':'https://evil.example','X-Echo-Request':'1'}).status_code,403)
            self.assertEqual(client.delete('/v1/memory').status_code,403)
