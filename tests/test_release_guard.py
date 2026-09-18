from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from tools import release_guard


class ReleaseGuardTests(unittest.TestCase):
    def test_worktree_checks_untracked_private_artifacts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root/'README.md').write_text('Public source')
            subprocess.run(['git', '-C', str(root), 'add', 'README.md'], check=True)
            (root/'.env').write_text('PRIVATE_SETTINGS=example')
            with patch.object(release_guard, 'ROOT', root):
                self.assertEqual(release_guard.inspect()[1], [])
                count, findings = release_guard.inspect(staged=False)
            self.assertEqual(count, 2)
            self.assertEqual(findings, [('.env', 0, 'private/generated artifact')])

    def test_index_is_checked_even_when_worktree_was_cleaned(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root/'draft.txt').write_text('-----BEGIN ' + 'PRIVATE KEY-----')
            subprocess.run(['git', '-C', str(root), 'add', 'draft.txt'], check=True)
            (root/'draft.txt').write_text('Clean working copy')
            with patch.object(release_guard, 'ROOT', root):
                self.assertEqual(release_guard.inspect(staged=False)[1], [])
                self.assertEqual(release_guard.inspect()[1], [('draft.txt', 1, 'private key')])
