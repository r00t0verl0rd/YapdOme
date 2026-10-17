"""Регрессии роутинга научного режима: адресация и speaking-token."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.engine import Engine

NAMES = ["Архитектор", "Скептик", "Экспериментатор"]
NEUTRAL = "Продолжаю мысль без обращения к кому-либо."


class ScienceRouting(unittest.TestCase):
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
                           ('[[TO:Экспериментатор]]\nПроверь это.', 2),
                           ('[TO:Экспериментатор] проверь', 2),
                           ('Мысль. [[to:экспериментатор]]', 2),
                           ('[[TO:Архитектор]] а ты?', 0)]:
            self.core.event('start', max_turns=0)
            next_agent, kind, reason = self.route(1, text)
            self.assertEqual(next_agent, want, text)
            self.assertEqual(reason, 'token', text)
            self.assertEqual(kind, 'normal', text)

    def test_to_any_falls_back_to_rotation(self):
        self.core.event('start', max_turns=0)
        next_agent, _, reason = self.route(0, '[[TO:ANY]] Кто хочет ответить?')
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

    def test_interrupted_speaker_always_gets_the_floor_back(self):
        # The old code compared next_agent to the rotation target, so an
        # interrupter who addressed the third agent silently dropped the
        # interrupted speaker's right to answer.
        for interrupter, third in ((1, 2), (2, 1)):
            self.core.event('start', max_turns=0)
            first = self.core.event('claim')
            self.assertEqual(first['agent'], 0)
            self.core.event('interrupt', agent=interrupter, ticket=first['ticket'])
            second = self.core.event('claim')
            self.assertEqual(second['agent'], interrupter)
            done = self.core.event('complete', agent=interrupter, ticket=second['ticket'],
                                   text=NEUTRAL)
            self.assertEqual(done['next_agent'], 0, (interrupter, third))
            self.assertEqual(done['route_reason'], 'pending_reply')
            self.assertEqual(self.core.event('claim')['agent'], 0)

    def test_explicit_address_still_overrides_pending_reply(self):
        self.core.event('start', max_turns=0)
        first = self.core.event('claim')
        self.core.event('interrupt', agent=2, ticket=first['ticket'])
        second = self.core.event('claim')
        done = self.core.event('complete', agent=2, ticket=second['ticket'],
                               text='Скептик, как ты думаешь?')
        self.assertEqual(done['next_agent'], 1)
        self.assertEqual(done['route_reason'], 'address')

    def test_interrupt_breaks_the_carousel(self):
        # A research discussion answers the critic before moving on: A -> B -> A -> C.
        self.core.event('start', max_turns=0)
        first = self.core.event('claim')                      # 0
        self.core.event('interrupt', agent=1, ticket=first['ticket'])
        second = self.core.event('claim')                     # 1
        self.core.event('complete', agent=1, ticket=second['ticket'], text=NEUTRAL)
        third = self.core.event('claim')                      # back to 0
        self.assertEqual(third['agent'], 0)
        done = self.core.event('complete', agent=0, ticket=third['ticket'], text=NEUTRAL)
        self.assertEqual(done['next_agent'], 2, 'the agent who waited longest should speak')

    def test_names_with_spaces_and_mixed_case(self):
        self.core.names(["Критик Иван", "Аналитик Мария", "Инженер Пётр"])
        self.assertEqual(self.core.event('claim')['agent'], 0)
        done = self.core.event('complete', agent=0, ticket=self.core.state()['ticket'],
                               text='**Аналитик Мария**, проверь выводы.')
        self.assertEqual(done['next_agent'], 1)

    def test_python_engine_version_matches_release(self):
        from backend import __version__
        self.assertEqual(__version__, '0.2.0')

    def test_route_reason_is_reported_through_bridge(self):
        self.assertTrue(self.core.state()['route_reason'] in
                        ('none', 'rotation', 'token', 'address', 'pending_reply',
                         'override', 'interrupt'))


if __name__ == '__main__':
    unittest.main()
