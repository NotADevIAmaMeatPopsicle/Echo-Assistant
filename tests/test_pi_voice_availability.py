"""Read-only availability probes; synthetic devices, no capture or playback."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from listener import Listener, VoiceUnavailable, private_audio_endpoints
from tests.test_pi_listener import Music


class OneAttempt:
    """Let run() attempt once without sleeping or opening real hardware."""
    def __init__(self):self.waits=0
    def wait(self,seconds):self.waits+=1;return self.waits>1
    def is_set(self):return False


class PiVoiceAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=100.;self.probes=[];self.captures=[]
        self.state={'available':True,'sources':[],'sinks':[]}
        def probe():self.probes.append(True);return deepcopy(self.state)
        self.listener=Listener(lambda *args:{'available':True},Music(),self.temp.name,
            captures=lambda:[{'id':'echo_cancelled'},{'id':'raw_mic'}],
            speakers=lambda:[{'id':'echo_processed'},{'id':'raw_speaker'}],
            endpoint_probe=probe,popen=lambda *a,**k:self.fail('A real child process must never start'))
        self.listener.config.update(enabled=True,muted=False,input='echo_cancelled',output='echo_processed',volume=2)
        self.listener.host_ready=True;self.listener.last_host=self.now
        self.clock=patch('listener.time.monotonic',side_effect=lambda:self.now);self.clock.start();self.addCleanup(self.clock.stop)

    def attempt(self,listener=None):
        listener=listener or self.listener;listener.stop=OneAttempt();listener.run()

    def test_named_hints_without_private_endpoints_are_precise_and_do_not_capture(self):
        self.attempt()
        self.assertEqual(self.listener.phase,'unavailable')
        self.assertIn('processed microphone and speaker route is missing',self.listener.error)
        self.assertIn('Reconnect the intended hardware',self.listener.error)
        self.assertIsNone(self.listener.capture)
        self.assertEqual(self.listener.diagnostics()['frames'],0)
        with patch.object(self.listener,'ready',return_value=True):
            state=self.listener.settings()
        self.assertEqual(state['error'],self.listener.error)
        self.assertIn('echo_cancelled',{d['id'] for d in state['inputs']})
        self.assertEqual(len(self.probes),1)

    def test_processed_probe_is_cached_recovers_and_does_not_change_configuration(self):
        before=deepcopy(self.listener.config)
        self.assertIn('route is missing',self.listener.audio_availability_error(before))
        self.state.update(sources=['echo_cancelled'],sinks=['echo_processed'])
        for _ in range(8):
            self.listener.check(before)
            self.assertIn('route is missing',self.listener.audio_availability_error(before))
        self.assertEqual(len(self.probes),1)
        self.now+=5.1
        self.assertIsNone(self.listener.audio_availability_error(before))
        self.assertEqual(len(self.probes),2);self.assertEqual(self.listener.config,before)
        self.assertFalse(self.listener.path.exists())

    def test_direct_alsa_and_custom_processed_paths_do_not_probe_private_server(self):
        self.listener.config.update(input='raw_mic',output='raw_speaker',echo_cancelled_input=True)
        self.assertIsNone(self.listener.audio_availability_error(self.listener.config))
        self.assertEqual(self.probes,[])
        self.listener.config['input']='missing_microphone'
        self.assertIn('selected microphone is unavailable',self.listener.audio_availability_error(self.listener.config))
        self.listener.config.update(input='raw_mic',output='missing_speaker')
        self.assertIn('selected speaker is unavailable',self.listener.audio_availability_error(self.listener.config))
        self.assertEqual(self.probes,[])

    def test_retry_reaches_only_the_selected_input_after_routes_recover(self):
        self.attempt();self.assertEqual(self.captures,[])
        self.now+=5.1;self.state.update(sources=['echo_cancelled'],sinks=['echo_processed'])
        class Detector:
            def reset(self):pass
            def feed(self,frame):raise InterruptedError()
        self.listener.detector_factory=lambda path:Detector()
        def microphone(config):
            self.captures.append(config['input'])
            return (frame for frame in [b'\0'*2560])
        self.listener.microphone=microphone;self.attempt()
        self.assertEqual(self.captures,['echo_cancelled'])
        self.assertIsNone(self.listener.error)
        self.assertEqual(self.listener.config['output'],'echo_processed')
        self.assertEqual(self.listener.config['volume'],2)

    def test_only_selected_private_endpoint_is_required(self):
        self.listener.config['output']='raw_speaker';self.state['sources']=['echo_cancelled']
        self.assertIsNone(self.listener.audio_availability_error(self.listener.config))
        self.listener.config.update(input='raw_mic',output='echo_processed')
        self.assertIn('processed speaker route is missing',self.listener.audio_availability_error(self.listener.config))

    def test_private_service_and_host_failures_are_distinct(self):
        self.state={'available':False,'reason':'private_server_unavailable'}
        self.assertIn('private Echo audio service is unavailable',self.listener.audio_availability_error(self.listener.config))
        self.listener.host_ready=False;self.attempt()
        self.assertEqual(self.listener.error,'Waiting for the private speech host.')
        with self.assertRaisesRegex(VoiceUnavailable,'private speech host is unavailable'):
            self.listener.check(self.listener.config)
        with patch.object(self.listener,'ready',return_value=True):
            self.assertEqual(self.listener.settings()['error'],'Waiting for the private speech host.')

    def test_model_load_failure_has_fixed_runtime_message_without_payload(self):
        self.state.update(sources=['echo_cancelled'],sinks=['echo_processed'])
        def failed(path):raise RuntimeError('synthetic private path or payload must not appear')
        self.listener.detector_factory=failed;self.attempt()
        self.assertIn('wake runtime or model could not load',self.listener.error)
        self.assertNotIn('synthetic',self.listener.error)
        self.assertIsNone(self.listener.capture)

    def test_muting_remains_possible_when_private_routes_are_missing(self):
        with patch.object(self.listener,'ready',return_value=True):
            state=self.listener.control('mute')
        self.assertTrue(state['settings']['muted']);self.assertEqual(state['settings']['volume'],2)
        self.assertEqual(state['settings']['input'],'echo_cancelled')

    def test_health_loop_reuses_the_bounded_probe_without_capture(self):
        self.listener.stop=OneAttempt();self.listener.health()
        self.assertTrue(self.listener.host_ready);self.assertEqual(len(self.probes),1)
        self.listener.stop=OneAttempt();self.listener.health()
        self.assertEqual(len(self.probes),1);self.assertIsNone(self.listener.capture)

    def test_private_probe_is_control_only_explicit_socket_and_bounded(self):
        calls=[]
        def run(args,**kwargs):
            calls.append((args,kwargs))
            name='echo_cancelled' if args[-1]=='sources' else 'echo_processed'
            return SimpleNamespace(returncode=0,stdout='0\t'+name+'\tmodule-echo-cancel.c\ts16le\tIDLE\n')
        with patch('listener.Path.is_socket',return_value=True):
            state=private_audio_endpoints(run=run,uid=1000)
        self.assertTrue(state['available']);self.assertEqual(state['sources'],['echo_cancelled']);self.assertEqual(state['sinks'],['echo_processed'])
        self.assertEqual(len(calls),2)
        for args,kwargs in calls:
            self.assertEqual(args[0],'pactl');self.assertTrue(args[1].startswith('--server=unix:'))
            self.assertIn('echo-audio',args[1]);self.assertEqual(args[2:4],['list','short'])
            self.assertEqual(kwargs['timeout'],1);self.assertEqual(kwargs['stderr'],subprocess.DEVNULL)

    def test_missing_socket_and_failed_probe_do_not_leak_error_output(self):
        with patch('listener.Path.is_socket',return_value=False):
            self.assertFalse(private_audio_endpoints(run=lambda *a,**k:self.fail('Must not query another server'),uid=1000)['available'])
        def fail(*args,**kwargs):raise subprocess.TimeoutExpired('sensitive command',1,output='private diagnostic')
        with patch('listener.Path.is_socket',return_value=True):
            state=private_audio_endpoints(run=fail,uid=1000)
        self.assertEqual(state,{'available':False,'reason':'private_server_unavailable'})


if __name__=='__main__':unittest.main()
