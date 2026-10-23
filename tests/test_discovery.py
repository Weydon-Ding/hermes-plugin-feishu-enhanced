"""Exercise real discovery, scoped factory selection and unload (no sockets)."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class Discovery(unittest.TestCase):
    def test_real_discovery_selection_scope_and_restore(self):
        with tempfile.TemporaryDirectory(prefix='feishu-plugin-', dir=os.environ.get('HERMES_TEST_SCRATCH')) as directory:
            home = Path(directory)
            shutil.copytree(ROOT, home / 'plugins' / 'feishu-enhanced', ignore=shutil.ignore_patterns('__pycache__', '.git'))
            (home / 'config.yaml').write_text('plugins:\n  enabled: [feishu-enhanced]\n', encoding='utf-8')
            script = '''
import socket
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network forbidden'))
from hermes_cli.plugins import PluginManager
from gateway.platform_registry import platform_registry
from gateway.platforms.base import BasePlatformAdapter
from plugins.platforms.feishu.adapter import FeishuAdapter
from gateway.config import PlatformConfig
assert FeishuAdapter.send_clarify is BasePlatformAdapter.send_clarify, 'test requires clean core'
manager = PluginManager()
manager.discover_and_load()
entry = platform_registry.get('feishu')
assert entry.adapter_factory is not FeishuAdapter, ('wrong adapter selected', entry)
a = entry.adapter_factory(PlatformConfig())
assert isinstance(a, FeishuAdapter)
assert type(a).send is FeishuAdapter.send
assert a._topic_context_hook_ready
assert manager._hooks.get('pre_llm_call'), 'actual-session hook not registered'
assert type(a).connect is FeishuAdapter.connect
assert type(a).send_exec_approval is FeishuAdapter.send_exec_approval
assert entry.allowed_users_env == 'FEISHU_ALLOWED_USERS'
assert entry.allow_all_env == 'FEISHU_ALLOW_ALL_USERS'
# Ledger teardown uses captured scope even when ambient profile changes.
import os
old_home = os.environ['HERMES_HOME']
os.environ['HERMES_HOME'] = old_home + '-other'
assert manager.unload('feishu-enhanced')
assert not a._topic_context_hook_ready, 'old instance still creates references'
assert not manager._hooks.get('pre_llm_call'), 'hook leaked on unload'
os.environ['HERMES_HOME'] = old_home
restored = platform_registry.get('feishu').adapter_factory
assert restored.__name__ == 'FeishuAdapter', ('restored wrong', restored, restored.__mro__)
assert restored.send_clarify is BasePlatformAdapter.send_clarify
assert restored.__module__.endswith('.adapter')
manager.unload()
print('real discovery: enhanced selection, metadata, inherited behavior, unload restoration PASS')
'''
            env = {k: v for k, v in os.environ.items() if not k.startswith(('FEISHU_', 'LARK_'))}
            env.update(HERMES_HOME=str(home), HERMES_SAFE_MODE='0')
            result = subprocess.run([sys.executable, '-c', script], env=env, cwd=str(home), text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('restoration PASS', result.stdout)

if __name__ == '__main__':
    unittest.main()
