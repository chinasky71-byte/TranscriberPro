"""Test CPU: un salto temporale enorme DENTRO una parola (timestamp errato di Whisper) non trascina il resto del segmento."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EVAL))

import test_support as TS  # noqa: E402

NS = TS.real_new_module()


def seg(toks):
    words = [{'start': s, 'end': e, 'word': w} for s, e, w in toks]
    return {'start': words[0]['start'], 'end': words[-1]['end'],
            'text': ''.join(w['word'] for w in words).strip(), 'words': words}


GLITCH = seg([(0.0, 0.4, ' Vedrai,'), (0.4, 0.9, ' tesoro.'), (1.0, 1.4, ' Cos'), (100.0, 100.2, "'è"),
              (100.2, 100.8, ' successo?'), (100.9, 101.4, ' Papà,'), (101.4, 102.0, ' un'), (102.0, 102.6, ' fantasma!'),
              (102.7, 103.2, ' Era'), (103.2, 103.6, ' un'), (103.6, 104.3, ' vero'), (104.3, 105.0, ' fantavivo!')])


class TestGlitch(unittest.TestCase):
    def check(self, lang):
        pieces = NS.sentence_aware_split(GLITCH, 80, 6.0, lang=lang)
        self.assertIsNotNone(pieces)
        # nessun pezzo dura piu' di 9 s e i pezzi dopo il salto iniziano al tempo vero
        self.assertTrue(all(p['end'] - p['start'] <= 9.0 for p in pieces), lang)
        self.assertTrue(any(abs(p['start'] - 100.0) < 1e-6 for p in pieces), lang)
        self.assertEqual([w['word'] for p in pieces for w in p['words']], [w['word'] for w in GLITCH['words']])
        self.assertTrue(NS.validate_split(GLITCH, pieces), lang)

    def test_glitch_is_cut_it(self):
        self.check('it')

    def test_glitch_is_cut_en(self):
        self.check('en')

    def test_moderate_gap_inside_word_is_kept_whole(self):
        # "Boop-a-doop-a": salto di 7 s dentro la parola, sotto la soglia 2 x 9 s: si resta sulla parola intera
        s = seg([(0.0, 0.5, ' Boop'), (0.5, 0.6, '-a'), (0.6, 7.9, '-doop'), (7.9, 8.4, '-a.'), (8.5, 9.0, ' Poi'),
                 (9.0, 9.5, ' basta.')])
        pieces = NS.sentence_aware_split(s, 80, 6.0, lang='en')
        for p in pieces or []:
            self.assertNotIn(p['words'][0]['word'][:1], ('-',))


if __name__ == '__main__':
    unittest.main()
