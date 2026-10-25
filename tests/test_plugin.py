"""Offline contracts against a real, clean Hermes checkout and Lark SDK."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('clarify_plugin', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
if spec.loader and (ROOT / '__init__.py').exists():
    spec.loader.exec_module(plugin)
from tools import clarify_gateway as cg
from gateway.platforms.base import SendResult
from gateway.config import PlatformConfig

class Contracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = 'agent:main:feishu:group:oc_chat:ou_owner'
        self.entry = cg.register('cid', self.key, 'Pick?', ['A', 'B'])

    def tearDown(self):
        cg.clear_session(self.key)

    async def adapter(self):
        self.assertTrue(hasattr(plugin, 'ClarifyFeishuAdapter'), 'standalone clarify adapter is missing')
        a = plugin.ClarifyFeishuAdapter(PlatformConfig(extra={'default_group_policy': 'open'}))
        a._send_interactive_card = AsyncMock(return_value=SendResult(success=True, message_id='om_card'))
        await a.send_clarify('oc_chat', 'Pick?', ['A', 'B'], 'cid', self.key)
        return a

    def click(self, a, op='choose', index=0, user='ou_owner', chat='oc_chat', message='om_card', token='t1'):
        return a._on_card_action_trigger(NS(event=NS(operator=NS(open_id=user, user_id=''),
            context=NS(open_chat_id=chat, open_message_id=message), token=token,
            action=NS(value={plugin.NAMESPACE: 'v1', 'id': 'cid', 'op': op, 'index': index}))))

    async def test_click_resolves_real_registry_once(self):
        a = await self.adapter()
        self.click(a)
        self.assertEqual(self.entry.response, 'A')
        self.click(a, index=1)
        self.assertEqual(self.entry.response, 'A')

    async def test_multi_toggle_deduplicates_delivery_and_submits(self):
        self.entry.multi_select = True
        a = await self.adapter()
        self.click(a, op='toggle', index=0)
        self.click(a, op='toggle', index=0)
        self.assertIsNone(self.entry.response)
        self.click(a, op='toggle', index=1, token='t2')
        self.click(a, op='toggle', index=1, token='t3')
        self.click(a, op='submit', token='t4')
        self.assertEqual(json.loads(self.entry.response), ['A'])

    async def test_other_arms_real_text_capture(self):
        a = await self.adapter()
        self.click(a, op='other')
        self.assertTrue(self.entry.awaiting_text)
        self.assertTrue(cg.resolve_text_response_for_session(self.key, 'custom answer'))
        self.assertEqual(self.entry.response, 'custom answer')

    async def test_failed_card_falls_back_to_inherited_numbered_text(self):
        a = await self.adapter()
        a._send_interactive_card.return_value = SendResult(success=False, error='offline')
        a.send = AsyncMock(return_value=SendResult(success=True, message_id='text'))
        result = await a.send_clarify('oc_chat', 'Pick?', ['A', 'B'], 'cid', self.key)
        self.assertTrue(result.success)
        self.assertTrue(a.send.called)
        self.assertTrue(self.entry.awaiting_text)
        self.assertNotIn('cid', a._clarify_cards)

    async def test_retire_patches_interactive_message_and_forgets_state(self):
        a = await self.adapter()
        a._client = NS(im=NS(v1=NS(message=NS(apatch=AsyncMock(return_value=NS(success=lambda: True))))))
        self.assertTrue(hasattr(a, 'retire_clarify_card'), 'retirement hook missing')
        await a.retire_clarify_card('cid', 'Expired')
        request = a._client.im.v1.message.apatch.call_args.args[0]
        self.assertEqual(request.message_id, 'om_card')
        self.assertIn('Expired', request.request_body.content)
        self.assertNotIn('cid', a._clarify_cards)
        self.click(a)
        self.assertIsNone(self.entry.response)

    async def test_thread_named_ou_prefix_remains_shared(self):
        cg.clear_session(self.key)
        self.key = 'agent:main:feishu:group:oc_chat:ou_thread'
        self.entry = cg.register('cid', self.key, 'Pick?', ['A', 'B'])
        a = await self.adapter()
        await a.send_clarify('oc_chat', 'Pick?', ['A', 'B'], 'cid', self.key, {'thread_id': 'ou_thread'})
        self.click(a, user='ou_other')
        self.assertEqual(self.entry.response, 'A')

    async def test_registration_preserves_every_official_field(self):
        from plugins.platforms.feishu import adapter as official
        class Capture:
            def register_platform(self, **kwargs):
                self.fields = kwargs
        original, enhanced = Capture(), Capture()
        official.register(original)
        self.assertTrue(hasattr(plugin, 'register'), 'official plugin entry point missing')
        plugin.register(enhanced)
        self.assertIs(enhanced.fields.pop('adapter_factory'), plugin.ClarifyFeishuAdapter)
        original.fields.pop('adapter_factory')
        self.assertEqual(enhanced.fields, original.fields)

    async def test_upstream_native_and_local_patch_fail_safe(self):
        from plugins.platforms.feishu import adapter as official
        class Capture:
            fields = None
            def register_platform(self, **kwargs):
                self.fields = kwargs
        async def native(*args, **kwargs):
            pass
        for module in ('plugins.platforms.feishu.adapter', 'plugins.platforms.feishu.clarify'):
            native.__module__ = module
            target = Capture()
            with patch.object(official.FeishuAdapter, 'send_clarify', native), self.assertLogs(plugin.logger, level='WARNING') as logged:
                plugin.register(target)
            self.assertIn('LOCAL CORE PATCH' if module.endswith('.clarify') else 'upstream/native', logged.output[0])
            self.assertIsNone(target.fields, 'must not stack on native or prior local core override')

    async def test_disconnect_clears_own_state_and_delegates(self):
        from plugins.platforms.feishu.adapter import FeishuAdapter
        a = await self.adapter()
        with patch.object(FeishuAdapter, 'disconnect', new_callable=AsyncMock) as parent:
            await a.disconnect()
            parent.assert_awaited_once()
        self.assertFalse(a._clarify_cards)

    async def test_passthrough_unknown_callbacks_and_approvals(self):
        from plugins.platforms.feishu.adapter import FeishuAdapter
        a = await self.adapter()
        for value in ({'hermes_action': 'once'}, {'hermes_update_prompt_action': 'y'}, {'unknown': 1}, None, 'bad'):
            data = NS(event=NS(action=NS(value=value)))
            sentinel = object()
            with patch.object(FeishuAdapter, '_on_card_action_trigger', return_value=sentinel) as parent:
                self.assertIs(a._on_card_action_trigger(data), sentinel)
                parent.assert_called_once_with(data)

    async def test_rejects_missing_or_wrong_identity_and_indices(self):
        a = await self.adapter()
        for kwargs in ({'user': ''}, {'user': 'ou_intruder'}, {'chat': ''}, {'chat': 'wrong'},
                       {'message': ''}, {'message': 'wrong'}, {'index': -1}, {'index': True}, {'index': 99}, {'index': '0'}):
            self.click(a, **kwargs)
            self.assertIsNone(self.entry.response, kwargs)
        a._default_group_policy = 'disabled'
        self.click(a)
        self.assertIsNone(self.entry.response)

    async def test_shared_group_policy_and_per_user_thread_ownership(self):
        from gateway.session import SessionSource, build_session_key
        from gateway.config import Platform
        cg.clear_session(self.key)
        source = SessionSource(platform=Platform.FEISHU, chat_type='group', chat_id='oc_chat', user_id='ou_owner', thread_id='om_thread')
        self.key = build_session_key(source)
        self.entry = cg.register('cid', self.key, 'Pick?', ['A', 'B'])
        a = await self.adapter()
        await a.send_clarify('oc_chat', 'Pick?', ['A', 'B'], 'cid', self.key, {'thread_id': 'om_thread'})
        self.click(a, user='ou_other')
        self.assertEqual(self.entry.response, 'A')
        cg.clear_session(self.key)
        self.key = build_session_key(source, thread_sessions_per_user=True)
        self.entry = cg.register('cid', self.key, 'Pick?', ['A', 'B'])
        await a.send_clarify('oc_chat', 'Pick?', ['A', 'B'], 'cid', self.key, {'thread_id': 'om_thread'})
        self.click(a, user='ou_other')
        self.assertIsNone(self.entry.response)
        self.click(a)
        self.assertEqual(self.entry.response, 'A')

    async def test_retire_during_send_does_not_rearm_late_card(self):
        a = await self.adapter()
        async def late(*args, **kwargs):
            await a.retire_clarify_card('cid', 'Expired')
            return SendResult(success=True, message_id='late')
        a._send_interactive_card.side_effect = late
        await a.send_clarify('oc_chat', 'Pick?', ['A', 'B'], 'cid', self.key)
        self.assertNotIn('cid', a._clarify_cards)

    async def test_reused_id_cannot_answer_replacement_entry(self):
        a = await self.adapter()
        replacement = cg.register('cid', self.key, 'New?', ['X', 'Y'])
        self.click(a)
        self.assertIsNone(replacement.response)

    async def test_group_rules_rechecked_after_card_delivery(self):
        from plugins.platforms.feishu.adapter import FeishuGroupRule
        a = await self.adapter()
        for rule in (FeishuGroupRule('disabled'), FeishuGroupRule('admin_only'),
                     FeishuGroupRule('allowlist', allowlist={'someone_else'}),
                     FeishuGroupRule('blacklist', blacklist={'ou_owner'})):
            a._group_rules['oc_chat'] = rule
            self.click(a)
            self.assertIsNone(self.entry.response, rule)
        a._group_rules['oc_chat'] = FeishuGroupRule('allowlist', allowlist={'ou_owner'})
        self.click(a)
        self.assertEqual(self.entry.response, 'A')

    async def test_other_multi_and_empty_submit(self):
        self.entry.multi_select = True
        a = await self.adapter()
        self.click(a, op='submit')
        self.assertIsNone(self.entry.response)
        self.click(a, op='toggle', index=0, token='')
        self.assertFalse(a._clarify_cards['cid']['selected'])
        self.click(a, op='other')
        self.assertTrue(self.entry.awaiting_text)
        self.assertTrue(cg.resolve_text_response_for_session(self.key, 'custom'))
        self.assertEqual(self.entry.response, 'custom')

    async def test_dm_owner_and_official_interactive_allowlist(self):
        cg.clear_session(self.key)
        self.key = 'agent:main:feishu:dm:oc_chat:ou_owner'
        self.entry = cg.register('cid', self.key, 'Pick?', ['A', 'B'])
        a = await self.adapter()
        self.click(a, user='ou_other')
        self.assertIsNone(self.entry.response)
        a._allowed_group_users = {'ou_other'}
        self.click(a)
        self.assertIsNone(self.entry.response)
        a._allowed_group_users = {'ou_owner'}
        self.click(a)
        self.assertEqual(self.entry.response, 'A')

    async def test_changed_internal_signature_leaves_official_untouched(self):
        from plugins.platforms.feishu import adapter as official
        class Capture:
            fields = None
            def register_platform(self, **kwargs):
                self.fields = kwargs
        async def incompatible(self, changed):
            pass
        target = Capture()
        with patch.object(official.FeishuAdapter, '_send_interactive_card', incompatible), self.assertLogs(plugin.logger, level='WARNING'):
            plugin.register(target)
        self.assertIsNone(target.fields)

    async def test_native_card_single_choice(self):
        a = await self.adapter()
        card = a._send_interactive_card.call_args.args[1]
        self.assertEqual(card['elements'][0]['content'], 'Pick?')
        buttons = [b for e in card['elements'] if e['tag'] == 'action' for b in e['actions']]
        self.assertEqual([b['text']['content'] for b in buttons], ['选项 1', '选项 2', 'Other / 其他'])
        self.assertTrue(all(b['value'].get('hermes_feishu_clarify') == 'v1' for b in buttons))

if __name__ == '__main__':
    unittest.main()
