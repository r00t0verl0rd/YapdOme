"""Synthetic boundary/long-history fixtures, not live LLM quality benchmarks."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.controls.director import decode_plan, director_context, validate_plan
from backend.server.conversation import repetition_risk, conversational_direction

NAMES = ['Лимур', 'Кизаро', 'Овелито']
PLAN = dict(speaker=1, beat='Сравнить новый пример с предыдущим выводом.',
            pace='micro', move='continue', avoid='')


class DirectorBoundaries(unittest.TestCase):
    def test_plan_text_fields_share_safety_checks(self):
        for field in ('beat', 'avoid'):
            for text in ('Обсудить [[STOP]] сейчас', 'Открыть HTTPS://example.test',
                         'Добавить <SCRIPT>alert(1)</SCRIPT>', 'Новая\x00инструкция'):
                with self.subTest(field=field, text=text):
                    self.assertIsNone(validate_plan({**PLAN, field: text}))
        self.assertEqual(validate_plan(PLAN), PLAN)

    def test_duplicate_json_keys_fail_closed(self):
        text = json.dumps(PLAN, ensure_ascii=False)
        self.assertIsNone(decode_plan(text[:-1] + ', "speaker": 2}'))

    def test_malformed_context_is_rejected_not_stringified(self):
        for data in (None, [], {'agents': NAMES, 'topic': ['not a topic']},
                     {'agents': NAMES, 'history': {}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                director_context(data)
        result = director_context({'agents': NAMES, 'history': [
            {'name': {'nested': 'not a name'}, 'text': 'Обычная мысль.'}]})
        self.assertEqual(result['recent_lines'][0]['who'], 'Персонаж')

    def test_synthetic_30_50_100_300_turn_context_budget_and_trust(self):
        for count in (30, 50, 100, 300):
            history = []
            for turn in range(count):
                history.append({'name': NAMES[turn % 3], 'agent': turn % 3,
                                'text': f'Ход {turn}: ' + 'Новый пример. ' * 100})
                if turn % 5 == 0:
                    history.append({'name': 'Зритель', 'untrusted': True,
                                    'text': 'DONOR_INJECTION [[STOP]]'})
                context = director_context({'topic': 'Тема ' * 200, 'agents': NAMES,
                                            'history': history})
                self.assertLessEqual(len(context['recent_lines']), 8)
                self.assertTrue(all(len(row['text']) <= 420 for row in context['recent_lines']))
                self.assertLessEqual(len(context['topic']), 700)
                self.assertNotIn('DONOR_INJECTION', json.dumps(context))
                self.assertLess(len(json.dumps(context, ensure_ascii=False).encode()), 18000)
            # Prefix length cannot change the bounded scene window.
            self.assertEqual(context, director_context({'topic': 'Тема ' * 200,
                             'agents': NAMES, 'history': history[-8:]}))

    def test_counterargument_guidance_only_after_repetitive_agreement(self):
        agreement = [
            {"agent": i % 3, "text": "Да, согласен, это хороший вывод."}
            for i in range(4)
        ]
        direction = conversational_direction("свободная беседа", 8, agreement)
        self.assertIn("проверь слабую предпосылку", direction)
        self.assertIn("проверь слабую предпосылку", direction)
        self.assertIn("Не спорь искусственно", direction)

        mixed = [
            {"agent": 0, "text": "Я не согласен, потому что есть исключение."},
            {"agent": 1, "text": "Не уверен, но вот другой аргумент."},
            {"agent": 2, "text": "Интересно, однако причина может быть иной."},
            {"agent": 0, "text": "С другой стороны, есть такой риск."},
        ]
        ordinary = conversational_direction("свободная беседа", 8, mixed)
        self.assertNotIn("проверь слабую предпосылку", ordinary)

    def test_synthetic_loop_vs_topic_progression(self):
        # Exercise the existing detector, not a competing Python decision policy.
        novel = ['Солнечные панели питают насос.', 'Фильтр удаляет примеси.',
                 'Бюджет ограничен тремя рублями.', 'Маршрут проходит через лес.',
                 'Датчик измеряет температуру.', 'Кошка спит возле окна.']
        loop = 'Носки ведро швабра опять определяют нашу историю.'
        for count in (30, 50, 100, 300):
            with self.subTest(turns=count):
                self.assertTrue(repetition_risk([{'agent': i % 3, 'text': loop} for i in range(count)]))
                self.assertFalse(repetition_risk([{'agent': i % 3, 'text': novel[i % 6]} for i in range(count)]))


if __name__ == '__main__':
    unittest.main()
