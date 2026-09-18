import unittest
from backend.activation import Activation


class ActivationTests(unittest.TestCase):
    def test_actual_cue_completion_starts_listening_before_old_blind_delay(self):
        now=[0.]
        gate=Activation(True,clock=lambda:now[0])
        command=gate.begin()
        self.assertEqual(command,f'WAKE {gate.request}\n'.encode())
        now[0]=.54
        self.assertIsNone(gate.poll())
        gate.receive(f'EVENT listening_ready={gate.request}')
        self.assertEqual(gate.poll(),'listening')

    def test_stale_readiness_cannot_accept_speech_for_next_activation(self):
        now=[0.];gate=Activation(True,clock=lambda:now[0])
        gate.begin();old=gate.request
        gate.begin()
        while gate.request==old: gate.begin()
        gate.receive(f'EVENT listening_ready={old}')
        self.assertIsNone(gate.poll())
        now[0]=2.1
        self.assertEqual(gate.poll(),'timeout')

    def test_old_firmware_retains_explicit_legacy_delay(self):
        now=[0.];gate=Activation(False,clock=lambda:now[0])
        self.assertEqual(gate.begin(),b'WAKE\n')
        now[0]=.5;self.assertIsNone(gate.poll())
        now[0]=.86;self.assertEqual(gate.poll(),'listening')
