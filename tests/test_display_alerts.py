import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import RLock
import unittest
from unittest.mock import patch
import wave

from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.core import Assistant
from backend.display_alerts import DisplayAlerts, Receipt
from backend.schedules import ScheduleStore
from backend.settings import SettingsStore
from backend.linux_protection import LinuxProtector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from alerts import Alerts, chime

DESK = 'display:'+'a'*32
OTHER = 'display:'+'b'*32


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); key = self.root/'key'; key.write_bytes(os.urandom(32)); key.chmod(0o600)
        self.protector = LinuxProtector(key); self.now = 1000.
        self.core = Assistant(clock=lambda:self.now, wall_clock=lambda:self.now, storage=self.root/'timers.json')
        self.schedules = ScheduleStore(self.root, self.protector, lambda:self.now)
        self.alerts = DisplayAlerts(self.core, self.schedules, lambda:self.now)

    def test_timer_ownership_restart_and_local_pronoun_scope(self):
        old = self.core.start_timer(1)
        raw = json.loads(self.core.storage.read_text()); raw[0].pop('destination'); raw[0].pop('occurrence')
        self.core.storage.write_text(json.dumps(raw))
        restored = Assistant(clock=lambda:self.now, wall_clock=lambda:self.now, storage=self.core.storage)
        self.assertEqual(restored.timer_states()[0]['destination'], 'round')
        self.assertEqual(restored.respond('cancel my timer', destination=DESK)['text'], 'There are no active timers.')
        item = restored.respond('set a timer for five minutes', destination=DESK)
        restarted = Assistant(clock=lambda:self.now, wall_clock=lambda:self.now, storage=self.core.storage)
        self.assertEqual(restarted.timers[item['timer_id']].destination, DESK)
        restarted.respond('cancel it', timer_context=item, destination=DESK)
        self.assertEqual(list(restarted.timers), [old])

    def test_leases_cross_endpoint_snooze_stale_receipts_and_restart_ack(self):
        identifier = self.core.start_timer(1, destination=DESK); self.now += 2
        item = self.alerts.inbox(DESK)['items'][0]; self.assertEqual(self.alerts.inbox(OTHER)['items'], [])
        with self.assertRaises(HTTPException): self.alerts.claim(OTHER, identifier, item['occurrence'])
        claim = self.alerts.claim(DESK, identifier, item['occurrence'])
        with self.assertRaises(HTTPException): self.alerts.claim(DESK, identifier, item['occurrence'])
        receipt = Receipt(occurrence=item['occurrence'], token=claim['token'], outcome='played')
        self.core.snooze_timer(identifier)
        self.assertFalse(self.alerts.valid(DESK, identifier, item['occurrence'], claim['token']))
        with self.assertRaises(HTTPException): self.alerts.receipt(DESK, identifier, receipt)
        self.now += 301; item = self.alerts.inbox(DESK)['items'][0]
        claim = self.alerts.claim(DESK, identifier, item['occurrence'])
        receipt = Receipt(occurrence=item['occurrence'], token=claim['token'], outcome='played')
        self.assertTrue(self.alerts.receipt(DESK, identifier, receipt)['accepted'])
        self.assertTrue(self.alerts.receipt(DESK, identifier, receipt)['accepted'])
        restored = Assistant(clock=lambda:self.now, wall_clock=lambda:self.now, storage=self.core.storage)
        self.assertTrue(restored.timer_states()[0]['notified'])

    def test_quiet_hours_late_start_and_schedule_destination_migration(self):
        notice = self.schedules.notify('Laundry', 'Synthetic reminder', True, destination=DESK)
        self.schedules.set_quiet({'enabled':True, 'timezone':'UTC', 'start':'00:00', 'end':'23:59', 'alarms_override':True}, 0)
        self.assertFalse(self.alerts.inbox(DESK)['items'][0]['audible'])
        timer = self.core.start_timer(1, destination=DESK); self.now += 2
        self.assertTrue(next(i for i in self.alerts.inbox(DESK)['items'] if i['id']==timer)['audible'])
        self.now += 901
        self.assertFalse(next(i for i in self.alerts.inbox(DESK)['items'] if i['id']==timer)['audible'])
        self.assertFalse(any(i['id']==notice['id'] for i in self.alerts.inbox(DESK)['items']))
        schedule = {'title':'Wake', 'kind':'alarm', 'time':'07:00', 'timezone':'UTC', 'weekdays':[0,1,2,3,4,5,6]}
        item = self.schedules.save(schedule, 1, destination=DESK)
        self.schedules.save({**schedule,'title':'Changed'}, 2, item['id'], destination=OTHER)
        restored = ScheduleStore(self.root, self.protector, lambda:self.now)
        self.assertEqual(restored.snapshot()['items'][0]['destination'], DESK)
        old = restored.state; old['items'][0].pop('destination'); old['events'][0].pop('destination')
        ScheduleStore.validate_saved(old)
        self.assertEqual(old['items'][0]['destination'], 'round'); self.assertEqual(old['events'][0]['destination'], 'round')

    def test_real_chat_timer_route_and_revocation(self):
        owner = {'Authorization':'Bearer '+'synthetic-owner-'*3}
        with patch('backend.app.Assistant', return_value=self.core):
            with TestClient(create_app('synthetic-owner-'*3, settings_store=SettingsStore(protector=self.protector))) as client:
                code = client.post('/v1/displays/pairing', headers=owner, json={'name':'Synthetic desk'}).json()['code']
                paired = client.post('/v1/displays/enroll', json={'code':code}).json()
                headers = {'Authorization':'Display '+paired['credential'], 'X-Echo-Request':'1'}
                reply = client.post('/v1/chat', headers=headers, json={'text':'set a timer for five seconds'})
                self.assertEqual(reply.status_code, 200, reply.text)
                identifier = reply.json()['timer_id']; self.now += 6
                item = client.get('/v1/display/alerts', headers=headers).json()['items'][0]
                self.assertEqual(item['destination'], 'display:'+paired['id']); self.assertTrue(item['audible'])
                round_state = client.get('/v1/state', headers=owner).json()['timers'][0]
                self.assertTrue(round_state['notified'])  # Existing round workers cannot speak a Pi timer.
                self.assertEqual(client.post('/v1/timers/'+identifier+'/ack',headers=owner).status_code,404)
                self.assertEqual(client.post('/v1/display/alerts/'+identifier+'/claim',headers=headers,json={'occurrence':item['occurrence']}).status_code,200)
                client.delete('/v1/displays/'+paired['id'], headers=owner)
                self.assertEqual(client.get('/v1/display/alerts',headers=headers).status_code,401)

    def test_native_chime_disabled_output_missing_and_receipt_retry_without_replay(self):
        class Music:
            lock = RLock()
            def __init__(self): self.focused = False
            def held(self): return self.focused
            def focus(self, client, busy): self.focused = busy
        starts = []; attempts = []; fail = [True]
        class Player:
            returncode = 0
            def poll(self): return 0
        def popen(args, **kwargs):
            raw = kwargs['stdin'].read()
            with wave.open(io.BytesIO(raw)) as wav:
                self.assertEqual(wav.getparams()[:3],(1,2,48000))
            starts.append(args); return Player()
        item = {'id':'c'*32,'occurrence':'1','audible':True,'label':'Tea'}
        def request(path,body=None):
            attempts.append(path)
            if path.endswith('/alerts'): return {'items':[item]}
            if path.endswith('/claim'): return {'token':'d'*64}
            if path.endswith('/check'): return {'valid':True}
            if path.endswith('/receipt') and fail[0]: fail[0]=False; raise OSError('Simulated lost response')
            return {'accepted':True}
        receiver = Alerts(request, Music(), self.root, devices=lambda:[{'id':'hw:CARD=Speaker','name':'Speaker'}], popen=popen)
        receiver.cycle(); self.assertEqual(attempts,[]); self.assertEqual(starts,[])
        with self.assertRaises(ValueError): receiver.configure({'enabled':True,'output':'hw:CARD=Missing','volume':2})
        receiver.configure({'enabled':True,'output':'hw:CARD=Speaker','volume':2})
        with self.assertRaises(OSError): receiver.cycle()
        receiver.cycle(); receiver.cycle()
        self.assertEqual(len(starts),1); self.assertFalse(receiver.music.focused)
        self.assertEqual(sum(p.endswith('/receipt') for p in attempts),2)
        with wave.open(io.BytesIO(chime(2))) as wav:
            from array import array
            samples=array('h',wav.readframes(wav.getnframes()))
            self.assertLess(max(abs(x) for x in samples),500)
        receiver.path.write_text('broken')
        damaged = Alerts(request, Music(), self.root, devices=lambda:[], popen=popen)
        damaged.cycle(); self.assertTrue(damaged.config_error); self.assertEqual(damaged.path.read_text(),'broken')


if __name__=='__main__': unittest.main()
