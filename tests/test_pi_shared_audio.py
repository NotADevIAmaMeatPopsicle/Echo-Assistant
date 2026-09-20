from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/pi'))
from setup_shared_audio import configure
from kiosk import selected_audio_flags


class SharedAudioTests(unittest.TestCase):
    def test_browser_uses_only_explicit_named_audio_devices(self):
        import json
        with TemporaryDirectory() as home:
            self.assertEqual(selected_audio_flags(home),[])
            path=Path(home)/'.config/echo-display/voice.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'input':'plughw:CARD=Sample,DEV=0','output':'echo_shared'}))
            self.assertEqual(selected_audio_flags(home),['--alsa-input-device=plughw:CARD=Sample,DEV=0','--alsa-output-device=echo_shared'])
            path.write_text(json.dumps({'output':'device --other-flag'}));self.assertEqual(selected_audio_flags(home),[])

    def test_preserves_existing_config_and_idempotent_named_output(self):
        with TemporaryDirectory() as home:
            path=Path(home)/'.asoundrc';old='pcm.custom { type null }\n';path.write_text(old)
            configure(home,'USB_Audio');first=path.read_text()
            self.assertTrue(first.startswith(old));self.assertIn('pcm.echo_shared',first)
            self.assertIn('hw:USB_Audio,0',first);self.assertNotIn('pcm.!default',first)
            self.assertEqual(path.with_name('.asoundrc.before-echo').read_text(),old)
            self.assertEqual(configure(home,'USB_Audio'),'already configured')
            configure(home,'AnotherCard');self.assertEqual(path.read_text().count('pcm.echo_shared'),1)
            self.assertEqual(path.with_name('.asoundrc.before-echo').read_text(),old)
            with self.assertRaises(ValueError):configure(home,'USB\nother config')

    def test_does_not_replace_unmanaged_alias(self):
        with TemporaryDirectory() as home:
            path=Path(home)/'.asoundrc';old='pcm.echo_shared { type null }';path.write_text(old)
            with self.assertRaises(ValueError):configure(home,'USB')
            self.assertEqual(path.read_text(),old)


if __name__=='__main__':unittest.main()
