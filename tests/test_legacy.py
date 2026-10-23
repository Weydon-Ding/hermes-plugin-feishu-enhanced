"""Original local tests ported to the standalone namespace and strict real group key.
Network boundaries only are mocked. Native failure now falls back immediately.
"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from gateway.config import PlatformConfig
from test_plugin import plugin
FeishuAdapter = plugin.ClarifyFeishuAdapter
from tools import clarify_gateway as cg


class FeishuClarifyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = FeishuAdapter(PlatformConfig(enabled=True, extra={'default_group_policy': 'open'}))
        self.adapter._client = MagicMock()
        self.adapter._feishu_send_with_retry = AsyncMock(return_value=SimpleNamespace(
            success=lambda: True, data=SimpleNamespace(message_id='om_test')))
        self.adapter._card_response = lambda card_data=None: card_data
        self.adapter._loop = SimpleNamespace(is_closed=lambda: False)
        self.entry = cg.register('feishu-test', 'agent:main:feishu:group:oc_test:ou_owner',
                                 'Pick', ['A', 'B'])

    def tearDown(self):
        cg.clear_session(self.entry.session_key)

    async def send(self):
        return await self.adapter.send_clarify('oc_test', 'Pick', ['A', 'B'],
                                                self.entry.clarify_id, self.entry.session_key)

    def click(self, choice, user='ou_owner', chat='oc_test', **extra):
        value = {plugin.NAMESPACE: 'v1', 'op': ('toggle' if self.entry.multi_select else 'choose') if choice == 'pick' else choice, 'id': self.entry.clarify_id, **extra}
        event = SimpleNamespace(action=SimpleNamespace(value=value),
            operator=SimpleNamespace(open_id=user),
            context=SimpleNamespace(open_chat_id=chat, open_message_id='om_test'), token=str(id(value)))
        return self.adapter._on_card_action_trigger(SimpleNamespace(event=event))

    async def test_duplicate_multi_select_callback_is_not_toggled_twice(self):
        self.entry.multi_select = True
        await self.send()
        event = SimpleNamespace(token='same-delivery',
            action=SimpleNamespace(value={plugin.NAMESPACE: 'v1', 'op': 'toggle', 'id': self.entry.clarify_id, 'index': 0}),
            operator=SimpleNamespace(open_id='ou_owner'),
            context=SimpleNamespace(open_chat_id='oc_test', open_message_id='om_test'))
        data = SimpleNamespace(event=event)
        self.adapter._on_card_action_trigger(data)
        self.adapter._on_card_action_trigger(data)
        self.click('submit')
        self.assertEqual(json.loads(self.entry.response), ['A'])

    async def test_retire_removes_state_and_updates_card(self):
        await self.send()
        self.adapter._client.im.v1.message.apatch = AsyncMock(return_value=SimpleNamespace(success=lambda: True))
        await self.adapter.retire_clarify_card(self.entry.clarify_id, 'Timed out')
        self.assertNotIn(self.entry.clarify_id, self.adapter._clarify_cards)
        self.adapter._client.im.v1.message.apatch.assert_awaited_once()

    async def test_other_accepts_typed_answer(self):
        await self.send()
        self.click('other')
        self.assertTrue(self.entry.awaiting_text)
        self.assertTrue(cg.resolve_text_response_for_session(self.entry.session_key, 'Custom answer'))
        self.assertEqual(self.entry.response, 'Custom answer')

    async def test_rejects_wrong_user_chat_and_invalid_choice(self):
        await self.send()
        self.click('pick', user='ou_intruder', index=0)
        self.click('pick', chat='oc_wrong', index=0)
        self.click('pick', index=-1)
        self.click('pick', index=True)
        self.click('pick', index=100)
        self.click('submit')
        self.assertIsNone(self.entry.response)

    async def test_expired_entry_does_not_resolve(self):
        await self.send()
        cg.clear_session(self.entry.session_key)
        self.click('pick', index=0)
        self.assertNotIn(self.entry.clarify_id, self.adapter._clarify_cards)

    async def test_native_send_failure_exposes_text_fallback(self):
        from gateway.run_turn_runner_clarify_delivery import text_fallback_coro
        self.adapter._feishu_send_with_retry.side_effect = RuntimeError('offline')
        self.adapter.send = AsyncMock(return_value=SimpleNamespace(success=True))
        with self.assertLogs(plugin.clarify.logger, level='WARNING'):
            self.assertTrue((await self.send()).success)
        result = await text_fallback_coro(self.adapter, chat_id='oc_test', question='Pick',
            choices=['A', 'B'], clarify_id=self.entry.clarify_id, session_key=self.entry.session_key)
        self.assertTrue(result.success)
        self.assertTrue(self.entry.awaiting_text)

    async def test_open_ended_stays_text(self):
        self.adapter.send = AsyncMock(return_value=SimpleNamespace(success=True))
        result = await self.adapter.send_clarify('oc_test', 'Tell me', None,
                                                self.entry.clarify_id, self.entry.session_key)
        self.assertTrue(result.success)
        self.adapter.send.assert_awaited_once()
        self.adapter._feishu_send_with_retry.assert_not_awaited()

    async def test_multi_select_toggles_then_submits(self):
        self.entry.multi_select = True
        await self.send()
        self.click('pick', index=1)
        self.assertIsNone(self.entry.response)
        self.click('pick', index=0)
        self.click('pick', index=1)
        self.click('submit')
        self.assertEqual(json.loads(self.entry.response), ['A'])

    async def test_single_select_native_card_resolves_and_rejects_repeat(self):
        result = await self.send()
        self.assertTrue(result.success)
        kwargs = self.adapter._feishu_send_with_retry.call_args.kwargs
        self.assertEqual(kwargs['msg_type'], 'interactive')
        card = json.loads(kwargs['payload'])
        self.assertIn('Pick', card['elements'][0]['content'])
        self.assertTrue(self.click('pick', index=1))
        self.assertEqual(self.entry.response, 'B')
        self.click('pick', index=0)
        self.assertEqual(self.entry.response, 'B')
