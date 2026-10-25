"""Keep offline verification away from real homes and startup installs."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_plugin', ROOT / 'scripts' / 'verify.py')
assert spec is not None and spec.loader is not None
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class VerificationIsolation(unittest.TestCase):
    def test_child_environment_allowlist_and_no_bootstrap_validator(self):
        session_file = sys.modules['gateway.session'].__file__
        assert session_file is not None
        core = Path(session_file).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=os.environ['HERMES_TEST_SCRATCH']) as scratch:
            argv = ['verify.py', '--hermes-root', str(core), '--scratch', scratch]
            captured = []
            def fake_run(command, **kwargs):
                captured.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, stdout='', stderr='')
            # Deliberately synthetic markers, never real tokens.
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-marker', 'FEISHU_APP_SECRET': 'test-marker',
                                         'HERMES_PROFILE': 'production-marker', 'PYTHONSTARTUP': '/not/run'}), \
                 patch.object(sys, 'argv', argv), patch.object(verify.subprocess, 'run', side_effect=fake_run):
                self.assertEqual(verify.main(), 0)
            self.assertEqual(len(captured), 2)
            for command, kwargs in captured:
                env = kwargs['env']
                for name in ('OPENAI_API_KEY', 'FEISHU_APP_SECRET', 'HERMES_PROFILE', 'PYTHONSTARTUP'):
                    self.assertNotIn(name, env)
                home = env['HOME']
                self.assertEqual(env['HERMES_HOME'], home)
                self.assertEqual(env['USERPROFILE'], home)
                self.assertEqual(kwargs['cwd'], home)
                self.assertEqual(env['HERMES_DISABLE_LAZY_INSTALLS'], '1')
                self.assertTrue(Path(home).is_relative_to(scratch))
                self.assertFalse(Path(home).exists(), 'disposable home must be cleaned')
            validation_command = captured[1][0]
            self.assertNotIn('hermes_cli.main', validation_command)
            self.assertIn('plugins_cmd_catalog import cmd_validate', validation_command[-1])
            self.assertIn('install_deps=False', validation_command[-1])
