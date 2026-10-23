"""Trace topic/quote context through the real adapter and gateway formatter.

Only network/profile lookup and the final dispatch boundary are mocked. These
are characterization tests, not claims of live payload capture or token counts.
"""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from typing import Any
import unittest
from unittest.mock import AsyncMock, patch

from gateway.config import PlatformConfig
from gateway.run_inbound import GatewayInboundMixin
from gateway.session import build_session_key
from plugins.platforms.feishu.adapter import FeishuAdapter

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'reply_context_plugin', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
assert spec is not None and spec.loader is not None
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class ReplyContextContracts(unittest.IsolatedAsyncioTestCase):
    async def normalize(self, *, adapter_class=None, chat_type='group', thread_id: str | None='omt_topic',
                        parent_id=None, upper_message_id=None, root_id: str | None='om_root',
                        parent_text: str | None='Original topic: all requirements and code'):
        adapter = (adapter_class or plugin.ClarifyFeishuAdapter)(PlatformConfig())
        adapter._fetch_message_text = AsyncMock(return_value=parent_text)
        adapter.get_chat_info = AsyncMock(return_value={
            'name': 'Example', 'type': 'private' if chat_type == 'p2p' else 'group'})
        adapter._resolve_sender_profile = AsyncMock(return_value={
            'user_id': 'ou_sender', 'user_name': 'Sender', 'user_id_alt': None})
        message = NS(message_type='text', content=json.dumps({'text': 'Continue'}),
                     mentions=[], chat_id='oc_chat', thread_id=thread_id,
                     parent_id=parent_id, upper_message_id=upper_message_id, root_id=root_id)
        with patch.object(FeishuAdapter, '_dispatch_inbound_event', new_callable=AsyncMock) as dispatch:
            await adapter._process_inbound_message(
                data=NS(event=NS(message=message)), message=message,
                sender_id=NS(open_id='ou_sender'), chat_type=chat_type, message_id='om_current')
        event = dispatch.call_args.args[0]
        return adapter, event

    async def dispatch(self, adapter, event):
        before = vars(event).copy()
        sentinel = object()
        with patch.object(FeishuAdapter, '_dispatch_inbound_event', new_callable=AsyncMock,
                          return_value=sentinel) as parent:
            self.assertIs(await adapter._dispatch_inbound_event(event), sentinel)
            parent.assert_awaited_once_with(event)
            self.assertIs(parent.call_args.args[0], event)
        self.assertEqual({k: v for k, v in vars(event).items() if k != 'reply_to_text'},
                         {k: v for k, v in before.items() if k != 'reply_to_text'})

    async def test_multiplex_uses_same_policy_without_storage(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory(dir=os.environ['HERMES_TEST_SCRATCH']) as home:
            with patch.dict(os.environ, HERMES_HOME=home):
                for multiplex in (False, True):
                    for parent in ('om_root', 'om_explicit'):
                        adapter, event = await self.normalize(parent_id=parent)
                        event.reply_to_text = 'quoted text'
                        adapter.gateway_runner = NS(config=NS(multiplex_profiles=multiplex))
                        await self.dispatch(adapter, event)
                        self.assertEqual(event.reply_to_text, None if parent == 'om_root' else 'quoted text')
                self.assertEqual(list(Path(home).iterdir()), [])

    async def test_missing_native_fields_and_reply_id_preserve_quotes(self):
        for field in ('raw_message', 'event', 'message', 'root_id', 'reply_to_message_id'):
            adapter, event = await self.normalize()
            event.reply_to_text = 'keep me'
            if field == 'raw_message':
                event.raw_message = None
            elif field == 'event':
                event.raw_message = NS()
            elif field == 'message':
                event.raw_message.event = NS()
            elif field == 'root_id':
                del event.raw_message.event.message.root_id
            else:
                event.reply_to_message_id = None
            await self.dispatch(adapter, event)
            self.assertEqual(event.reply_to_text, 'keep me', field)

    async def test_media_and_commands_follow_same_root_policy(self):
        from gateway.platforms.event import MessageType
        for text, kind, media in (('/new', MessageType.COMMAND, []),
                                  ('Image', MessageType.PHOTO, ['photo.png'])):
            adapter, event = await self.normalize()
            event.text, event.message_type, event.media_urls = text, kind, media
            event.reply_to_text = 'root'
            await self.dispatch(adapter, event)
            self.assertIsNone(event.reply_to_text)
            self.assertEqual(self.format(event), text)

    async def test_real_new_rotates_session_without_reinserting_root(self):
        import os
        import tempfile
        from unittest.mock import Mock
        from gateway.config import GatewayConfig
        from gateway.session import SessionStore
        from gateway.slash_commands_session import GatewaySessionCommandsMixin
        adapter, event = await self.normalize()
        with tempfile.TemporaryDirectory(dir=os.environ['HERMES_TEST_SCRATCH']) as home:
            store = SessionStore(Path(home), GatewayConfig())
            try:
                old = store.get_or_create_session(event.source)
                runner: Any = NS(session_store=store, _session_db=None,
                            async_session_store=NS(reset_session=AsyncMock(side_effect=store.reset_session)),
                            _session_key_for_source=build_session_key)
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
                new = store.lookup_by_session_key(old.session_key)
                self.assertIsNotNone(new)
                assert new is not None
                self.assertNotEqual(old.session_id, new.session_id)
                _, next_event = await self.normalize()
                self.assertEqual(self.format(next_event), 'Continue')
                self.assertIsNone(next_event.reply_to_text)
            finally:
                for db in store._db_handles.values():
                    db.close()

    def format(self, event):
        return GatewayInboundMixin._prepend_inbound_reply_context(event, event.source, event.text)

    async def test_topic_root_text_is_absent_on_every_turn(self):
        for _ in range(2):
            adapter, event = await self.normalize()
            adapter._fetch_message_text.assert_awaited_once_with('om_root')
            self.assertEqual(event.source.thread_id, 'omt_topic')
            self.assertEqual(event.reply_to_message_id, 'om_root')
            self.assertIsNone(event.reply_to_text)
            self.assertEqual(self.format(event), 'Continue')

    async def test_parent_and_upper_reference_precede_root_even_in_topic(self):
        for values, expected in (({'parent_id': 'om_explicit', 'upper_message_id': 'om_upper'}, 'om_explicit'),
                                 ({'upper_message_id': 'om_upper'}, 'om_upper')):
            with self.subTest(values=values):
                adapter, event = await self.normalize(**values)
                adapter._fetch_message_text.assert_awaited_once_with(expected)
                self.assertEqual(event.reply_to_message_id, expected)
                self.assertIn('Original topic: all requirements and code', self.format(event))

    async def test_regular_group_quote_does_not_create_topic(self):
        _, event = await self.normalize(thread_id=None)
        self.assertIsNone(event.source.thread_id)
        self.assertEqual(event.reply_to_message_id, 'om_root')
        self.assertTrue(self.format(event).startswith('[Replying to:'))

    async def test_dm_quote_remains_intact(self):
        _, event = await self.normalize(chat_type='p2p', thread_id=None)
        self.assertEqual(event.source.chat_type, 'dm')
        self.assertTrue(self.format(event).startswith('[Replying to:'))

    async def test_missing_reference_does_not_fetch_or_inject_context(self):
        adapter, event = await self.normalize(root_id=None)
        adapter._fetch_message_text.assert_not_awaited()
        self.assertIsNone(event.reply_to_message_id)
        self.assertEqual(self.format(event), 'Continue')

    async def test_failed_lookup_preserves_anchor_without_injected_text(self):
        _, event = await self.normalize(parent_text=None)
        self.assertEqual(event.reply_to_message_id, 'om_root')
        self.assertEqual(event.source.thread_id, 'omt_topic')
        self.assertEqual(self.format(event), 'Continue')

    async def test_long_quote_is_not_truncated_by_gateway(self):
        text = 'Long requirement\n' * 1000 + 'FINAL REQUIREMENT'
        _, event = await self.normalize(parent_id='om_explicit', parent_text=text)
        self.assertIn(text, self.format(event))

    async def test_topic_sessions_are_isolated_but_quote_text_is_independent(self):
        _, first = await self.normalize(thread_id='omt_first')
        _, second = await self.normalize(thread_id='omt_second')
        self.assertNotEqual(build_session_key(first.source), build_session_key(second.source))
        self.assertEqual(self.format(first), self.format(second))

    async def test_only_root_text_differs_from_official_adapter(self):
        _, enhanced = await self.normalize()
        _, official = await self.normalize(adapter_class=FeishuAdapter)
        self.assertIsNone(enhanced.reply_to_text)
        self.assertTrue(official.reply_to_text)
        self.assertEqual(enhanced.reply_to_message_id, official.reply_to_message_id)
        self.assertEqual(build_session_key(enhanced.source), build_session_key(official.source))
        self.assertEqual(enhanced.text, official.text)
        self.assertEqual(enhanced.raw_message.event.message.root_id, 'om_root')


if __name__ == '__main__':
    unittest.main()
