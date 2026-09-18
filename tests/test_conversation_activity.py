import asyncio
from threading import Event
import unittest

from backend.conversation_activity import Conversations, ConversationBusy
from backend.conversation_request import run_conversation


class ConversationActivityTests(unittest.TestCase):
    def test_session_bound_stop_cannot_cancel_new_request(self):
        tasks = Conversations(); first = tasks.begin('one')
        self.assertEqual(tasks.snapshot('two')['state'], 'idle')
        with self.assertRaises(KeyError): tasks.stop('two', first.id)
        with self.assertRaises(ConversationBusy): tasks.begin('one')
        self.assertFalse(first.cancel.is_set())
        tasks.stop('one', first.id)
        self.assertTrue(tasks.snapshot('one')['active'])
        self.assertEqual(tasks.snapshot('one')['state'], 'stopping')
        first.finish(None); second = tasks.begin('one')
        with self.assertRaises(KeyError): tasks.stop('one', first.id)
        self.assertFalse(second.cancel.is_set())

    def test_public_progress_is_bounded_and_contains_no_prompt_or_reasoning(self):
        tasks = Conversations(); job = tasks.begin('one')
        for _ in range(40): job.progress('checking'); job.progress('thinking')
        job.progress('arbitrary private tool payload')
        job.finish({'status':'complete','text':'private answer','reasoning':'private reasoning'})
        result = tasks.snapshot('one')
        self.assertLessEqual(len(result['events']), 16)
        self.assertNotIn('private', str(result))
        self.assertNotIn('arbitrary', str(result))
        self.assertFalse(result['active'])
        self.assertEqual(result['state'], 'completed')
        job.progress('acting')
        self.assertEqual(tasks.snapshot('one'), result)

    def test_capacity_preserves_active_handles_and_expires_completed_metadata(self):
        tasks = Conversations()
        for i in range(16): tasks.begin(str(i))
        with self.assertRaises(ConversationBusy): tasks.begin('overflow')
        tasks.sessions['0'].finish({'status':'complete'})
        tasks.begin('overflow')
        self.assertEqual(tasks.snapshot('0')['state'], 'idle')
        self.assertEqual(len(tasks.sessions), 16)
        job = tasks.sessions['1']; job.finish({'status':'complete'}); job.finished -= 1801
        self.assertEqual(tasks.snapshot('1')['state'], 'idle')

    def test_cancellation_retains_action_receipts_and_unconfirmed_stop(self):
        tasks = Conversations(); job = tasks.begin('one')
        tasks.stop('one', job.id); job.progress('unconfirmed')
        job.finish({'status':'unavailable','text':'not retained', 'home_actions':[
            {'entity_id':'light.study','action':'brightness','value':30,'status':'complete','attempted':True}]})
        result = tasks.snapshot('one')
        self.assertEqual(result['state'], 'unconfirmed')
        self.assertFalse(result['active'])
        self.assertEqual(result['home_actions'][0]['value'], 30)
        self.assertNotIn('not retained', str(result))
        tasks.clear('one'); self.assertEqual(tasks.snapshot('one')['state'], 'idle')

    def test_stop_reaches_worker_before_terminal_status_and_retains_receipts(self):
        class Connection:
            async def is_disconnected(self): return False
        tasks = Conversations(); job = tasks.begin('one'); entered = Event(); released = Event()
        receipt = {'entity_id':'light.study','action':'turn_on','status':'complete','attempted':True}
        def worker(*, cancel):
            entered.set()
            if not cancel.wait(2): raise RuntimeError('Cancellation did not reach worker')
            released.set()
            return {'status':'unavailable','home_actions':[receipt]}
        async def exercise():
            pending = asyncio.create_task(run_conversation(Connection(), Event(), worker, activity=job))
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            self.assertEqual(tasks.stop('one', job.id)['state'], 'stopping')
            result = await pending
            self.assertTrue(released.is_set())
            self.assertEqual(result['status'], 'cancelled')
            self.assertEqual(tasks.snapshot('one')['home_actions'], [receipt])
            self.assertFalse(tasks.snapshot('one')['active'])
        asyncio.run(exercise())


if __name__ == '__main__': unittest.main()
