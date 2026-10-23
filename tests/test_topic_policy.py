"""Accepted once-per-real-session policy at the documented pre_llm_call seam."""
import unittest
from unittest.mock import AsyncMock, patch
import test_reply_context as trace
plugin = trace.plugin


class TopicPolicy(unittest.IsolatedAsyncioTestCase):
    async def normalize(self, **kwargs):
        adapter, event = await trace.ReplyContextContracts().normalize(**kwargs)
        adapter._topic_context_hook_ready = True
        with patch.object(trace.FeishuAdapter, '_dispatch_inbound_event', new_callable=AsyncMock):
            await type(adapter)._dispatch_inbound_event(adapter, event)
        return adapter, event

    def format(self, event):
        return trace.GatewayInboundMixin._prepend_inbound_reply_context(event, event.source, event.text)

    async def test_disabled_and_multiplex_modes_preserve_official_quotes(self):
        from types import SimpleNamespace as NS
        for multiplex, enabled in ((False, False), (True, True)):
            adapter, event = await trace.ReplyContextContracts().normalize()
            adapter._topic_context_hook_ready = True
            adapter.config.extra['topic_root_context_once'] = enabled
            adapter.gateway_runner = NS(config=NS(multiplex_profiles=multiplex))
            with patch.object(trace.FeishuAdapter, '_dispatch_inbound_event', new_callable=AsyncMock):
                await type(adapter)._dispatch_inbound_event(adapter, event)
            self.assertIn('Original topic:', self.format(event))

    async def test_reference_survives_native_json_roundtrip_and_is_profile_scoped(self):
        import json
        import os
        import tempfile
        _, event = await self.normalize()
        text = json.loads(json.dumps({'reply_to_text': event.reply_to_text}))['reply_to_text']
        hook = plugin.topic_context.before_llm
        with tempfile.TemporaryDirectory(dir=os.environ['HERMES_TEST_SCRATCH']) as directory:
            with patch.dict(os.environ, HERMES_HOME=directory):
                result = hook(session_id='isolated', platform='feishu', sender_id='ou_sender', user_message=text)
                self.assertIn('unavailable', result['context'])
        self.assertIn('Original topic:', hook(session_id='json-restored', platform='feishu', sender_id='ou_sender', user_message=text)['context'])

    async def test_multimodal_input_keeps_full_official_quote(self):
        from gateway.platforms.event import MessageType
        adapter, event = await trace.ReplyContextContracts().normalize()
        adapter._topic_context_hook_ready = True
        event.message_type = MessageType.PHOTO
        event.media_urls = ['photo.png']
        with patch.object(trace.FeishuAdapter, '_dispatch_inbound_event', new_callable=AsyncMock):
            await type(adapter)._dispatch_inbound_event(adapter, event)
        self.assertIn('Original topic:', self.format(event))

    async def test_hook_sidecar_is_supplied_by_real_context_collector(self):
        from types import SimpleNamespace as NS
        from agent.turn_context import _collect_pre_llm_call_context
        _, event = await self.normalize()
        messages = [{'role': 'user', 'content': self.format(event)}]
        agent = NS(session_id='real-context-collector', model='test', platform='feishu', _user_id='ou_sender')
        hook = plugin.topic_context.before_llm
        def invoke(name, **kwargs):
            value = hook(**kwargs)
            return [value] if value else []
        with patch('hermes_cli.lifecycle.invoke_hook', side_effect=invoke):
            context = _collect_pre_llm_call_context(agent, effective_task_id='task', turn_id='turn',
                       original_user_message=self.format(event), messages=messages, conversation_history=[])
        self.assertIn('Original topic:', context)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['role'], 'user')

    async def test_copied_reference_cannot_expose_context_to_another_sender(self):
        _, event = await self.normalize()
        result = plugin.topic_context.before_llm(session_id='other-user', platform='feishu',
                    sender_id='ou_other', user_message=self.format(event))
        self.assertIsNone(result)

    async def test_long_roots_keep_official_full_quote_instead_of_hook_spill(self):
        text = 'LONG REQUIREMENT ' * 1000
        _, event = await self.normalize(parent_text=text)
        self.assertIn(text, self.format(event))

    async def test_storage_capacity_fails_open_to_full_quote(self):
        with patch.object(plugin.topic_context, 'MAX_REFERENCE_FILES', 0, create=True):
            _, event = await self.normalize(parent_text='unique capacity test')
        self.assertIn('unique capacity test', self.format(event))
        self.assertNotIn('Feishu topic root reference:', self.format(event))

    async def test_non_root_private_and_ordinary_group_quotes_stay_full(self):
        for options in ({'parent_id': 'om_explicit'}, {'upper_message_id': 'om_upper'},
                        {'chat_type': 'p2p'}, {'thread_id': None}):
            with self.subTest(options=options):
                _, event = await self.normalize(**options)
                self.assertIn('Original topic: all requirements and code', self.format(event))

    async def test_new_topic_is_independent_even_in_same_actual_session(self):
        _, first = await self.normalize()
        _, second = await self.normalize(thread_id='omt_new')
        hook = plugin.topic_context.before_llm
        for event in (first, second):
            self.assertIn('Original topic:', hook(session_id='two-topics', platform='feishu', sender_id='ou_sender',
                                                  user_message=self.format(event))['context'])

    async def test_failed_fetch_does_not_mark_root_seen(self):
        _, failed = await self.normalize(parent_text=None)
        hook = plugin.topic_context.before_llm
        self.assertIsNone(hook(session_id='failed-fetch', platform='feishu', sender_id='ou_sender', user_message=self.format(failed)))
        _, retry = await self.normalize()
        self.assertIn('Original topic:', hook(session_id='failed-fetch', platform='feishu', sender_id='ou_sender',
                                             user_message=self.format(retry))['context'])

    async def test_real_new_command_rotates_session_and_reallows_root(self):
        import os
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace as NS
        from unittest.mock import Mock
        from gateway.config import GatewayConfig
        from gateway.session import SessionStore, build_session_key
        from gateway.slash_commands_session import GatewaySessionCommandsMixin
        _, event = await self.normalize()
        with tempfile.TemporaryDirectory(dir=os.environ['HERMES_TEST_SCRATCH']) as directory:
            store = SessionStore(Path(directory), GatewayConfig())
            old = store.get_or_create_session(event.source)
            text = self.format(event)
            hook = plugin.topic_context.before_llm
            self.assertIn('Original topic:', hook(session_id=old.session_id, platform='feishu', sender_id='ou_sender', user_message=text)['context'])
            runner = NS(session_store=store, _session_db=None,
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
            new = store.lookup_by_session_key(old.session_key)
            self.assertNotEqual(old.session_id, new.session_id)
            self.assertIsNone(hook(session_id=old.session_id, platform='feishu', sender_id='ou_sender', user_message=text))
            self.assertIn('Original topic:', hook(session_id=new.session_id, platform='feishu', sender_id='ou_sender', user_message=text)['context'])

    async def test_inactive_hook_never_loses_the_official_quote(self):
        adapter, event = await trace.ReplyContextContracts().normalize()
        adapter._topic_context_hook_ready = False
        with patch.object(trace.FeishuAdapter, '_dispatch_inbound_event', new_callable=AsyncMock):
            await type(adapter)._dispatch_inbound_event(adapter, event)
        self.assertIn('Original topic: all requirements and code', self.format(event))

    async def test_root_context_is_injected_once_per_actual_session(self):
        adapter, event = await self.normalize()
        # Normalization leaves a small opaque reference, not the full root quote.
        self.assertNotIn('Original topic: all requirements and code', self.format(event))
        hook = plugin.topic_context.before_llm
        first = hook(session_id='actual-1', platform='feishu', sender_id='ou_sender', user_message=self.format(event))
        self.assertIn('Original topic: all requirements and code', first['context'])
        self.assertIsNone(hook(session_id='actual-1', platform='feishu', sender_id='ou_sender', user_message=self.format(event)))
        fresh = hook(session_id='actual-2', platform='feishu', sender_id='ou_sender', user_message=self.format(event))
        self.assertIn('Original topic: all requirements and code', fresh['context'])
