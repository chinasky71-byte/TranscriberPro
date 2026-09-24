"""Test CPU del foglio cieco e del conteggio (nessun modello, nessuna rete)."""
import random
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import decision_rule as R  # noqa: E402
import sheet_lib as L  # noqa: E402

SRC = """1
00:00:10,000 --> 00:00:12,000
After all, Dad tried to send her

2
00:00:12,200 --> 00:00:14,000
husband to jail.

3
00:00:20,000 --> 00:00:22,000
Good morning.

4
00:00:30,000 --> 00:00:32,000
We need to talk about

5
00:00:32,100 --> 00:00:34,000
the money you owe me.
"""


def make(text_map, path):
    blocks = SRC.strip().split('\n\n')
    out = []
    for b in blocks:
        lines = b.split('\n')
        idx = lines[0]
        out.append('\n'.join([idx, lines[1], text_map[idx]]))
    Path(path).write_text('\n\n'.join(out) + '\n', encoding='utf-8')


class TestBlind(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        (self.td / 'src.srt').write_text(SRC, encoding='utf-8')
        make({'1': "Dopotutto, papa' ha provato a mandarla", '2': "marito in prigione.", '3': "Buongiorno.",
              '4': "Dobbiamo parlare dei", '5': "soldi che mi devi."}, self.td / 'base.srt')
        make({'1': "Dopotutto, papa' ha provato a mandare", '2': "suo marito in prigione.", '3': "Buongiorno.",
              '4': "Dobbiamo parlare dei soldi", '5': "che devi a me."}, self.td / 'ric.srt')
        self.SR = L.load_recompose()
        self.meta = {'id': '01-x', 'title': 'Film X', 'excerpt_start_s': 600}

    def pairs(self):
        return L.build_pairs(self.SR, self.td / 'src.srt', self.td / 'base.srt', self.td / 'ric.srt',
                             self.meta, random.Random(1), 15)

    def test_pairs_only_merged_and_different(self):
        ps = self.pairs()
        self.assertEqual(len(ps), 2)
        self.assertTrue(all(' / ' in p['en'] for p in ps))
        self.assertEqual(ps[0]['time'][:2], '0:')        # 600 s di estratto + 10 s
        self.assertTrue(all(p['prev'] != p['en'] for p in ps))

    def test_same_words_different_cut_is_skipped(self):
        make({'1': "Dopotutto, papa' ha provato a mandarla", '2': "marito in prigione.", '3': "Buongiorno.",
              '4': "Dobbiamo parlare dei soldi", '5': "che mi devi."}, self.td / 'ric.srt')
        make({'1': "Dopotutto, papa' ha provato a mandarla", '2': "marito in prigione.", '3': "Buongiorno.",
              '4': "Dobbiamo parlare dei", '5': "soldi che mi devi."}, self.td / 'base.srt')
        self.assertEqual(self.pairs(), [])

    def test_identical_translations_are_skipped(self):
        (self.td / 'ric.srt').write_text((self.td / 'base.srt').read_text(encoding='utf-8'), encoding='utf-8')
        self.assertEqual(self.pairs(), [])

    def test_block_count_mismatch_raises(self):
        (self.td / 'ric.srt').write_text("1\n00:00:10,000 --> 00:00:12,000\nX\n", encoding='utf-8')
        with self.assertRaises(ValueError):
            self.pairs()

    def test_assemble_blinding_is_balanced_and_deterministic(self):
        many = [{'file': 'f', 'title': 't', 'time': '0:00:01', 'prev': '', 'en': 'e', 'next': '',
                 'base': f"b{i}", 'ric': f"r{i}"} for i in range(200)]
        p1, m1 = L.assemble({'f': many}, 7, 100)
        p2, m2 = L.assemble({'f': many}, 7, 100)
        self.assertEqual(m1, m2)
        self.assertEqual(len(p1), 100)
        a_ric = sum(1 for m in m1.values() if m['A'] == 'ricomposta')
        self.assertTrue(30 < a_ric < 70, a_ric)
        for p in p1:
            self.assertEqual(m1[p['id']][ 'A'] == 'ricomposta', p['A'].startswith('r'))

    def test_render_lot_hides_labels(self):
        p, m = L.assemble({'f': [{'file': 'f', 'title': 'Titolo', 'time': '0:01:02', 'prev': 'p', 'en': 'e',
                                  'next': 'n', 'base': 'BASE', 'ric': 'RIC'}]}, 1, 10)
        txt = L.render_lot(p, 1, 1)
        self.assertNotIn('ricomposta', txt.split('---', 1)[1].lower())
        self.assertIn('[P001]', txt)

    def test_parse_judgments(self):
        j, errs = L.parse_judgments("# c\nP001|A|\nP002|b|a\nP003|pari|\nP004||\nfoo\nP005|X|\n")
        self.assertEqual(j, {'P001': ('A', ''), 'P002': ('B', 'a'), 'P003': ('P', '')})
        self.assertEqual(len(errs), 2)

    def mapping(self, n, ric_is_a):
        return {f"P{i:03d}": {'A': 'ricomposta' if ric_is_a(i) else 'base',
                              'B': 'base' if ric_is_a(i) else 'ricomposta', 'file': f"f{i % 6}"} for i in range(1, n + 1)}

    def test_tally_promote(self):
        m = self.mapping(100, lambda i: i % 2 == 0)
        j = {f"P{i:03d}": (('A' if m[f"P{i:03d}"]['A'] == 'ricomposta' else 'B') if i <= 78 else
                           ('A' if m[f"P{i:03d}"]['A'] == 'base' else 'B'), '') for i in range(1, 101)}
        r = L.tally(m, j)
        self.assertEqual(r['verdict'], 'PROMUOVI', r)
        self.assertEqual(r['ricomposta'], 78)

    def test_tally_defects_block_promotion(self):
        m = self.mapping(100, lambda i: True)                    # A = ricomposta sempre
        j = {f"P{i:03d}": ('A', 'a' if i <= 5 else '') for i in range(1, 101)}
        r = L.tally(m, j)
        self.assertEqual(r['defects_ricomposta'], 5)
        self.assertEqual(r['verdict'], 'ARCHIVIA')
        self.assertTrue(any('difetti' in x for x in r['reasons']))

    def test_tally_insufficient_and_archive(self):
        m = self.mapping(100, lambda i: True)
        few = {f"P{i:03d}": ('A', '') for i in range(1, 30)}
        self.assertEqual(L.tally(m, few)['verdict'], 'INSUFFICIENTE')
        coin = {f"P{i:03d}": ('A' if i % 2 else 'B', '') for i in range(1, 101)}
        self.assertEqual(L.tally(m, coin)['verdict'], 'ARCHIVIA')

    def test_binomial(self):
        self.assertAlmostEqual(L.binom_upper(10, 8), 56 / 1024)
        self.assertEqual(L.binom_upper(0, 0), 1.0)

    def test_rule_module_is_frozen_shape(self):
        self.assertEqual(R.FROZEN_ON, '2026-09-25')
        self.assertLessEqual(R.N_FILMS, len(R.FILMS_FROM))


if __name__ == '__main__':
    unittest.main()
