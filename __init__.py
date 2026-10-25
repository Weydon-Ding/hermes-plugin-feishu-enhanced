"""Community Feishu clarify cards and topic quotes; no global class mutation."""
import logging
from plugins.platforms.feishu.adapter import FeishuAdapter
from .clarify import FeishuClarifyMixin, NAMESPACE
from tools import clarify_gateway as cg

logger = logging.getLogger(__name__)


class ClarifyFeishuAdapter(FeishuClarifyMixin, FeishuAdapter):
    """Clarify cards and native topic-root quote suppression."""

    async def _dispatch_inbound_event(self, event):
        source = event.source
        raw = getattr(getattr(event.raw_message, 'event', None), 'message', None)
        root = getattr(raw, 'root_id', None)
        if (source and source.chat_type == 'group' and source.thread_id
                and root and event.reply_to_message_id == root):
            event.reply_to_text = None
        return await super()._dispatch_inbound_event(event)


def register(ctx):
    """Forward all official metadata through the caller's scoped context."""
    from plugins.platforms.feishu import adapter as official
    from gateway.platforms.base import BasePlatformAdapter
    if official.FeishuAdapter.send_clarify is not BasePlatformAdapter.send_clarify:
        module = official.FeishuAdapter.send_clarify.__module__
        if module == 'plugins.platforms.feishu.clarify':
            logger.warning('Feishu clarify: prior LOCAL CORE PATCH detected; plugin inactive. Back up and review that patch before manual migration.')
        else:
            logger.warning('Feishu clarify: upstream/native or unknown clarify override detected; preserving it, plugin inactive.')
        return
    required = ('_send_interactive_card', '_card_response', '_allow_group_message', '_on_card_action_trigger',
                '_response_succeeded', '_resolve_sender_profile', '_is_interactive_operator_authorized')
    if any(not callable(getattr(official.FeishuAdapter, name, None)) for name in required) or not hasattr(cg, '_entries') or not hasattr(cg, '_lock'):
        logger.warning('Feishu clarify: incompatible internal API; leaving official adapter untouched.')
        return

    import inspect
    try:
        inspect.signature(official.FeishuAdapter._send_interactive_card).bind(
            None, 'chat', {}, None, 'failure', state_map={}, state_id='id', session_key='key')
        inspect.signature(official.FeishuAdapter._on_card_action_trigger).bind(None, None)
        inspect.signature(official.FeishuAdapter._allow_group_message).bind(None, None, 'chat')
        inspect.signature(official.FeishuAdapter._card_response).bind({})
        inspect.signature(official.FeishuAdapter._resolve_sender_profile).bind(None, None, is_bot=False)
        inspect.signature(official.FeishuAdapter._is_interactive_operator_authorized).bind(None, 'open_id')
    except (TypeError, ValueError):
        logger.warning('Feishu clarify: incompatible internal signature; leaving official adapter untouched.')
        return

    class ScopedRegistration:
        def register_platform(self, *args, **kwargs):
            kwargs['adapter_factory'] = ClarifyFeishuAdapter
            return ctx.register_platform(*args, **kwargs)

    official.register(ScopedRegistration())
