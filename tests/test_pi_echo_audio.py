"""Configuration checks only; never starts an audio server or opens hardware."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

PI=Path(__file__).resolve().parents[1]/'deploy/pi'
def load(name):
    spec=importlib.util.spec_from_file_location('test_echo_'+name,PI/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
audio=load('setup_echo_audio');kiosk=load('kiosk')


class EchoAudioTests(unittest.TestCase):
    def test_named_pair_preserves_other_alsa_devices_and_can_be_removed(self):
        with TemporaryDirectory() as d:
            home=Path(d);original='pcm.other { type null }\n'
            (home/'.asoundrc').write_text(original)
            audio.configure(home,'plughw:CARD=USB,DEV=0','plughw:CARD=Speaker,DEV=0',1000)
            first=[p.read_text() for p in audio.files(home)]
            audio.configure(home,'plughw:CARD=USB,DEV=0','plughw:CARD=Speaker,DEV=0',1000)
            self.assertEqual(first,[p.read_text() for p in audio.files(home)])
            self.assertNotIn('pcm.!default',first[0]);self.assertIn(original.strip(),first[0])
            self.assertIn('aec_method=webrtc',first[1]);self.assertIn('save_aec=0',first[1])
            self.assertIn('analog_gain_control=0',first[1]);self.assertIn('digital_gain_control=0',first[1])
            audio.remove(home)
            self.assertEqual((home/'.asoundrc').read_text().strip(),original.strip())
            self.assertFalse(audio.files(home)[1].exists())

    def test_unmanaged_configuration_and_invalid_devices_leave_files_intact(self):
        with TemporaryDirectory() as d:
            home=Path(d);path=audio.files(home)[2];path.parent.mkdir(parents=True)
            path.write_text('Existing user unit')
            with self.assertRaises(ValueError):audio.configure(home,'hw:USB,0','hw:USB,0',1000)
            self.assertFalse((home/'.asoundrc').exists());self.assertEqual(path.read_text(),'Existing user unit')
        for bad in ('default','null','echo_processed','hw:USB,0\nload-module other','hw:USB,0;command'):
            with self.assertRaises(ValueError):audio.pcm(bad)

    def test_browser_uses_processing_server_only_for_explicit_matched_pair(self):
        with TemporaryDirectory() as d:
            home=Path(d);p=home/'.config/echo-display/voice.json';p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'input':'echo_cancelled','output':'echo_processed'}))
            self.assertEqual(kiosk.selected_audio_environment(home,1000),{'PULSE_SERVER':'unix:/run/user/1000/echo-audio/native'})
            p.write_text(json.dumps({'input':'hw:USB,0','output':'echo_processed'}))
            self.assertEqual(kiosk.selected_audio_environment(home,1000),{})

    def test_failed_write_restores_existing_empty_file(self):
        with TemporaryDirectory() as d:
            home=Path(d);paths=audio.files(home);paths[0].touch()
            original_atomic=audio.atomic
            def failing_write(path,text):
                if path==paths[1]:raise OSError('simulated write failure')
                original_atomic(path,text)
            with patch.object(audio,'atomic',side_effect=failing_write):
                with self.assertRaises(OSError):audio.configure(home,'hw:USB,0','hw:USB,0',1000)
            self.assertEqual(paths[0].read_text(),'')
            self.assertFalse(paths[1].exists());self.assertFalse(paths[2].exists())

    def test_unusable_later_backup_is_rejected_before_writing(self):
        with TemporaryDirectory() as d:
            home=Path(d);paths=audio.files(home)
            backup=paths[2].with_name(paths[2].name+'.before-echo-aec')
            backup.mkdir(parents=True)
            with self.assertRaises(ValueError):audio.configure(home,'hw:USB,0','hw:USB,0',1000)
            self.assertFalse(any(p.exists() for p in paths))


if __name__=='__main__':unittest.main()
