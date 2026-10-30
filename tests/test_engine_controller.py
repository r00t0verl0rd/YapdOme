"""Регрессии контроллера эфира; без сети и модельных аккаунтов."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.engine import Engine

class EngineController(unittest.TestCase):
    def setUp(self):
        self.core = Engine()
        self.core.event('start', max_turns=24)
    def tearDown(self):
        self.core.close()
    def claim(self):
        s=self.core.event('claim')
        self.assertTrue(s['accepted'])
        return s
    def test_user_words_cannot_stop_live_session(self):
        current=self.claim()
        p=self.core.event('user', text='подожди не торопись')
        self.assertEqual(p['status'],'RUNNING')
        self.assertEqual(p['kind'],'user_pause')
        self.assertFalse(self.core.event('complete',agent=0,ticket=current['ticket'],text='late')['accepted'])
        self.assertEqual(self.claim()['agent'],1)

    def test_stop_words_not_privileged(self):
        for phrase in ['Стойте!', 'ПОДОЖДИ', 'Не торопись', 'STOP', 'Пауза']:
            self.core.event('start',max_turns=20)
            self.claim()
            self.assertEqual(self.core.event('user',text=phrase)['status'],'RUNNING',phrase)


    def test_native_wait_is_bounded(self):
        s=self.claim()
        w=self.core.event('complete',agent=0,ticket=s['ticket'],text='[[WAIT_USER]]')
        self.assertEqual(w['status'],'RUNNING')
        self.assertEqual(w['timeout_ms'],0)
        self.assertEqual(self.claim()['agent'],1)

    def test_unlimited_live_and_recover(self):
        self.core.event('start',max_turns=0)
        for i in range(8):
            s=self.claim()
            self.assertEqual(s['status'],'RUNNING')
            self.core.event('complete',ticket=s['ticket'],agent=s['agent'],text='hi')
        self.assertEqual(self.core.state()['turns'],8)
        for i in range(3):
            s=self.claim()
            failed=self.core.event('recover',ticket=s['ticket'])
        self.assertEqual(failed['status'],'ERROR')
        self.assertEqual(failed['errors'],3)

    def test_regular_user_message_resumes_from_wait(self):
        self.claim()
        self.core.event('user',text='Стойте!')
        x=self.core.event('user',text='нужен движок на си')
        self.assertEqual(x['status'],'RUNNING')
        self.assertEqual(self.claim()['agent'],1)
    def test_utf8_long_address_after_4000_bytes(self):
        s=self.claim()
        phrase='Это текст. ' * 340 + 'Экспериментатор: предложи тест.'
        self.assertGreater(len(phrase.encode()),4093)
        self.assertLessEqual(len(phrase),4000)
        self.core.event('complete',agent=0,ticket=s['ticket'],text=phrase)
        self.assertEqual(self.claim()['agent'],2)

    def test_address_punctuation_and_word_boundaries(self):
        for mark in [':',' —',' –','!','?',';', '.']:
            self.core.event('start',max_turns=20)
            s=self.claim()
            self.core.event('complete',agent=0,ticket=s['ticket'],text='Скептик'+mark+' объясни')
            self.assertEqual(self.claim()['agent'],1)
        self.core.event('start',max_turns=20)
        s=self.claim()
        self.core.event('complete',agent=0,ticket=s['ticket'],text='псевдоэкспериментатор: не имя')
        self.assertEqual(self.claim()['agent'],1)

    def test_pass_exact_only(self):
        for phrase in ['Pass the ball','PASS is a word','[[PASS]] и дальше мысль']:
            self.core.event('start',max_turns=20)
            s=self.claim()
            result=self.core.event('complete',ticket=s['ticket'],agent=0,text=phrase)
            self.assertEqual(result['kind'],'normal',phrase)
        self.core.event('start',max_turns=20)
        s=self.claim()
        self.assertEqual(self.core.event('complete',agent=0,ticket=s['ticket'],text='«[[PASS]]»')['kind'],'normal')
        self.core.event('start',max_turns=20)
        s=self.claim()
        self.assertEqual(self.core.event('complete',agent=0,ticket=s['ticket'],text='[[PASS]]')['kind'],'pass')

    def test_operator_pause_cannot_be_overridden_with_user_text(self):
        self.claim();p=self.core.event('pause')
        r=self.core.event('user',text='продолжим')
        self.assertFalse(r['accepted'])
        self.assertEqual(r['status'],'PAUSED')
        self.assertEqual(r['revision'],p['revision'])

    def test_retired_donation_actions_are_rejected_without_mutation(self):
        before = self.core.state()
        for action in ('donation', 'decision'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.core.event(action)
            self.assertEqual(self.core.state(), before)

    def test_revision_is_monotonic(self):
        first = self.core.state()['revision']
        turn = self.claim()
        self.assertGreater(turn['revision'], first)
        done = self.core.event('complete', agent=turn['agent'], ticket=turn['ticket'], text='Готово')
        self.assertGreater(done['revision'], turn['revision'])
        donation = self.core.event('priority_donation', agent=2)
        self.assertTrue(donation['accepted'])
        self.assertGreater(donation['revision'], done['revision'])

    def test_stop_reset_guards(self):
        self.core.event('reset')
        before=self.core.state()['revision']
        self.assertFalse(self.core.event('reset')['accepted'])
        self.assertFalse(self.core.event('stop')['accepted'])
        self.assertEqual(self.core.state()['revision'],before)

    def test_limit_overrides_model_wait(self):
        self.core.event('start',max_turns=1)
        c=self.claim()
        d=self.core.event('complete',agent=c['agent'],ticket=c['ticket'],text='[[WAIT_USER]]')
        self.assertEqual(d['status'],'LIMIT')
        self.assertEqual(d['timeout_ms'],0)

    def test_donation_priority_after_wait_marker(self):
        turn = self.claim()
        self.core.event('complete', agent=turn['agent'], ticket=turn['ticket'], text='[[WAIT_USER]]')
        donation = self.core.event('priority_donation', agent=2)
        self.assertTrue(donation['accepted'])
        self.assertEqual(self.claim()['agent'], 2)

    def test_social_return_ends_pair_even_after_repeated_to_markers(self):
        first = self.claim()
        self.assertEqual(first['agent'], 0)
        self.core.event('complete', agent=0, ticket=first['ticket'], text='[[TO:1]]')
        second = self.claim()
        self.assertEqual(second['agent'], 1)
        done = self.core.event('complete', agent=1, ticket=second['ticket'], text='[[TO:0]]')
        returned = self.core.event('social_return', agent=2, ticket=done['ticket'])
        self.assertTrue(returned['accepted'])
        self.assertEqual(returned['route_reason'], 'social_return')
        self.assertEqual(self.claim()['agent'], 2)

        self.core.event('complete', agent=2, ticket=self.core.state()['ticket'], text='Своя мысль.')
        donor = self.core.event('priority_donation', agent=1)
        blocked = self.core.event('social_return', agent=0, ticket=donor['ticket'])
        self.assertFalse(blocked['accepted'])
        self.assertEqual(self.claim()['agent'], 1)

    def test_addressed_agent_has_priority(self):
        s=self.claim()
        self.core.event('complete',agent=0,ticket=s['ticket'],text='Экспериментатор, предложи тест!')
        self.assertEqual(self.claim()['agent'],2)
    def test_ai_wait_marker(self):
        s=self.claim()
        d=self.core.event('complete',agent=0,ticket=s['ticket'],text='[[WAIT_USER]]')
        self.assertEqual(d['kind'],'wait')
        self.assertEqual(d['status'],'RUNNING')
        self.assertEqual(d['turns'],1)
    def test_three_passes_then_wait(self):
        for i in range(3):
            s=self.claim()
            self.assertEqual(s['agent'],i)
            d=self.core.event('complete',agent=i,ticket=s['ticket'],text='[[PASS]]')
        self.assertEqual(d['status'],'RUNNING')
        self.assertEqual(d['passes'],3)
        self.assertTrue(self.core.event('claim')['accepted'])

    def test_pause_resume_retries_same_speaker(self):
        s=self.claim()
        p=self.core.event('pause')
        self.assertEqual(p['status'],'PAUSED')
        self.assertFalse(self.core.event('claim')['accepted'])
        self.core.event('resume')
        r=self.claim()
        self.assertEqual(r['agent'],0)
        self.assertNotEqual(r['ticket'],s['ticket'])
    def test_max_turns_native(self):
        self.core.event('start',max_turns=2)
        for i in range(2):
            s=self.claim()
            d=self.core.event('complete',agent=i,ticket=s['ticket'],text='Готово!')
        self.assertEqual(d['status'],'LIMIT')
        self.assertFalse(self.core.event('claim')['accepted'])
    def test_user_input_not_false_pause(self):
        self.claim()
        s=self.core.event('user',text='В истории они сказали «стойте» и продолжили')
        self.assertEqual(s['status'],'RUNNING')
        self.assertEqual(s['kind'],'normal')
    def test_stop_after_wait_and_hard_reset(self):
        self.claim();self.core.event('user',text='стоп')
        self.assertEqual(self.core.event('stop')['status'],'STOPPED')
        self.assertFalse(self.core.event('claim')['accepted'])
        self.assertEqual(self.core.event('reset')['status'],'IDLE')
        self.assertEqual(self.core.state()['turns'],0)
if __name__=='__main__': unittest.main()
