import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import subprocess
import sys
from threading import Thread
import unittest
from unittest.mock import patch

from backend.container_host import Host, request_voice_restart, main
from backend.lifecycle import Lifecycle, request_stop


class Child:
    def __init__(self, on_poll=None):
        self.returncode = None
        self.on_poll = on_poll
        self.stops = 0

    def poll(self):
        if self.on_poll: self.on_poll()
        return self.returncode

    def terminate(self):
        self.stops += 1
        self.returncode = 0

    def wait(self, timeout): return self.returncode


class ContainerSupervisorTests(unittest.TestCase):
    def test_validation_cannot_arm_a_voice_child(self):
        with patch('sys.platform','linux'), patch.dict(os.environ,{
                'ECHO_CONTAINER':'1','ECHO_VOICE_ENABLED':'1','ECHO_DEPLOYMENT_MODE':'validation'}):
            with self.assertRaisesRegex(RuntimeError,'paired device deployment'): main()

    def test_restart_refuses_stale_owner_and_api_only_validation_host(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError): request_voice_restart(root)
            with Lifecycle(root, 'host') as owner:
                path = root/'local/host-status.json'
                state = {'run_id':owner.identity,'updated_at':time.time(),'voice_enabled':False}
                path.write_text(json.dumps(state))
                with self.assertRaises(ValueError): request_voice_restart(root)
                state.update(voice_enabled=True,updated_at=time.time()-10)
                path.write_text(json.dumps(state))
                with self.assertRaises(ValueError): request_voice_restart(root)
                state['updated_at'] = time.time(); path.write_text(json.dumps(state))
                request_voice_restart(root)
                self.assertEqual((root/'local/voice-restart').read_text(),owner.identity)

    def test_api_only_never_launches_voice_and_stops_with_api(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); launched=[]; polls=0
            def tick():
                nonlocal polls
                polls += 1
                if polls > 2: api.returncode = 7
            api = Child(tick)
            def launch(name): launched.append(name); return api
            with patch.object(Lifecycle,'wait'):
                self.assertEqual(Host(root,False,launch=launch,ready=lambda:True).run(),7)
            self.assertEqual(launched,['app'])
            self.assertFalse((root/'local/host-process.json').exists())

    def test_explicit_stop_stays_paused_then_generation_bound_restart_replaces_child(self):
        with TemporaryDirectory() as directory:
            root=Path(directory); voices=[]; poll_count=0
            def tick():
                nonlocal poll_count
                poll_count += 1
                if poll_count == 2: voices[0].returncode=0
                if poll_count == 4:
                    self.assertEqual(len(voices),1)
                    request_voice_restart(root)
                if poll_count == 6: api.returncode=0
            api=Child(tick)
            def launch(name):
                if name=='app': return api
                child=Child(); voices.append(child); return child
            with patch.object(Lifecycle,'wait'):
                host=Host(root,True,launch=launch,ready=lambda:True)
                self.assertEqual(host.run(),0)
            self.assertEqual(len(voices),2)
            self.assertEqual(voices[1].stops,1,'API exit must gracefully stop the voice child')

    def test_voice_waits_for_api_readiness(self):
        with TemporaryDirectory() as directory:
            root=Path(directory); launched=[]; polls=0
            def tick():
                nonlocal polls
                polls+=1
                if polls==4: api.returncode=0
            api=Child(tick)
            def launch(name):
                launched.append((name,polls)); return api if name=='app' else Child()
            with patch.object(Lifecycle,'wait'):
                Host(root,True,launch=launch,ready=lambda:polls>=3).run()
            self.assertEqual(launched,[('app',0),('voice',3)])

    @unittest.skipUnless(sys.platform=='linux','Exercise real Linux process groups and lifecycle locks')
    def test_real_children_recover_apply_and_pause_without_restarting_api(self):
        with TemporaryDirectory() as directory:
            root=Path(directory); children=[]; failures=[]
            code=('import sys; from pathlib import Path; from backend.lifecycle import Lifecycle; '
                  'scope=Lifecycle(Path(sys.argv[1]),sys.argv[2]); scope.__enter__()\n'
                  'try:\n while not scope.stopped(): scope.wait(.02)\nfinally: scope.__exit__()')
            def launch(name):
                child=subprocess.Popen([sys.executable,'-c',code,str(root),'api' if name=='app' else 'voice'],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                children.append(child); return child
            host=Host(root,True,launch=launch,ready=lambda:True,grace=2)
            def until(check):
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    if check(): return
                    time.sleep(.05)
                raise AssertionError('Child lifecycle transition did not complete')
            def exercise():
                try:
                    until(lambda:(root/'local/voice-process.json').exists())
                    first=host.voice; api=host.api
                    first.kill(); first.wait(timeout=2)
                    until(lambda:host.voice is not None and host.voice is not first and (root/'local/voice-process.json').exists())
                    second=host.voice
                    request_voice_restart(root)
                    until(lambda:host.voice is not None and host.voice is not second and (root/'local/voice-process.json').exists())
                    self.assertIs(host.api,api)
                    self.assertIsNone(api.poll())
                    request_stop(root,'voice')
                    until(lambda:host.phase=='paused')
                    time.sleep(.6); self.assertIsNone(host.voice)
                    request_voice_restart(root)
                    until(lambda:host.voice is not None and (root/'local/voice-process.json').exists())
                except Exception as error: failures.append(error)
                finally: request_stop(root,'host')
            driver=Thread(target=exercise); driver.start()
            self.assertEqual(host.run(),0)
            driver.join(3); self.assertFalse(driver.is_alive())
            self.assertFalse(failures,failures)
            self.assertTrue(all(child.poll() is not None for child in children))


if __name__=='__main__': unittest.main()
