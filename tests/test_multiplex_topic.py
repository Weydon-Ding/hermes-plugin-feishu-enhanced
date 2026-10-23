"""Real routing identity, scoped plugin managers and actual SessionStore IDs."""
import asyncio
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from typing import Any
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch
import test_reply_context as trace
from gateway.config import GatewayConfig
from gateway.session import SessionStore
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from hermes_cli.plugins import get_plugin_manager


@contextmanager
def home_scope(home):
    token = set_hermes_home_override(home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)


class MultiplexTopic(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['HERMES_TEST_SCRATCH'])
        self.addCleanup(self.tmp.cleanup)
        self.homes = {name: Path(self.tmp.name) / name for name in ('ingress', 'alpha', 'beta')}
        for home in self.homes.values():
            home.mkdir()
        self.stores = {}
        for name, home in self.homes.items():
            with home_scope(home):
                store = SessionStore(home, GatewayConfig())
            self.stores[name] = store
        self.addCleanup(self.close_stores)

    def close_stores(self):
        for store in self.stores.values():
            for db in store._db_handles.values():
                db.close()

    def register_hook(self, name):
        # Exercise the production registration path, with real profile-local managers.
        with home_scope(self.homes[name]):
            manager = get_plugin_manager()
            from hermes_cli.plugins import PluginContext, parse_manifest_file
            manifest = parse_manifest_file(trace.ROOT / 'plugin.yaml', trace.ROOT, 'user', '')
            assert manifest is not None
            ctx = PluginContext(manifest, manager)
            self.addCleanup(manager.unload)
            trace.plugin.register(ctx)
        return manager

    async def routed(self, target='alpha', media=False, **options):
        adapter, event = await trace.ReplyContextContracts().normalize(**options)
        adapter._topic_context_hook_ready = True
        # Suppress launcher/PM activation only; routing/identity remain real.
        with patch('hermes_cli.venv_sync.prepare_launch', return_value=None), \
             patch('pm.environments.activate_dependencies'):
            from gateway.run import GatewayRunner
        from gateway.profile_routing import parse_profile_routes
        runner: Any = NS(config=NS(multiplex_profiles=True, profile_routes=parse_profile_routes([
                        {'name': 'topic-owner', 'platform': 'feishu', 'chat_id': 'oc_chat', 'profile': target}])),
                    _primary_profile_name='ingress',
                    _owning_profile=lambda adapter, platform: (True, 'ingress'),
                    _transport_owner=lambda source: (adapter, None))
        runner._profile_name_for_source = lambda source: GatewayRunner._profile_name_for_source(runner, source)
        runner._resolve_profile_home_for_source = lambda source: GatewayRunner._resolve_profile_home_for_source(runner, source)
        adapter.gateway_runner = runner
        # Use real route matcher, served-target gate, home resolver and identity pinning.
        if media:
            from gateway.platforms.event import MessageType
            event.message_type = MessageType.PHOTO
            event.media_urls = ['photo.png']
        with patch('gateway.run._multiplex_profile_homes', return_value=list(self.homes.items())), \
             patch('hermes_cli.profiles.get_profile_dir', side_effect=lambda name: self.homes[name]), \
             patch('hermes_cli.profiles.profile_exists', return_value=True), \
             home_scope(self.homes['ingress']), \
             patch.object(trace.FeishuAdapter, '_dispatch_inbound_event', new_callable=AsyncMock):
            await type(adapter)._dispatch_inbound_event(adapter, event)
        return event

    def collect(self, name, event):
        with home_scope(self.homes[name]):
            session = self.stores[name].get_or_create_session(event.source)
            result = get_plugin_manager().invoke_hook('pre_llm_call', session_id=session.session_id,
                platform='feishu', sender_id='ou_sender', user_message=trace.ReplyContextContracts().format(event))
            return result

    async def test_routed_profile_owns_reference_and_real_session_ledger(self):
        self.register_hook('alpha')
        event = await self.routed()
        self.assertIn('Feishu topic root reference:', event.reply_to_text)
        self.assertFalse((self.homes['ingress'] / 'cache' / 'feishu-enhanced-topic').exists())
        with patch('hermes_cli.profiles.get_profile_dir', side_effect=lambda name: self.homes[name]), \
             patch('hermes_cli.profiles.profile_exists', return_value=True):
            self.assertIn('Original topic:', self.collect('alpha', event)[0]['context'])
            self.assertEqual(self.collect('alpha', event), [])

    async def test_copied_sidecar_is_rejected_even_with_same_sender_and_session(self):
        import shutil
        self.register_hook('alpha')
        self.register_hook('beta')
        event = await self.routed()
        source = self.homes['alpha'] / 'cache' / 'feishu-enhanced-topic'
        target = self.homes['beta'] / 'cache' / 'feishu-enhanced-topic'
        shutil.copytree(source, target)
        # Even an accidentally copied file must not become beta's root text.
        with home_scope(self.homes['alpha']):
            original = get_plugin_manager().invoke_hook('pre_llm_call', session_id='same-session',
                platform='feishu', sender_id='ou_sender', user_message=event.reply_to_text)
        self.assertIn('Original topic:', str(original))
        with home_scope(self.homes['beta']):
            result = get_plugin_manager().invoke_hook('pre_llm_call', session_id='same-session',
                platform='feishu', sender_id='ou_sender', user_message=event.reply_to_text)
        self.assertNotIn('Original topic:', str(result))

    async def test_two_profiles_same_chat_thread_are_independent_and_concurrent(self):
        self.register_hook('alpha')
        self.register_hook('beta')
        async def run(name):
            event = await self.routed(name)
            with home_scope(self.homes[name]):
                await asyncio.sleep(0)
                first = self.collect(name, event)
                await asyncio.sleep(0)
                repeat = self.collect(name, event)
            return event, first, repeat
        results = await asyncio.gather(run('alpha'), run('beta'))
        for event, first, repeat in results:
            self.assertIn('Original topic:', first[0]['context'])
            self.assertEqual(repeat, [])
        self.assertNotEqual(results[0][0].reply_to_text, results[1][0].reply_to_text)

    async def test_missing_target_hook_keeps_full_quote_without_writing(self):
        self.register_hook('ingress')
        event = await self.routed()
        self.assertIn('Original topic:', event.reply_to_text)
        self.assertFalse((self.homes['alpha'] / 'cache' / 'feishu-enhanced-topic').exists())

    async def test_real_new_in_routed_profile_reallows_root_only_there(self):
        from unittest.mock import Mock
        from gateway.session import build_session_key
        from gateway.slash_commands_session import GatewaySessionCommandsMixin
        self.register_hook('alpha')
        self.register_hook('beta')
        event = await self.routed()
        other = await self.routed('beta')
        self.assertTrue(self.collect('alpha', event))
        self.assertTrue(self.collect('beta', other))
        with home_scope(self.homes['alpha']):
            store = self.stores['alpha']
            old = store.get_or_create_session(event.source)
            runner: Any = NS(session_store=store, _session_db=None,
                async_session_store=NS(reset_session=AsyncMock(side_effect=store.reset_session)),
                _session_key_for_source=lambda source: build_session_key(source))
            for name in ('_hm_stop_owner_turn', '_cleanup_old_agent_for_reset', '_fire_session_reset_hooks'):
                setattr(runner, name, AsyncMock())
            for name in ('_invalidate_session_run_generation', '_release_running_agent_state',
                         '_evict_cached_agent', '_clear_conversation_scope'):
                setattr(runner, name, Mock())
            runner._reset_notice_session_info = Mock(return_value='')
            runner._telegram_topic_new_header = Mock(return_value='')
            runner._is_telegram_topic_lane = Mock(return_value=False)
            event.text = '/new'
            with patch('gateway.session_automation.move_route_wakes', new_callable=AsyncMock), \
                 patch('gateway.slash_commands_session._reset_process_scoped_tool_state'):
                await GatewaySessionCommandsMixin._handle_reset_command(runner, event)
            self.assertNotEqual(old.session_id, store.lookup_by_session_key(old.session_key).session_id)
        self.assertTrue(self.collect('alpha', event))
        self.assertEqual(self.collect('beta', other), [])

    async def test_real_context_collector_uses_owner_manager(self):
        from agent.turn_context import _collect_pre_llm_call_context
        self.register_hook('alpha')
        event = await self.routed()
        with home_scope(self.homes['alpha']):
            session = self.stores['alpha'].get_or_create_session(event.source)
            agent = NS(session_id=session.session_id, model='test', platform='feishu', _user_id='ou_sender')
            text = trace.ReplyContextContracts().format(event)
            # No lifecycle mock: scope selects the actual registered manager.
            context = _collect_pre_llm_call_context(agent, effective_task_id='task', turn_id='turn',
                original_user_message=text, messages=[{'role': 'user', 'content': text}], conversation_history=[])
            self.assertIn('Original topic:', context)

    async def test_multiplex_fallbacks_keep_original_quote(self):
        self.register_hook('alpha')
        media_event = await self.routed(media=True)
        self.assertIn('Original topic:', media_event.reply_to_text)
        for options in ({'parent_id': 'om_explicit'}, {'upper_message_id': 'om_upper'},
                        {'chat_type': 'p2p'}, {'thread_id': None}, {'parent_text': 'LONG ' * 10000}):
            event = await self.routed(**options)
            self.assertNotIn('Feishu topic root reference:', event.reply_to_text)
        with patch.object(trace.plugin.topic_context, 'MAX_REFERENCE_FILES', 0):
            event = await self.routed(parent_text='unique full capacity quote')
            self.assertEqual(event.reply_to_text, 'unique full capacity quote')

    async def test_resolver_fallback_cannot_write_routed_text_into_ingress(self):
        self.register_hook('ingress')
        self.register_hook('alpha')
        adapter, event = await trace.ReplyContextContracts().normalize()
        from gateway.session_identity import RoutingIdentity
        event.source._identity = RoutingIdentity('ingress', 'alpha', self.homes['ingress'], self.homes['ingress'])
        adapter.gateway_runner = NS(config=NS(multiplex_profiles=True))
        adapter._topic_context_hook_ready = True
        with home_scope(self.homes['ingress']), \
             patch('hermes_cli.profiles.get_profile_dir', side_effect=lambda name: self.homes[name]), \
             patch.object(trace.FeishuAdapter, '_dispatch_inbound_event', new_callable=AsyncMock):
            await type(adapter)._dispatch_inbound_event(adapter, event)
        self.assertIn('Original topic:', event.reply_to_text)
        self.assertFalse((self.homes['ingress'] / 'cache' / 'feishu-enhanced-topic').exists())

    async def test_foreign_hook_callback_refuses_ambient_profile(self):
        manager = self.register_hook('alpha')
        event = await self.routed()
        callback = manager._hooks['pre_llm_call'][0]
        with home_scope(self.homes['beta']):
            self.assertIsNone(callback(session_id='same', platform='feishu', sender_id='ou_sender',
                                      user_message=event.reply_to_text))
