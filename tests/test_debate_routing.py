"""Регрессии роутинга дебатов: адресация, TO-токены, перебивания."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.engine import Engine

NAMES = ["Архитектор", "Скептик", "Экспериментатор"]
NEUTRAL = "Продолжаю мысль без обращения к кому-либо."


class DebateRouting(unittest.TestCase):
    def setUp(self):
        self.core = Engine()
        self.core.names(NAMES)
        self.core.event('start', max_turns=0)

    def tearDown(self):
        self.core.close()

    def run_to(self, speaker):
        """Advance the live session until `speaker` holds the floor."""
        cur = 0
        while cur != speaker:
            s = self.core.event('claim')
            self.assertEqual(s['agent'], cur)
            self.core.event('complete', agent=cur, ticket=s['ticket'], text=NEUTRAL)
            cur = (cur + 1) % 3
        s = self.core.event('claim')
        self.assertEqual(s['agent'], speaker)
        return s

    def route(self, speaker, text):
        """Return (next_agent, kind, route_reason) for one completed turn."""
        s = self.run_to(speaker)
        r = self.core.event('complete', agent=speaker, ticket=s['ticket'], text=text)
        return r['next_agent'], r['kind'], r['route_reason']

    def test_markdown_and_quote_addressing_is_not_lost(self):
        # Every one of these addressed agent 2 while round-robin wanted agent 1.
        for text in ['**Экспериментатор**, предложи тест.',
                     '«Экспериментатор», предложи тест.',
                     '__Экспериментатор__, предложи тест.',
                     'Экспериментатор — предложи тест.',
                     'Экспериментатор: предложи тест.',
                     'Экспериментатор\nПредложи тест.',
                     '**Экспериментатор:**\nПредложи тест.',
                     '"Экспериментатор", предложи тест.',
                     'Экспериментатор, предложи тест.']:
            self.core.event('start', max_turns=0)
            next_agent, kind, reason = self.route(0, text)
            self.assertEqual(next_agent, 2, text)
            self.assertEqual(kind, 'normal', text)
            self.assertEqual(reason, 'address', text)

    def test_explicit_to_token_is_format_independent(self):
        for text, want in [('[[TO:Экспериментатор]] Проверь это.', 2),
                           ('[[TO=Экспериментатор]] Проверь это.', 2),
                           ('[[TO:Экспериментатор]]\nПроверь это.', 2),
                           ('[TO:Экспериментатор] проверь', 2),
                           ('[TO=Экспериментатор] проверь', 2),
                           ('Мысль. [[to:экспериментатор]]', 2),
                           ('[[TO:Архитектор]] а ты?', 0)]:
            self.core.event('start', max_turns=0)
            next_agent, kind, reason = self.route(1, text)
            self.assertEqual(next_agent, want, text)
            self.assertEqual(reason, 'token', text)
            self.assertEqual(kind, 'normal', text)

    def test_to_any_falls_back_to_rotation(self):
        for marker in ("[[TO:ANY]]", "[[TO=ANY]]"):
            self.core.event('start', max_turns=0)
            next_agent, _, reason = self.route(0, marker + ' Кто хочет ответить?')
            self.assertEqual(next_agent, 1)
            self.assertEqual(reason, 'rotation')

    def test_to_self_allows_a_continuation_turn(self):
        self.core.event('start', max_turns=0)
        next_agent, kind, reason = self.route(0, '[[TO:SELF]] Договорю мысль.')
        self.assertEqual(next_agent, 0)
        self.assertEqual(reason, 'token')
        self.assertEqual(kind, 'normal')
        self.assertEqual(self.core.event('claim')['agent'], 0)

    def test_directive_only_turn_is_a_silent_pass(self):
        self.core.event('start', max_turns=0)
        next_agent, kind, _ = self.route(0, '[[TO:Экспериментатор]]')
        self.assertEqual(kind, 'pass')
        self.assertEqual(next_agent, 2)

    def test_punctuated_pass_marker_is_recognised(self):
        for text in ['[[PASS]].', '[[PASS]]!', '[[PASS]], ', 'PASS.']:
            self.core.event('start', max_turns=0)
            _, kind, _ = self.route(0, text)
            self.assertEqual(kind, 'pass', text)


    def test_names_with_spaces_and_mixed_case(self):
        self.core.names(["Критик Иван", "Аналитик Мария", "Инженер Пётр"])
        self.assertEqual(self.core.event('claim')['agent'], 0)
        done = self.core.event('complete', agent=0, ticket=self.core.state()['ticket'],
                               text='**Аналитик Мария**, проверь выводы.')
        self.assertEqual(done['next_agent'], 1)

    def test_engine_version_matches_release(self):
        from backend import __version__
        number = r'(?:0|[1-9][0-9]*)'
        import re
        self.assertRegex(__version__, rf'\A{number}\.{number}\.{number}\Z')
        self.assertEqual(__version__, '0.2.0')

    def test_route_reason_is_reported_through_bridge(self):
        self.assertTrue(self.core.state()['route_reason'] in
                        ('none', 'rotation', 'token', 'address', 'override'))


if __name__ == '__main__':
    unittest.main()
