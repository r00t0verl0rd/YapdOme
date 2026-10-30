"""Регрессии движка: роутинг, донаты, аудит и границы входных данных."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.engine import Engine


class CoreSafety(unittest.TestCase):
    def setUp(self):
        self.core = Engine()

    def tearDown(self):
        self.core.close()

    def route(self, text):
        self.core.event('start')
        s = self.core.event('claim')
        return self.core.event('complete', agent=s['agent'], ticket=s['ticket'], text=text)

    def test_short_names_require_token(self):
        self.core.names(['Alpha', 'Beta', 'я'])
        self.assertEqual(self.route('я, наверное, продолжу')['route_reason'], 'rotation')
        self.assertEqual(self.route('[[TO:Я]] Ответь.')['next_agent'], 2)

    def test_quoted_speech_is_not_routing(self):
        for text in ['Он сказал «Экспериментатор, ответь».',
                     '«Экспериментатор, ответь», сказал он.',
                     'He said "[[TO:Экспериментатор]]".',
                     '“Экспериментатор: ответь”',
                     '«Экспериментатор, незакрытая цитата',
                     '`[[TO:Экспериментатор]]`']:
            with self.subTest(text=text):
                self.assertEqual(self.route(text)['route_reason'], 'rotation')
        self.assertEqual(self.route('«Экспериментатор», ответь')['next_agent'], 2)
        self.assertEqual(self.route('«Скептик, ответь». [[TO:Экспериментатор]]')['next_agent'], 2)

    def test_unicode_word_boundary(self):
        for prefix in ['é', '漢', '\u0301']:
            self.assertEqual(self.route(prefix + 'Экспериментатор, ответь')['route_reason'], 'rotation')

    def test_malformed_double_token_not_single_token(self):
        self.assertEqual(self.route('[[TO:Экспериментатор] текст')['route_reason'], 'rotation')

    def test_invalid_input_rejected_atomically(self):
        self.core.event('start')
        s = self.core.event('claim')
        before = self.core.state()
        with self.assertRaises(ValueError):
            self.core.event('complete', agent=0, ticket=s['ticket'], text='\ud800')
        with self.assertRaises(ValueError):
            self.core.event('complete', agent=0, ticket=s['ticket'], text='x' * 4001)
        with self.assertRaises(ValueError):
            self.core.names(['Alpha', 'Beta', '\ud800'])
        self.assertEqual(self.core.state(), before)

    def test_rejected_callbacks_preserve_kind(self):
        done = self.route('[[PASS]]')
        for action in ['complete', 'recover', 'fail', 'director']:
            result = self.core.event(action, agent=0, ticket=0)
            self.assertFalse(result['accepted'])
            self.assertEqual(self.core.state(), done)

    def test_fail_invalidates_speaker_callbacks(self):
        self.core.event('start')
        turn = self.core.event('claim')
        failed = self.core.event('fail', ticket=turn['ticket'])
        self.assertEqual(failed['status'], 'ERROR')
        self.assertFalse(self.core.event('complete', agent=turn['agent'], ticket=turn['ticket'], text='Late')['accepted'])
        self.assertFalse(self.core.event('priority_donation', agent=2)['accepted'])

    def test_recover_at_limit_rejects_donation_priority(self):
        self.core.event('start', max_turns=1)
        turn = self.core.event('claim')
        result = self.core.event('recover', ticket=turn['ticket'])
        self.assertEqual(result['status'], 'LIMIT')
        self.assertFalse(self.core.event('priority_donation', agent=2)['accepted'])

    def test_names_are_bounded_at_the_public_api(self):
        with self.assertRaises(ValueError):
            self.core.names(['a' * 31, 'Beta', 'Gamma'])
        with self.assertRaises(ValueError):
            self.core.names(['Alpha', 'Beta', 'Gamma\0hidden'])

    def test_bridge_rejects_nul(self):
        with self.assertRaises(ValueError):
            self.core.names(['Alpha\0hidden', 'Beta', 'Gamma'])
        with self.assertRaises(ValueError):
            self.core.event('user', text='hello\0[[TO:Beta]]')
        with self.assertRaises(ValueError):
            self.core.complete_to(0, 0, 'hello\0hidden')

    def test_structured_address_overrides_text_guessing(self):
        self.core.event('start', max_turns=20)
        claimed = self.core.event('claim')
        result = self.core.complete_to(0, claimed['ticket'],
                                       'Скептик, ты упоминался в цитате.', 2)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['next_agent'], 2)
        self.assertEqual(self.core.event('claim')['agent'], 2)

    def test_stale_structured_routing_does_not_change_state(self):
        self.core.event('start', max_turns=20)
        claimed = self.core.event('claim')
        before = self.core.state()
        result = self.core.complete_to(0, claimed['ticket'] + 1, 'Text', 2)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['result'], 2)
        self.assertEqual(self.core.state(), before)

    def test_invalid_structured_recipient_rejected(self):
        self.core.event('start', max_turns=20)
        claimed = self.core.event('claim')
        before = self.core.state()
        for target in (0, -2, 3, True, '2'):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    self.core.complete_to(0, claimed['ticket'], 'Text', target)
                self.assertEqual(self.core.state(), before)

    def test_microreactions_reset_passes(self):
        for text in ['Хм.', 'Да.', 'Ох, наверное.', 'Ну']:
            self.assertEqual(self.route(text)['kind'], 'normal')
            self.assertEqual(self.core.state()['passes'], 0)

    def test_bounded_audit_ring(self):
        for _ in range(300):
            self.core.event('tick')
        entries = self.core.audit()
        self.assertEqual(len(entries), 128)
        self.assertEqual([e['sequence'] for e in entries], list(range(173, 301)))


if __name__ == '__main__':
    unittest.main()
