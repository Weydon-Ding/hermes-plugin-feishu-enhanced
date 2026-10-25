"""Offline verification using the caller's Hermes runtime; never installs packages."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-root', required=True, type=Path, help='Clean Hermes checkout (not the plugin)')
    parser.add_argument('--scratch', required=True, type=Path, help='Parent for disposable test homes')
    parser.add_argument('--report-dir', type=Path, help='Optional persistent test and validator output')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    core = args.hermes_root.resolve()
    if not (core / 'hermes_cli' / 'plugins.py').is_file():
        parser.error('--hermes-root must contain a Hermes checkout')
    args.scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='clarify-verify-', dir=args.scratch) as tmp:
        # Allowlist, not a credential-prefix denylist. Never inherit production
        # provider tokens, profile selection, dotenv locations or Python hooks.
        env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'WINDIR') if k in os.environ}
        env.update(HOME=tmp, USERPROFILE=tmp, HERMES_HOME=tmp,
                   XDG_CONFIG_HOME=tmp, XDG_CACHE_HOME=tmp, XDG_DATA_HOME=tmp,
                   HERMES_TEST_SCRATCH=tmp, HERMES_SAFE_MODE='0', HERMES_DISABLE_LAZY_INSTALLS='1',
                   PYTHONPATH=str(core), TMPDIR=tmp, TEMP=tmp, TMP=tmp,
                   PYTHONUTF8='1', PYTHONNOUSERSITE='1', TZ='UTC')
        # Warm SDK imports before IsolatedAsyncioTestCase starts its debug event loops.
        test_script = "import unittest,lark_oapi; suite=unittest.defaultTestLoader.discover(%r); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful())" % str(root / 'tests')
        tests = subprocess.run([sys.executable, '-c', test_script], env=env, cwd=tmp,
                               capture_output=True, text=True, encoding='utf-8', timeout=180)
        print(tests.stdout + tests.stderr)
        # Call the official CLI validation handler directly: main() bootstraps
        # a fresh data root and may install dependencies before dispatching.
        validation_script = ("from hermes_cli.plugins_cmd_catalog import cmd_validate; "
                             "cmd_validate(%r, as_json=True, install_deps=False)" % str(root))
        validation = subprocess.run([sys.executable, '-c', validation_script],
                                    env=env, cwd=tmp, capture_output=True, text=True, encoding='utf-8', timeout=90)
        print(validation.stdout + validation.stderr)
        if args.report_dir:
            args.report_dir.mkdir(parents=True, exist_ok=True)
            (args.report_dir / 'tests.txt').write_text(tests.stdout + tests.stderr, encoding='utf-8')
            (args.report_dir / 'validation.json').write_text(validation.stdout, encoding='utf-8')
        return tests.returncode or validation.returncode


if __name__ == '__main__':
    raise SystemExit(main())
