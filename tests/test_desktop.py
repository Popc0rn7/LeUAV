"""Explicit desktop selection must preserve authentication boundaries."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('validate_adrl',Path(__file__).resolve().parents[1]/'tools/validate_adrl.py')
validator=importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class DesktopTests(unittest.TestCase):
    def test_explicit_desktop_uses_given_auth_without_global_permission_changes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            auth=Path(tmp)/'Xauthority';auth.touch()
            env=validator.desktop_environment(':7',str(auth))
            self.assertEqual(env['DISPLAY'],':7')
            self.assertEqual(env['XAUTHORITY'],str(auth))

    def test_missing_auth_is_not_ignored(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(RuntimeError,'Xauthority'):
                validator.desktop_environment(':7','/nonexistent/leuav-Xauthority')
