import time
import unittest
from threading import Event
from unittest.mock import Mock
from backend.research_tasks import ResearchTasks
from backend.settings import EchoSettings
from backend.lookup import Answer, cited_answer
from backend.agent_configuration import model_profile
from backend.agent_runtime import configuration_fingerprint


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.settings=EchoSettings(provider='azure',model='test',azure_url='https://test.openai.azure.com',web_lookup='auto')
        self.store=Mock();self.store.snapshot.return_value=(self.settings,{'azure':'test-key'},1)
        self.entered=Event();self.release=Event();self.provider=Mock()
        def answer(*args,**kwargs):
            self.entered.set()
            while not self.release.wait(.01) and not kwargs['cancel'].is_set():pass
            return Answer('Brief result','Detailed result',[{'title':'Example','url':'https://example.org'}],True)
        self.provider.complete.side_effect=answer
        self.tasks=ResearchTasks(self.store,self.provider);self.addCleanup(self.tasks.close)
        self.addCleanup(self.release.set)

    def finish(self,owner):
        for _ in range(100):
            result=self.tasks.list(owner)[0]
            if not result['active']:return result
            time.sleep(.01)
        self.fail('Worker did not finish')

    def test_report_survives_refresh_is_private_and_has_no_home_tools(self):
        job=self.tasks.start('one','Compare these two speakers');self.assertTrue(self.entered.wait(1))
        self.assertEqual(self.tasks.list('two'),[])
        with self.assertRaises(KeyError):self.tasks.stop('two',job['id'])
        with self.assertRaises(ValueError):self.tasks.start('one','A second task')
        self.release.set();result=self.finish('one')
        self.assertEqual(result['state'],'completed');self.assertEqual(result['result']['display_text'],'Detailed result')
        self.assertFalse(result['persistent'])
        kwargs=self.provider.complete.call_args.kwargs
        self.assertTrue(kwargs['lookup'] and kwargs['detailed']);self.assertNotIn('memory',kwargs)
        self.tasks.delete('one',job['id']);self.assertEqual(self.tasks.list('one'),[])

    def test_cancel_does_not_publish_report_and_voice_tasks_are_visible(self):
        job=self.tasks.start('device','Research desk lamps');self.assertTrue(self.entered.wait(1))
        self.assertEqual(self.tasks.list('browser')[0]['id'],job['id'])
        self.tasks.stop('browser',job['id']);result=self.finish('device')
        self.assertEqual(result['state'],'cancelled');self.assertIsNone(result['result'])

    def test_disabled_search_does_not_start_provider(self):
        self.store.snapshot.return_value=(self.settings.model_copy(update={'web_lookup':'off'}),{},1)
        with self.assertRaises(ValueError):self.tasks.start('one','Research a lamp')
        self.provider.complete.assert_not_called()

    def test_long_reports_do_not_change_spoken_answer_limits(self):
        blocks=[{'type':'output_text','text':'Detailed evidence. '*200}]
        self.assertLessEqual(len(cited_answer(blocks).display_text),1100)
        self.assertGreater(len(cited_answer(blocks,limit=12000).display_text),1100)

    def test_provider_profiles_use_distinct_credentials_and_keep_azure_fingerprint(self):
        import hashlib,json
        for provider,expected in [('azure','azure-foundry'),('openai','openai-api'),('anthropic','anthropic'),('local','custom')]:
            settings=self.settings.model_copy(update={'provider':provider,'agent_runtime':'hermes'})
            validated=EchoSettings.model_validate(settings.model_dump())
            profile=model_profile(validated,{provider:'test-key'})
            self.assertEqual(profile['model_config']['provider'],expected)
            self.assertEqual(profile['provider_key'],'test-key')
        self.assertEqual(configuration_fingerprint(self.settings,{'azure':'test-key'}),hashlib.sha256(json.dumps([self.settings.azure_url,'test','test-key']).encode()).hexdigest())
        self.assertEqual(model_profile(self.settings.model_copy(update={'provider':'local'}),{})['provider_key'],'echo-local-no-key')

if __name__=='__main__':unittest.main()
