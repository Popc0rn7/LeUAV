import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from leuav import resources as r

class ResourcesTest(unittest.TestCase):
    def test_override_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user = root / 'user.yaml'
            user.write_text('resources:\n  model:\n    path: old\n  sdk:\n    path: sdk\n')
            work = root / 'workspace'
            work.mkdir()
            (work / 'resources.local.yaml').write_text('resources:\n  model:\n    path: weights\n')
            entries = r.load_resources(work, user)
            self.assertEqual(entries['model']['path'], work / 'weights')
            self.assertEqual(entries['sdk']['path'], root / 'sdk')
            self.assertEqual(entries['model']['source'], work / 'resources.local.yaml')

    def test_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.yaml'
            for content in ['[]', 'resources: []', 'resources: {a: {path: 42}}', 'resources: {a: {path: x, typo: y}}', 'resources: [']:
                config.write_text(content)
                with self.assertRaises(r.ResourceError):
                    r.read_resources(config)

    def test_cli_success_missing_and_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'weights').mkdir()
            config = root / 'config.yaml'
            config.write_text('resources:\n  good:\n    path: weights\n  bad:\n    path: absent\n')
            prefix = ['--user-config', str(config), '--workspace', str(root)]
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(r.main(prefix + ['resolve', 'good']), 0)
                self.assertEqual(output.getvalue().strip(), str(root / 'weights'))
                self.assertEqual(r.main(prefix + ['check', 'bad']), 1)
                self.assertEqual(r.main(prefix + ['check', 'unknown']), 1)
                self.assertEqual(r.main(prefix + ['check']), 1)

    def test_no_resources_fails_check(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(r.main(['--workspace', tmp, '--user-config', str(Path(tmp) / 'missing'), 'check']), 1)
            self.assertEqual(r.load_resources(Path(tmp), Path(tmp) / 'missing'), {})

if __name__ == '__main__':
    unittest.main()
