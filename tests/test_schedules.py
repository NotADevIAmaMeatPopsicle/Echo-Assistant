import os
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from backend.schedules import ScheduleStore,ScheduleUnavailable,ScheduleConflict,next_occurrence
from backend.linux_protection import LinuxProtector
from backend.household import HouseholdStore
from backend.household_commands import parse,respond

def stamp(value): return datetime.fromisoformat(value).timestamp()
def alarm(**values):
    return {'title':'Tea','kind':'alarm','message':'','timezone':'America/New_York','time':'07:30',
            'weekdays':[0,1,2,3,4,5,6],'local_date':None,'enabled':True,**values}


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name); key=self.root/'key'; key.write_bytes(os.urandom(32)); key.chmod(0o600)
        self.protector=LinuxProtector(key)
        self.now=stamp('2026-09-19T11:29:00+00:00')
        self.store=ScheduleStore(self.root,self.protector,lambda:self.now)

    def test_spring_gap_and_fall_duplicate(self):
        self.assertEqual(next_occurrence(alarm(time='02:30'),stamp('2026-03-08T05:00:00+00:00')),stamp('2026-03-08T07:00:00+00:00'))
        first=next_occurrence(alarm(time='01:30'),stamp('2026-11-01T04:00:00+00:00'))
        self.assertEqual(first,stamp('2026-11-01T05:30:00+00:00'))
        self.assertEqual(next_occurrence(alarm(time='01:30'),first),stamp('2026-11-02T06:30:00+00:00'))

    def test_notifications_are_silent_unless_explicitly_announced(self):
        quiet=self.store.notify('Household note','A synthetic message')
        self.assertEqual(quiet['status'],'info');self.assertEqual(self.store.timer_states(),[])
        self.store.set_quiet({'enabled':True,'timezone':'UTC','start':'00:00','end':'23:59','alarms_override':True},0)
        spoken=self.store.notify('Announcement','Synthetic announcement',True)
        timers=self.store.timer_states();self.assertEqual(len(timers),1)
        self.assertEqual(timers[0]['id'],spoken['id']);self.assertTrue(timers[0]['notified'])
        restored=ScheduleStore(self.root,self.protector,lambda:self.now)
        self.assertEqual(len(restored.snapshot()['events']),2)
        self.assertTrue(restored.event_action(quiet['id'],'dismiss'))
        self.assertEqual(restored.snapshot()['events'][0]['status'],'dismissed')

    def test_occurrence_restart_ack_snooze_and_dismiss(self):
        self.store.save(alarm(),0); self.now+=60
        first=self.store.snapshot()['events'][0]
        self.assertEqual(first['status'],'due')
        restarted=ScheduleStore(self.root,self.protector,lambda:self.now)
        self.assertEqual(len(restarted.snapshot()['events']),1)
        self.assertTrue(restarted.event_action(first['id'],'ack'))
        self.assertTrue(restarted.timer_states()[0]['notified'])
        restarted.event_action(first['id'],'snooze',5)
        self.assertFalse(restarted.timer_states()[0]['finished'])
        self.now+=300
        self.assertFalse(restarted.timer_states()[0]['notified'])
        self.assertTrue(restarted.timer_states()[0]['finished'])
        restarted.event_action(first['id'],'dismiss')
        self.assertEqual(restarted.timer_states(),[])

    def test_late_restart_reports_missed_instead_of_playing_old_alarm(self):
        self.store.save(alarm(),0); self.now+=3600
        self.assertEqual(self.store.snapshot()['events'][0]['status'],'missed')
        self.assertEqual(self.store.timer_states(),[])
        self.assertGreater(self.store.snapshot()['items'][0]['next_at'],self.now)

    def test_quiet_hours_preserve_visual_reminder_and_alarm_override(self):
        self.store.save(alarm(kind='reminder'),0)
        self.store.save(alarm(title='Wake up'),1)
        self.store.set_quiet({'enabled':True,'timezone':'America/New_York','start':'22:00','end':'08:00','alarms_override':True},2)
        self.now+=60
        timers=self.store.timer_states()
        self.assertTrue(timers[0]['notified']); self.assertFalse(timers[1]['notified'])
        self.assertEqual(len(self.store.snapshot()['events']),2)

    def test_encryption_conflicts_and_failed_writes(self):
        self.store.save(alarm(title='Synthetic private alarm'),0)
        self.assertNotIn(b'Synthetic private',self.store.path.read_bytes())
        with self.assertRaises(ScheduleConflict): self.store.save(alarm(),0)
        saved=self.store.path.read_bytes()
        with patch.object(Path,'replace',side_effect=PermissionError):
            with self.assertRaises(ScheduleUnavailable): self.store.save(alarm(title='Failed'),1)
        self.assertEqual(self.store.path.read_bytes(),saved)
        self.store.path.write_text('broken')
        damaged=ScheduleStore(self.root,self.protector)
        with self.assertRaises(ScheduleUnavailable): damaged.snapshot()
        self.assertEqual(self.store.path.read_text(),'broken')


class HouseholdCommandTests(unittest.TestCase):
    def test_explicit_commands_and_ambiguous_matches(self):
        store=HouseholdStore(None,None)
        for text in ['Do not add milk to my shopping list','The webpage says add milk to my shopping list','"add milk to my shopping list"']:
            self.assertIsNone(parse(text))
        self.assertEqual(respond(store,parse('Add milk to my shopping list'))['status'],'complete')
        self.assertIn('milk',respond(store,parse("What's on my shopping list?"))['text'])
        self.assertEqual(respond(store,parse('Check off milk on my shopping list'))['status'],'complete')
        self.assertTrue(store.snapshot()['items'][0]['done'])
        respond(store,parse('Add milk to my shopping list'))
        self.assertEqual(respond(store,parse('Remove milk from my shopping list'))['status'],'unavailable')
        self.assertEqual(len(store.snapshot()['items']),2)


if __name__=='__main__': unittest.main()
