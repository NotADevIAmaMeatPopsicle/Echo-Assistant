"""Model importer portability and preservation, using temporary synthetic files."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from tools import import_remote_models as importer


class ModelImportTests(TestCase):
    def test_manifest_uses_explicit_source_and_only_reviewed_directories(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            for name in importer.NAMES:
                (root/name).mkdir();(root/name/'sample.bin').write_bytes(b'synthetic')
            (root/'unrelated.txt').write_text('not a model')
            manifest=importer.manifest(root)
            self.assertEqual(len(manifest),len(importer.NAMES))
            self.assertTrue(all(v==hashlib.sha256(b'synthetic').hexdigest() for v in manifest.values()))

    def test_remote_inventory_distinguishes_absent_and_partial_directories(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);(root/'partial').mkdir();(root/'partial'/'existing.bin').write_bytes(b'demo')
            digest=hashlib.sha256(b'demo').hexdigest()
            expected={name:digest for name in ('partial/existing.bin','partial/missing.bin','absent/model.bin')}
            def fake_docker(*args,**kwargs):
                self.assertEqual(kwargs['context'],'synthetic-context')
                script=args[-1].replace("Path('/models')",'Path('+repr(str(root))+')')
                return subprocess.run([sys.executable,'-c',script],input=kwargs['input'],capture_output=True,check=True)
            with patch.object(importer,'docker',side_effect=fake_docker):
                result=importer.check(expected,'synthetic-context')
            self.assertEqual(result['partial_directories'],['partial'])
            self.assertEqual(result['missing_directories'],['absent','partial'])

    def test_partial_volume_never_dispatches_copy(self):
        inspected=subprocess.CompletedProcess([],0,stdout=json.dumps([{'Labels':{'org.echo.owner':'round-voice'}}]).encode())
        with patch.object(importer,'manifest',return_value={'demo/file':'a'*64}), \
             patch.object(importer.subprocess,'run',return_value=inspected), \
             patch.object(importer,'check',return_value={'different':0,'extra':0,'missing':1,'partial_directories':['demo']}), \
             patch.object(importer,'docker') as docker:
            with self.assertRaisesRegex(RuntimeError,'partially populated'):
                importer.main(['--source','synthetic-models','--context','synthetic-context'])
            docker.assert_not_called()
