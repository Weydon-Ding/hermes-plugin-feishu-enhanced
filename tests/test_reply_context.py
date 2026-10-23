"""Trace topic/quote context through the real adapter and gateway formatter.

Only network/profile lookup and the final dispatch boundary are mocked. These
are characterization tests, not claims of live payload capture or token counts.
"""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

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
        adapter._dispatch_inbound_event = AsyncMock()
        message = NS(message_type='text', content=json.dumps({'text': 'Continue'}),
                     mentions=[], chat_id='oc_chat', thread_id=thread_id,
                     parent_id=parent_id, upper_message_id=upper_message_id, root_id=root_id)
        await adapter._process_inbound_message(
            data=NS(event=NS(message=message)), message=message,
            sender_id=NS(open_id='ou_sender'), chat_type=chat_type, message_id='om_current')
        event = adapter._dispatch_inbound_event.call_args.args[0]
        return adapter, event

    def format(self, event):
        return GatewayInboundMixin._prepend_inbound_reply_context(event, event.source, event.text)

    async def test_topic_root_is_fetched_and_quoted_on_each_message(self):
        adapter, event = await self.normalize()
        adapter._fetch_message_text.assert_awaited_once_with('om_root')
        self.assertEqual(event.source.thread_id, 'omt_topic')
        self.assertEqual(event.reply_to_message_id, 'om_root')
        self.assertEqual(self.format(event),
                         '[Replying to: "Original topic: all requirements and code"]\n\nContinue')
        _, next_event = await self.normalize()
        self.assertEqual(self.format(event), self.format(next_event))

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
        _, event = await self.normalize(parent_text=text)
        self.assertIn(text, self.format(event))

    async def test_topic_sessions_are_isolated_but_quote_text_is_independent(self):
        _, first = await self.normalize(thread_id='omt_first')
        _, second = await self.normalize(thread_id='omt_second')
        self.assertNotEqual(build_session_key(first.source), build_session_key(second.source))
        self.assertEqual(self.format(first), self.format(second))

    async def test_plugin_and_official_context_paths_are_identical(self):
        _, enhanced = await self.normalize()
        _, official = await self.normalize(adapter_class=FeishuAdapter)
        self.assertEqual(enhanced.reply_to_text, official.reply_to_text)
        self.assertEqual(enhanced.reply_to_message_id, official.reply_to_message_id)
        self.assertEqual(build_session_key(enhanced.source), build_session_key(official.source))
        self.assertEqual(self.format(enhanced), self.format(official))


if __name__ == '__main__':
    unittest.main()
