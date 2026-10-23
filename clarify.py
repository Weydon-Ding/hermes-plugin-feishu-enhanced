"""Adapted from the user's existing FeishuClarifyMixin, not a core patch.

Reuse: card layout, registry resolution, multi-selection and retirement protocol.
Changes: standalone imports, owned callback namespace, strict identity checks,
thread-aware session ownership, fail-safe delivery and adapter-local lifecycle.
"""
import json
import logging
from types import SimpleNamespace

from plugins.platforms.feishu.adapter import _card, _card_button
from tools import clarify_gateway as cg

logger = logging.getLogger(__name__)
NAMESPACE = 'hermes_feishu_clarify'


class FeishuClarifyMixin:
    async def disconnect(self):
        with cg._lock:
            getattr(self, '_clarify_cards', {}).clear()
        return await super().disconnect()

    @staticmethod
    def _clarify_card(question, choices, clarify_id, multi=False, selected=()):
        actions = [_card_button(('✓ ' if i in selected else '') + str(label),
                   'primary' if i in selected else 'default', {
                       NAMESPACE: 'v1', 'id': clarify_id, 'op': 'toggle' if multi else 'choose', 'index': i,
                   }) for i, label in enumerate(choices)]
        if multi:
            actions.append(_card_button('Submit / 提交', 'primary', {
                NAMESPACE: 'v1', 'id': clarify_id, 'op': 'submit'}))
        actions.append(_card_button('Other / 其他', 'default', {
            NAMESPACE: 'v1', 'id': clarify_id, 'op': 'other'}))
        card = _card('Hermes · Question', 'blue', question)
        card['elements'].extend({'tag': 'action', 'actions': actions[i:i + 3]}
                                for i in range(0, len(actions), 3))
        return card

    async def send_clarify(self, chat_id, question, choices, clarify_id, session_key, metadata=None):
        if not choices:
            return await super().send_clarify(chat_id, question, choices, clarify_id, session_key, metadata)
        with cg._lock:
            entry = cg._entries.get(clarify_id)
            multi = bool(entry and entry.multi_select)
            if not hasattr(self, '_clarify_cards'):
                self._clarify_cards = {}
            state = {'chat': chat_id, 'message': '', 'key': session_key,
                     'selected': set(), 'tokens': set(), 'entry': entry, 'thread': (metadata or {}).get('thread_id')}
            self._clarify_cards[clarify_id] = state
        try:
            result = await self._send_interactive_card(
                chat_id, self._clarify_card(question, choices, clarify_id, multi),
                metadata, 'send_clarify failed', state_map={}, state_id=clarify_id, session_key=session_key)
        except Exception:
            logger.warning('Feishu clarify card send failed; using numbered text', exc_info=True)
            result = None
        if result is None or not result.success or not result.message_id:
            with cg._lock:
                getattr(self, '_clarify_cards', {}).pop(clarify_id, None)
            return await super().send_clarify(chat_id, question, choices, clarify_id, session_key, metadata)
        with cg._lock:
            current = cg._entries.get(clarify_id)
            # Retirement/disconnect may win while network I/O is in flight.
            if self._clarify_cards.get(clarify_id) is state and current is entry and current and not current.event.is_set():
                state['message'] = result.message_id
            elif self._clarify_cards.get(clarify_id) is state:
                self._clarify_cards.pop(clarify_id, None)
        return result

    def _on_card_action_trigger(self, data):
        event = getattr(data, 'event', None)
        value = getattr(getattr(event, 'action', None), 'value', None)
        if not isinstance(value, dict) or NAMESPACE not in value:
            return super()._on_card_action_trigger(data)
        return self._handle_clarify_card_action(event=event, action_value=value)

    def _clarify_operator_allowed(self, event, state):
        context = getattr(event, 'context', None)
        operator = getattr(event, 'operator', None)
        user = getattr(operator, 'open_id', '')
        if not isinstance(user, str) or not user or getattr(context, 'open_chat_id', '') != state['chat']:
            return False
        if not state['message'] or getattr(context, 'open_message_id', '') != state['message']:
            return False
        # build_session_key: agent:<profile>:feishu:<type>:<chat>[:thread][:owner].
        parts = state['key'].split(':')
        if len(parts) < 5 or parts[0] != 'agent' or parts[2] != 'feishu' or parts[4] != state['chat']:
            return False
        tail = parts[5:]
        if parts[3] == 'dm':
            # Callback transport authenticates membership in the private chat; also retain
            # the official interactive gate. Explicit owner suffixes must match.
            if state['thread']:
                if not tail or tail.pop() != state['thread']:
                    return False
            return len(tail) <= 1 and (not tail or tail[0] == user) and self._is_interactive_operator_authorized(user)
        if parts[3] not in ('group', 'channel', 'thread'):
            return False
        if not self._allow_group_message(SimpleNamespace(open_id=user, user_id=getattr(operator, 'user_id', '')), state['chat']):
            return False
        if state['thread']:
            if not tail or tail.pop(0) != state['thread']:
                return False
        return len(tail) <= 1 and (not tail or tail[0] == user)

    def _handle_clarify_card_action(self, *, event, action_value):
        cid = action_value.get('id')
        if not isinstance(cid, str) or action_value.get(NAMESPACE) != 'v1':
            return self._card_response()
        with cg._lock:
            states = getattr(self, '_clarify_cards', {})
            state, entry = states.get(cid), cg._entries.get(cid)
            if not state:
                return self._card_response()
            if not entry or entry is not state['entry'] or entry.event.is_set() or entry.session_key != state['key']:
                states.pop(cid, None)
                return self._card_response(_card('Hermes · Question', 'grey', 'Expired / 已过期'))
            if not self._clarify_operator_allowed(event, state):
                return self._card_response()
            kind = action_value.get('op')
            if kind == 'other':
                if cg.mark_awaiting_text(cid):
                    states.pop(cid, None)
                    return self._card_response(_card('Hermes · Question', 'blue', 'Please type your answer in this conversation / 请在当前会话输入答案'))
                return self._card_response()
            index = action_value.get('index')
            if entry.multi_select:
                token = getattr(event, 'token', '')
                if not isinstance(token, str) or not token or token in state['tokens']:
                    return self._card_response()
                if kind == 'toggle' and type(index) is int and 0 <= index < len(entry.choices or []):
                    state['tokens'].add(token)
                    state['selected'].symmetric_difference_update({index})
                    return self._card_response(self._clarify_card(entry.question, entry.choices, cid, True, state['selected']))
                if kind != 'submit' or not state['selected']:
                    return self._card_response()
                answer = json.dumps([entry.choices[i] for i in sorted(state['selected'])], ensure_ascii=False)
            else:
                if kind != 'choose' or type(index) is not int or not 0 <= index < len(entry.choices or []):
                    return self._card_response()
                answer = entry.choices[index]
            if not cg.resolve_gateway_clarify(cid, answer):
                return self._card_response()
            states.pop(cid, None)
            return self._card_response(_card('Hermes · Answered', 'green', answer))

    async def retire_clarify_card(self, clarify_id, notice):
        with cg._lock:
            state = getattr(self, '_clarify_cards', {}).pop(clarify_id, None)
        if not state or not state.get('message') or not self._client:
            return
        try:
            from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody
            body = PatchMessageRequestBody.builder().content(json.dumps(
                _card('Hermes · Question', 'grey', str(notice)), ensure_ascii=False)).build()
            request = PatchMessageRequest.builder().message_id(state['message']).request_body(body).build()
            response = await self._client.im.v1.message.apatch(request)
            if not self._response_succeeded(response):
                logger.warning('Failed to retire Feishu clarify card %s', clarify_id)
        except Exception:
            logger.warning('Failed to retire Feishu clarify card %s', clarify_id, exc_info=True)
