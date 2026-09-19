"""Synthetic doorbell states: permission selection, persistence, no false reconnect rings."""
from datetime import datetime,timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from backend.doorbells import Doorbells
from backend.experiences import Experiences,SourceStore,ExperienceUnavailable
from backend.home import HomeBridge,HomeConfig
from backend.linux_protection import LinuxProtector


class DoorbellTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        key=self.root/'key';key.write_bytes(os.urandom(32));key.chmod(0o600);self.protector=LinuxProtector(key)
        self.now=1_800_000_000.0;self.fail=False;self.calls=0
        self.states=[{'entity_id':'event.front','state':'unknown','attributes':{'friendly_name':'Front bell'}},
                     {'entity_id':'binary_sensor.back','state':'off','last_changed':self.stamp(-100),'attributes':{}},
                     {'entity_id':'camera.porch','state':'idle','attributes':{}}]
        def respond(request):
            self.assertEqual(request.method,'GET');self.assertEqual(request.url.path,'/api/states');self.calls+=1
            return httpx.Response(503) if self.fail else httpx.Response(200,json=self.states)
        home=HomeBridge(HomeConfig(True,'http://127.0.0.1:8123','synthetic-token',{'weather':'weather.demo'}),httpx.MockTransport(respond))
        self.sources=SourceStore(self.root,self.protector);self.experiences=Experiences(home,self.sources)
        self.bells=Doorbells(self.experiences,self.root,self.protector,lambda:self.now)

    def stamp(self,offset=0):return datetime.fromtimestamp(self.now+offset,timezone.utc).isoformat()
    def select(self):
        return self.experiences.save_sources({'cameras':['camera.porch'],'doorbells':[
            {'trigger':'event.front','label':'Front door','camera':'camera.porch'},
            {'trigger':'binary_sensor.back','label':'Back door','camera':None}]},self.sources.revision)
    def ring(self):self.now+=2;self.states[0]['state']=self.stamp();self.bells.tick()

    def test_opt_in_first_press_persistence_and_dismiss(self):
        self.bells.tick();self.assertEqual(self.calls,0);self.select();self.bells.tick()
        self.assertEqual(self.bells.snapshot()['events'],[]);self.ring();self.bells.tick()
        events=self.bells.snapshot()['events'];self.assertEqual(len(events),1);self.assertEqual(events[0]['camera'],'camera.porch')
        self.assertNotIn(b'event.front',self.bells.path.read_bytes())
        restored=Doorbells(self.experiences,self.root,self.protector,lambda:self.now);restored.tick()
        self.assertEqual(restored.snapshot()['events'],events)
        restored.dismiss(events[0]['id']);self.assertEqual(Doorbells(self.experiences,self.root,self.protector).snapshot()['events'],[])

    def test_reconnect_unknown_and_stale_events_do_not_fabricate_rings(self):
        self.select();self.bells.tick();self.fail=True;self.bells.tick();self.fail=False
        self.states[0]['state']=self.stamp();self.bells.tick();self.assertEqual(self.bells.snapshot()['events'],[])
        self.states[1].update(state='unknown');self.bells.tick()
        self.states[1].update(state='on',last_changed=self.stamp());self.bells.tick();self.assertEqual(self.bells.snapshot()['events'],[])
        self.states[1].update(state='off',last_changed=self.stamp());self.bells.tick();self.now+=2
        self.states[1].update(state='on',last_changed=self.stamp());self.bells.tick();self.assertEqual(len(self.bells.snapshot()['events']),1)
        self.states[0]['state']=self.stamp(-100);self.bells.tick();self.assertEqual(len(self.bells.snapshot()['events']),1)

    def test_permissions_and_bad_storage(self):
        with self.assertRaises(ValueError):self.experiences.save_sources({'doorbells':[{'trigger':'event.front','label':'Front','camera':'camera.porch'}]},0)
        self.select();self.bells.tick();self.ring()
        self.sources.save({},self.sources.revision);self.assertEqual(self.bells.snapshot()['events'],[])
        self.bells.tick();self.assertEqual(self.bells.events,[])
        self.bells.path.write_text('broken')
        restored=Doorbells(self.experiences,self.root,self.protector)
        with self.assertRaises(ExperienceUnavailable):restored.dismiss('a'*32)
        self.assertEqual(self.bells.path.read_text(),'broken')


if __name__=='__main__':unittest.main()
