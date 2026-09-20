import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('pi_screen',Path(__file__).resolve().parents[1]/'deploy/pi/screen.py')
screen=importlib.util.module_from_spec(spec);spec.loader.exec_module(screen)


class ScreenTests(unittest.TestCase):
    def test_validate_and_no_desktop_changes_without_opt_in(self):
        with tempfile.TemporaryDirectory() as home:
            calls=[]
            control=screen.Screen(home,run=lambda *a,**k:calls.append(a))
            control.apply();control.wake();control.sleep()
            self.assertEqual(calls,[])
            for value in ({},dict(screen.DEFAULTS,off_after=60),dict(screen.DEFAULTS,dim_after=True),dict(screen.DEFAULTS,hdmi_sleep='yes')):
                with self.assertRaises(ValueError):screen.validate(value)

    def test_persistence_sleep_wake_and_disabling_restore(self):
        with tempfile.TemporaryDirectory() as home:
            calls=[]
            def run(args,**kwargs):
                calls.append(args)
                return SimpleNamespace(stdout='DPMS is Enabled')
            control=screen.Screen(home,run=run)
            value=dict(screen.DEFAULTS,hdmi_sleep=True)
            control.configure(value)
            self.assertIn(['xset','dpms','0','0','602'],calls)
            self.assertEqual(screen.Screen(home,run=run).config,value)
            control.sleep();self.assertEqual(calls[-1],['xset','dpms','force','off'])
            control.wake();self.assertEqual(calls[-1],['xset','s','reset'])
            control.configure(dict(screen.DEFAULTS))
            self.assertIn(['xset','-dpms'],calls)
            self.assertFalse(control.config['hdmi_sleep'])

    def test_unavailable_does_not_save_false_success(self):
        with tempfile.TemporaryDirectory() as home:
            def unavailable(*args,**kwargs):raise FileNotFoundError()
            control=screen.Screen(home,run=unavailable)
            with self.assertRaises(ValueError):control.configure(dict(screen.DEFAULTS,hdmi_sleep=True))
            self.assertFalse(control.path.exists())


if __name__=='__main__':unittest.main()
