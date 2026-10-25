"""Identity regressions using real session keys and real SDK callback models."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from gateway.config import Platform, PlatformConfig
from gateway.session import SessionSource, build_session_key
from gateway.platforms.base import SendResult
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger
from tools import clarify_gateway as cg

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('owner_plugin', ROOT / '__init__.py',
                                           submodule_search_locations=[str(ROOT)])
assert spec is not None and spec.loader is not None
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)


class OwnerIdentity(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.adapter = plugin.ClarifyFeishuAdapter(PlatformConfig(extra={'default_group_policy': 'open'}))
        self.adapter._resolve_sender_name_from_api = AsyncMock(return_value=None)
        self.adapter._send_interactive_card = AsyncMock(return_value=SendResult(success=True, message_id='om_card'))
        self.keys = set()

    def tearDown(self):
        for key in self.keys:
            cg.clear_session(key)

    async def card(self, ids, *, thread=None, shared=False, observe=True, adapter=None):
        a = adapter or self.adapter
        if observe:
            profile = await a._resolve_sender_profile(NS(**ids))
        else:
            profile = {'user_id': ids.get('user_id') or ids.get('open_id'),
                       'user_id_alt': ids.get('union_id')}
        source = SessionSource(platform=Platform.FEISHU, chat_type='group', chat_id='oc_chat',
                               user_id=profile['user_id'], user_id_alt=profile['user_id_alt'], thread_id=thread)
        key = build_session_key(source, group_sessions_per_user=not shared,
                                thread_sessions_per_user=not shared)
        self.keys.add(key)
        entry = cg.register('owner-cid', key, 'Pick?', ['A', 'B'])
        await a.send_clarify('oc_chat', 'Pick?', ['A', 'B'], 'owner-cid', key,
                             {'thread_id': thread} if thread else None)
        return entry

    def click(self, ids, *, chat='oc_chat', message='om_card', adapter=None):
        data = P2CardActionTrigger({'event': {'operator': ids,
            'context': {'open_chat_id': chat, 'open_message_id': message},
            'action': {'value': {plugin.NAMESPACE: 'v1', 'id': 'owner-cid', 'op': 'choose', 'index': 0}}}})
        return (adapter or self.adapter)._on_card_action_trigger(data)

    async def test_direct_callback_id_variants_with_real_keys(self):
        for ids in ({'open_id': 'ou_owner'},
                    {'open_id': 'ou_owner', 'user_id': 'employee_owner'},
                    {'open_id': 'ou_owner', 'user_id': 'employee_owner', 'union_id': 'on_owner'}):
            for thread in (None, 'omt_topic'):
                with self.subTest(ids=ids, thread=thread):
                    entry = await self.card(ids, thread=thread, observe=False)
                    self.click({'open_id': 'ou_other', 'user_id': 'employee_other', 'union_id': 'on_other'})
                    self.assertIsNone(entry.response)
                    self.click(ids)
                    self.assertEqual(entry.response, 'A')

    async def test_missing_union_and_user_callback_use_observed_inbound_alias(self):
        for ids in ({'open_id': 'ou_owner', 'user_id': 'employee_owner'},
                    {'open_id': 'ou_owner', 'user_id': 'employee_owner', 'union_id': 'on_owner'}):
            for thread in (None, 'omt_topic'):
                with self.subTest(ids=ids, thread=thread):
                    entry = await self.card(ids, thread=thread)
                    self.click({'open_id': 'ou_other'})
                    self.assertIsNone(entry.response)
                    self.click({'open_id': 'ou_owner'})
                    self.assertEqual(entry.response, 'A')

    async def test_missing_alias_proof_fails_closed(self):
        entry = await self.card({'open_id': 'ou_owner', 'union_id': 'on_owner'}, observe=False)
        self.click({'open_id': 'ou_owner'})
        self.assertIsNone(entry.response)

    async def test_empty_open_id_remains_denied_by_official_gate_contract(self):
        entry = await self.card({'open_id': 'ou_owner', 'union_id': 'on_owner'})
        for ids in ({}, {'union_id': 'on_owner'}, {'open_id': None}, {'open_id': 123}):
            self.click(ids)
            self.assertIsNone(entry.response)

    async def test_conflicting_typed_fields_do_not_authorize(self):
        entry = await self.card({'open_id': 'ou_owner', 'user_id': 'employee_owner', 'union_id': 'on_owner'})
        for ids in ({'open_id': 'ou_other', 'union_id': 'on_owner'},
                    {'open_id': 'ou_owner', 'user_id': 'employee_other'},
                    {'open_id': 'ou_other', 'user_id': 'on_owner'}):
            self.click(ids)
            self.assertIsNone(entry.response)

    async def test_shared_group_and_topic_still_accept_other_admitted_members(self):
        for thread in (None, 'omt_topic', 'ou_thread'):
            entry = await self.card({'open_id': 'ou_owner', 'union_id': 'on_owner'}, thread=thread, shared=True)
            self.click({'open_id': 'ou_other'})
            self.assertEqual(entry.response, 'A')

    async def test_alias_does_not_bypass_context_thread_or_group_gate(self):
        ids = {'open_id': 'ou_owner', 'union_id': 'on_owner'}
        entry = await self.card(ids, thread='omt_topic')
        for kwargs in ({'chat': 'oc_wrong'}, {'message': 'om_wrong'}):
            self.click({'open_id': 'ou_owner'}, **kwargs)
            self.assertIsNone(entry.response)
        state = self.adapter._clarify_cards['owner-cid']
        state['thread'] = 'omt_other'
        self.click({'open_id': 'ou_owner'})
        self.assertIsNone(entry.response)
        state['thread'] = 'omt_topic'
        self.adapter._default_group_policy = 'disabled'
        self.click({'open_id': 'ou_owner'})
        self.assertIsNone(entry.response)

    async def test_adapter_local_cache_and_disconnect_cleanup(self):
        ids = {'open_id': 'ou_owner', 'union_id': 'on_owner'}
        await self.card(ids)
        other = plugin.ClarifyFeishuAdapter(PlatformConfig(extra={'default_group_policy': 'open'}))
        other._send_interactive_card = self.adapter._send_interactive_card
        entry = await self.card(ids, observe=False, adapter=other)
        self.click({'open_id': 'ou_owner'}, adapter=other)
        self.assertIsNone(entry.response)
        from plugins.platforms.feishu.adapter import FeishuAdapter
        with patch.object(FeishuAdapter, 'disconnect', new_callable=AsyncMock):
            await self.adapter.disconnect()
        self.assertFalse(self.adapter._clarify_identities)
        self.assertFalse(self.adapter._clarify_cards)

    async def test_cache_ttl_bound_and_card_snapshot(self):
        ids = {'open_id': 'ou_owner', 'union_id': 'on_owner'}
        with patch.object(sys.modules['owner_plugin.clarify'].time, 'monotonic', return_value=10):
            entry = await self.card(ids)
        with patch.object(sys.modules['owner_plugin.clarify'].time, 'monotonic', return_value=10000):
            # A delivered card keeps its original proof, until normal retirement.
            self.click({'open_id': 'ou_owner'})
            self.assertEqual(entry.response, 'A')
            entry = await self.card(ids, observe=False)
            self.click({'open_id': 'ou_owner'})
            self.assertIsNone(entry.response)
            self.assertFalse(self.adapter._clarify_identities)
        for i in range(1030):
            await self.adapter._resolve_sender_profile(NS(open_id=f'ou_{i}', union_id=f'on_{i}'))
        self.assertLessEqual(len(self.adapter._clarify_identities), 1024)

    async def test_real_inbound_normalization_connects_to_open_only_callback(self):
        from plugins.platforms.feishu.adapter import FeishuAdapter
        a = self.adapter
        a.get_chat_info = AsyncMock(return_value={'name': 'Example', 'type': 'group'})
        ids = NS(open_id='ou_owner', user_id='employee_owner', union_id='on_owner')
        for thread in (None, 'omt_topic'):
            message = NS(message_type='text', content='{"text":"Question"}', mentions=[],
                         chat_id='oc_chat', thread_id=thread, root_id=None,
                         parent_id=None, upper_message_id=None)
            with patch.object(FeishuAdapter, '_dispatch_inbound_event', new_callable=AsyncMock) as dispatch:
                await a._process_inbound_message(data=NS(event=NS(message=message)), message=message,
                    sender_id=ids, chat_type='group', message_id='om_inbound')
            source = dispatch.call_args.args[0].source
            key = build_session_key(source, thread_sessions_per_user=True)
            self.assertTrue(key.endswith(':on_owner'))
            self.keys.add(key)
            entry = cg.register('owner-cid', key, 'Pick?', ['A', 'B'])
            await a.send_clarify('oc_chat', 'Pick?', ['A', 'B'], 'owner-cid', key,
                                 {'thread_id': source.thread_id} if source.thread_id else None)
            self.click({'open_id': 'ou_other'})
            self.assertIsNone(entry.response)
            self.click({'open_id': 'ou_owner'})
            self.assertEqual(entry.response, 'A')
        a._resolve_sender_name_from_api.assert_awaited()

    async def test_pending_card_proof_is_not_changed_by_later_resolution(self):
        entry = await self.card({'open_id': 'ou_owner', 'union_id': 'on_owner'})
        await self.adapter._resolve_sender_profile(NS(open_id='ou_changed', union_id='on_owner'))
        self.click({'open_id': 'ou_changed'})
        self.assertIsNone(entry.response)
        self.click({'open_id': 'ou_owner'})
        self.assertEqual(entry.response, 'A')

    async def test_bot_identities_are_not_cached(self):
        await self.adapter._resolve_sender_profile(NS(open_id='ou_bot', union_id='on_bot'), is_bot=True)
        self.assertFalse(getattr(self.adapter, '_clarify_identities', {}))

    async def test_disconnect_during_resolution_does_not_repopulate_cache(self):
        from plugins.platforms.feishu.adapter import FeishuAdapter
        async def disconnect_before_name(*args, **kwargs):
            with patch.object(FeishuAdapter, 'disconnect', new_callable=AsyncMock):
                await self.adapter.disconnect()
            return None
        self.adapter._resolve_sender_name_from_api.side_effect = disconnect_before_name
        await self.adapter._resolve_sender_profile(NS(open_id='ou_owner', union_id='on_owner'))
        self.assertFalse(getattr(self.adapter, '_clarify_identities', {}))

    async def test_changed_identity_resolver_signature_disables_plugin(self):
        from plugins.platforms.feishu.adapter import FeishuAdapter
        async def incompatible(self, sender):
            return {}
        class Capture:
            def register_platform(self, **kwargs):
                raise AssertionError('incompatible adapter must not register')
        with patch.object(FeishuAdapter, '_resolve_sender_profile', incompatible), self.assertLogs(plugin.logger, level='WARNING'):
            plugin.register(Capture())

    async def test_retirement_removes_card_identity_snapshot(self):
        await self.card({'open_id': 'ou_owner', 'union_id': 'on_owner'})
        await self.adapter.retire_clarify_card('owner-cid', 'Expired')
        self.assertNotIn('owner-cid', self.adapter._clarify_cards)
