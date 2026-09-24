import sys
import types
import unittest

import _common
from _common import blk
from split_eval import midcut as M


class TestPieces(unittest.TestCase):
    def test_sentence_end(self):
        for t in ('Done.', 'Really?', 'Stop!', 'Wait…', 'Wait...', '"Go home."', "She said 'no.'", 'Ok.)', 'Fine.»'):
            self.assertTrue(M.ends_sentence(t), t)
        for t in ('After all, Dad tried to send her', 'Well,', 'I think that', 'He said "yes"', 'but--'):
            self.assertFalse(M.ends_sentence(t), t)
        self.assertTrue(M.ends_ellipsis('and then...'))
        self.assertTrue(M.ends_ellipsis('e poi…'))
        self.assertFalse(M.ends_ellipsis('Done.'))

    def test_continuation_en(self):
        self.assertEqual(M.continuation_kind('husband to jail.', 'en'), 'lower')
        self.assertEqual(M.continuation_kind('And then we left.', 'en'), 'word')
        self.assertEqual(M.continuation_kind('The man who came.', 'en'), 'word')
        self.assertEqual(M.continuation_kind('20 dollars a night.', 'en'), 'digit')
        self.assertEqual(M.continuation_kind('"and he said"', 'en'), 'lower')
        self.assertEqual(M.continuation_kind('...and so on', 'en'), 'lower')
        self.assertIsNone(M.continuation_kind('I will crush you.', 'en'))
        self.assertIsNone(M.continuation_kind('Larry?', 'en'))
        self.assertIsNone(M.continuation_kind('- and you?', 'en'))      # trattino = cambio parlante

    def test_continuation_it(self):
        self.assertEqual(M.continuation_kind('marito in prigione.', 'it'), 'lower')
        self.assertEqual(M.continuation_kind('E poi se ne andò.', 'it'), 'word')
        self.assertEqual(M.continuation_kind('Della casa non so nulla.', 'it'), 'word')
        self.assertEqual(M.continuation_kind("L'uomo che hai visto.", 'it'), 'word')
        self.assertEqual(M.continuation_kind('Perché non vieni?', 'it'), 'word')
        self.assertIsNone(M.continuation_kind('È tardi.', 'it'))           # accento: non e' la congiunzione "e"
        self.assertIsNone(M.continuation_kind('Marco, vieni qui.', 'it'))
        self.assertEqual(M.first_word("dell'albero"), "dell'")

    def test_clean_lines(self):
        self.assertEqual(M.clean_lines('<i>Hello</i> there'), ['Hello there'])
        self.assertEqual(M.clean_lines('JOHN: where is it'), ['where is it'])
        self.assertEqual(M.clean_lines('[DOOR SLAMS]\nand then'), ['and then'])
        self.assertEqual(M.clean_lines('(SIGHS) fine'), ['fine'])
        self.assertEqual(M.clean_lines('he said (quietly) no'), ['he said (quietly) no'])
        self.assertTrue(M.is_music('♪ la la ♪'))
        self.assertTrue(M.is_dialogue_block('- Hi.\n- Hello.'))
        self.assertFalse(M.is_dialogue_block('Hi there,\nhow are you?'))

    def test_pair_kind(self):
        self.assertEqual(M.pair_kind('Dad tried to send her', 'husband to jail.', 0.1, 'en'), 'midcut')
        self.assertIsNone(M.pair_kind('Dad tried to send her', 'husband to jail.', 1.0, 'en'))   # gap >= 1 s
        self.assertIsNone(M.pair_kind('Dad tried to send her', '♪ husband ♪', 0.1, 'en'))
        self.assertIsNone(M.pair_kind('Hi.', 'and you', 0.1, 'en'))
        self.assertEqual(M.pair_kind('I was going...', 'to the store.', 0.1, 'en'), 'ellipsis')
        self.assertEqual(M.pair_kind('If you are late,', 'I will crush you.', 0.1, 'en'), 'softend')
        self.assertIsNone(M.pair_kind('Where are you', '- Here.', 0.1, 'en'))

    def test_stats_small(self):
        bl = [blk(0, 1, 'Dad tried to send her'), blk(1.1, 2, 'husband to jail.'),
              blk(2.2, 3, 'I was going...'), blk(3.1, 4, 'to the store.'),
              blk(4.2, 5, '♪ la la ♪'), blk(5.1, 6, 'and then'), blk(9, 10, 'nobody came')]
        st = M.midcut_stats(bl, 'en')
        self.assertEqual(st['n_blocks'], 6)                     # musica esclusa dal denominatore
        self.assertEqual(st['n_midcut'], 1)
        self.assertEqual(st['n_ellipsis_cont'], 1)
        self.assertEqual(st['n_noend'], 3)                      # 'Dad...', 'and then', 'nobody came'
        self.assertAlmostEqual(st['rate'], 1 / 6)
        self.assertEqual(M.midcut_stats([], 'en')['rate'], None)
        # chiavi s/e (battute di windows.jsonl) come start/end
        st2 = M.midcut_stats([{'s': 0, 'e': 1, 'text': 'send her'}, {'s': 1.2, 'e': 2, 'text': 'home.'}], 'en')
        self.assertEqual(st2['n_midcut'], 1)


@unittest.skipUnless((_common.REAL_SUBS / '10.srt').exists(), "sub reali di Office Romance assenti")
class TestRealSubs(unittest.TestCase):
    def rate(self, idx, lang):
        bl = M.srt_blocks((_common.REAL_SUBS / f'{idx}.srt').read_text(encoding='utf-8', errors='replace'))
        return M.midcut_stats(bl, lang)

    def test_english_professional(self):
        st = self.rate(10, 'en')
        self.assertEqual((st['n_midcut'], st['n_blocks']), (136, 1914))   # blocco di regressione
        self.assertTrue(0.05 <= st['rate'] <= 0.10, st)

    def test_italian_professional(self):
        st = self.rate(23, 'it')
        self.assertTrue(0.04 <= st['rate'] <= 0.10, st)


class TestFormatterBlocks(unittest.TestCase):
    SEGS = [{'start': 0.0, 'end': 2.0, 'text': 'After all, Dad tried to send her', 'words': []},
            {'start': 2.05, 'end': 3.2, 'text': 'husband to jail.', 'words': []},
            {'start': 5.0, 'end': 6.0, 'text': 'Whatever.', 'words': []}]

    def test_no_torch_and_fake_core(self):
        saved = sys.modules.get('core')
        sys.modules['core'] = types.ModuleType('core')          # come fa asr_eval/tests/test_flow_fake
        try:
            bl = M.formatter_blocks(self.SEGS)
        finally:
            if saved is None:
                sys.modules.pop('core', None)
            else:
                sys.modules['core'] = saved
        self.assertNotIn('torch', sys.modules)
        # gap 0,05 s senza punteggiatura finale: il formatter li unisce gia' (MERGE_GAP)
        # righe divise dal _wrap_cpl REALE del formatter (taglio vicino alla meta')
        self.assertEqual(bl[0]['text'], 'After all, Dad tried to\nsend her husband to jail.')
        self.assertEqual(len(bl), 2)


if __name__ == '__main__':
    unittest.main()
