"""Readable choices with real card serialization/registry, mocked transport only."""
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

from gateway.config import PlatformConfig
from test_plugin import plugin
from tools import clarify_gateway as cg


CHOICES = [
    '短选项：显示正常 (Recommended)',
    '中等长度：这是一条用于检查飞书卡片是否会截断的测试选项',
    '长选项：' + '完整保留中文、emoji 🐼、换行\n以及 Markdown **原文**。' * 12 + '结束标记：小熊猫',
]


def buttons(card):
    return [button for element in card['elements'] if element['tag'] == 'action'
            for button in element['actions']]


def option_texts(card):
    return [element['text'] for element in card['elements'] if element['tag'] == 'div']


class CardLayout(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = 'agent:main:feishu:group:oc_test:ou_owner'
        self.entry = cg.register('readable-card', self.key, '请先阅读完整说明，再选择。', list(CHOICES))
        self.adapter = plugin.ClarifyFeishuAdapter(
            PlatformConfig(enabled=True, extra={'default_group_policy': 'open'}))
        self.adapter._client = MagicMock()
        self.adapter._loop = NS(is_closed=lambda: False)
        self.adapter._feishu_send_with_retry = AsyncMock(return_value=NS(
            success=lambda: True, data=NS(message_id='om_test')))
        self.adapter._card_response = lambda card_data=None: card_data

    def tearDown(self):
        cg.clear_session(self.key)

    async def send(self):
        result = await self.adapter.send_clarify('oc_test', self.entry.question,
            self.entry.choices, self.entry.clarify_id, self.key)
        self.assertTrue(result.success)
        call = self.adapter._feishu_send_with_retry.call_args.kwargs
        self.assertEqual(call['msg_type'], 'interactive')
        return json.loads(call['payload'])

    def click(self, op, index=0, token='token-1', user='ou_owner'):
        return self.adapter._on_card_action_trigger(NS(event=NS(
            operator=NS(open_id=user),
            context=NS(open_chat_id='oc_test', open_message_id='om_test'), token=token,
            action=NS(value={plugin.NAMESPACE: 'v1', 'id': self.entry.clarify_id,
                            'op': op, 'index': index}))))

    def assert_readable(self, card):
        self.assertEqual(card['elements'][0]['content'], self.entry.question)
        texts = option_texts(card)
        self.assertEqual(len(texts), len(CHOICES))
        for i, (text, original) in enumerate(zip(texts, CHOICES)):
            self.assertEqual(text['tag'], 'plain_text')
            self.assertEqual(text['content'], f'{i + 1}. {original}')
            self.assertNotIn('lines', text, 'Do not reintroduce ellipsis through line limits')
        first_action = next(i for i, e in enumerate(card['elements']) if e['tag'] == 'action')
        self.assertEqual(first_action, 1 + len(CHOICES))

    async def test_full_original_choices_precede_short_buttons_on_wire(self):
        card = await self.send()
        self.assert_readable(card)
        actual = buttons(card)
        self.assertEqual([b['text']['content'] for b in actual],
                         ['选项 1', '选项 2', '选项 3', 'Other / 其他'])
        self.assertEqual([b['value']['index'] for b in actual[:3]], [0, 1, 2])
        self.assertTrue(all(b['value']['op'] == 'choose' for b in actual[:3]))
        self.assertTrue(all(b['value'][plugin.NAMESPACE] == 'v1' for b in actual))

    async def test_single_click_returns_original_not_button_label(self):
        await self.send()
        response = self.click('choose', index=2)
        self.assertEqual(self.entry.response, CHOICES[2])
        self.assertEqual(response['elements'][0]['content'], CHOICES[2])
        self.click('choose', index=0)
        self.assertEqual(self.entry.response, CHOICES[2], 'A replay must not replace the answer')

    async def test_multi_refresh_preserves_full_text_and_number_mapping(self):
        self.entry.multi_select = True
        initial = await self.send()
        self.assert_readable(initial)
        self.assertEqual([b['text']['content'] for b in buttons(initial)],
                         ['选项 1', '选项 2', '选项 3', 'Submit / 提交', 'Other / 其他'])
        selected = self.click('toggle', index=2)
        self.assert_readable(selected)
        self.assertEqual(buttons(selected)[2]['text']['content'], '✓ 选项 3')
        self.assertEqual(buttons(selected)[2]['type'], 'primary')
        self.assertEqual(buttons(selected)[2]['value']['index'], 2)
        self.click('toggle', index=2)  # Same delivery token must not undo selection.
        self.click('toggle', index=0, token='token-2')
        deselected = self.click('toggle', index=2, token='token-3')
        self.assert_readable(deselected)
        self.assertEqual(buttons(deselected)[2]['text']['content'], '选项 3')
        self.assertEqual(buttons(deselected)[2]['type'], 'default')
        self.click('submit', token='token-4')
        assert self.entry.response is not None
        self.assertEqual(json.loads(self.entry.response), [CHOICES[0]])

    async def test_multi_submit_keeps_original_text_and_original_order(self):
        self.entry.multi_select = True
        await self.send()
        self.click('submit')
        self.assertIsNone(self.entry.response)
        self.click('toggle', index=2, token='token-2')
        self.click('toggle', index=0, token='token-3')
        self.click('submit', token='token-4')
        assert self.entry.response is not None
        self.assertEqual(json.loads(self.entry.response), [CHOICES[0], CHOICES[2]])

    async def test_other_still_captures_text_in_original_session(self):
        await self.send()
        self.click('other')
        self.assertTrue(self.entry.awaiting_text)
        self.assertTrue(cg.resolve_text_response_for_session(self.key, '我自己输入的答案'))
        self.assertEqual(self.entry.response, '我自己输入的答案')

    async def test_wrong_user_cannot_use_short_button_to_answer(self):
        await self.send()
        self.click('choose', index=2, user='ou_other')
        self.assertIsNone(self.entry.response)
        self.click('choose', index=2)
        self.assertEqual(self.entry.response, CHOICES[2])

    def test_numbering_handles_more_than_alphabet_without_changing_indices(self):
        choices = [f'原选项 {i}' for i in range(28)]
        card = self.adapter._clarify_card('Pick', choices, 'many')
        self.assertEqual(option_texts(card)[26]['content'], '27. 原选项 26')
        self.assertEqual(buttons(card)[26]['text']['content'], '选项 27')
        self.assertEqual(buttons(card)[26]['value']['index'], 26)
        self.assertTrue(all(len(e['actions']) <= 3 for e in card['elements'] if e['tag'] == 'action'))


if __name__ == '__main__':
    unittest.main()
