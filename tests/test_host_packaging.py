"""Package only reviewed source into a fresh context; no Docker, devices or downloads."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import build_remote_host as build


class ContextTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        for name in (*build.EXTRA,'backend/app.py','web/display/app.js','web/fonts/example.ttf'):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'reviewed source')
        (self.root/'.gitignore').write_text('local/\ncontext/\n.env\n')
        subprocess.run(['git','-C',str(self.root),'add','.'],check=True)

    def native_sources(self,root):
        directory=root/'local/runtime';directory.mkdir(parents=True,exist_ok=True)
        for name in ('librespot-0.8.0.crate','aec_audio_processing-1.0.1.tar.gz'):(directory/name).write_bytes(b'fixture')

    def test_fresh_context_excludes_private_and_stale_files_and_preserves_previous(self):
        old=self.root/'deploy/host/context/backend';old.mkdir(parents=True)
        (old/'retired.py').write_text('previous generated source')
        (self.root/'web/.env').write_text('synthetic private settings')
        with patch.object(build,'fetch',self.native_sources):target=build.stage(self.root)
        self.assertTrue((target/'backend/app.py').is_file())
        self.assertTrue((target/'web/fonts/example.ttf').is_file())
        self.assertFalse((target/'web/.env').exists())
        self.assertFalse((target/'backend/retired.py').exists())
        previous=list((self.root/'local/build-context-backups').glob('*/backend/retired.py'))
        self.assertEqual(len(previous),1);self.assertEqual(previous[0].read_text(),'previous generated source')
        manifest=json.loads((target/'context-manifest.json').read_text())
        self.assertIn('web/display/app.js',manifest);self.assertIn('native/librespot-0.8.0.crate',manifest)
        self.assertTrue((target/'Dockerfile').is_file())

    def test_new_source_and_tracked_private_key_fail_before_fetch_or_context_change(self):
        extra=self.root/'backend/new.py';extra.write_text('new source')
        with patch.object(build,'fetch') as fetch:
            with self.assertRaisesRegex(ValueError,'track new'):build.stage(self.root)
            fetch.assert_not_called()
        extra.write_text('-----BEGIN '+'PRIVATE KEY-----')
        subprocess.run(['git','-C',str(self.root),'add','backend/new.py'],check=True)
        with patch.object(build,'fetch') as fetch:
            with self.assertRaisesRegex(ValueError,'Credential'):build.stage(self.root)
            fetch.assert_not_called()


@unittest.skipUnless(sys.platform=='win32','Windows launcher')
class DisplayLauncherTests(unittest.TestCase):
    def test_display_only_starts_no_round_listener_and_rejects_round_options(self):
        source=Path(__file__).resolve().parents[1]/'tools/run.ps1'
        with TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'tools').mkdir();shutil.copy2(source,root/'tools/run.ps1')
            python=root/'.venv/Scripts/python.exe';python.parent.mkdir(parents=True);python.touch()
            # Simulate an available API. A process launch fails the check instead
            # of touching the user's actual host, board, network or filesystem.
            prefix="function Invoke-RestMethod { @{product='round-voice'; device_transport='disconnected'} }; function Start-Process { throw 'Unexpected process launch' }; "
            quoted=str(root/'tools/run.ps1').replace("'","''")
            for flags,success in [('-DisplayOnly',True),('-DisplayOnly -Usb',False),('',False)]:
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',prefix+f"& '{quoted}' start {flags}"],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode==0,success,result.stderr)
                if success:self.assertIn('did not start a round-board listener',result.stdout)


if __name__=='__main__':unittest.main()
