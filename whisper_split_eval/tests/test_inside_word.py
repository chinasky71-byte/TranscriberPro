"""
Test CPU: core/whisper_sentence_split.py non taglia MAI dentro una parola
(token senza spazio iniziale), anche quando i limiti duri lo costringerebbero
e anche quando la maggioranza dei token e' attaccata (caso reale "Boop-a-doop-a"
di I'm Not Rappaport, 1996, ~4628,5 s: prima si ricadeva sullo split originale,
che produceva 'Boop' | '-a-doop-a. Boop-a' | '-doop -a.').

Esecuzione:
  cd whisper_split_eval\\tests
  set PYTHONIOENCODING=utf-8 & ..\\..\\venv\\Scripts\\python.exe -m unittest discover -p "test_*.py" -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path.insert(0, str(EVAL))

import common as C  # noqa: E402
import test_support as TS  # noqa: E402

NS = TS.real_new_module()
ORIG = C.orig_split_mod().orig_split
RAPPAPORT = EVAL / 'work_full_runs' / 'raw' / '02-i-m-not-rappaport-1996.json'


def seg_from_tokens(toks):
    """toks: lista di (start, end, word) con lo spazio iniziale gia' nel word."""
    words = [{'start': s, 'end': e, 'word': w} for s, e, w in toks]
    return {'start': words[0]['start'], 'end': words[-1]['end'],
            'text': ''.join(w['word'] for w in words).strip(), 'words': words}


def boop_segment():
    """Copia sintetica fedele del segmento reale (27 token, 15 senza spazio)."""
    toks = [
        (0.00, 0.66, ' Trying'), (0.66, 1.18, ' mighty'), (1.18, 1.82, ' hard'),
        (1.82, 2.52, ' to'), (2.52, 3.00, ' sound'), (3.00, 3.50, ' like'), (3.50, 4.50, ' Gary.'),
        (5.62, 6.66, ' Boop'), (6.66, 7.04, '-a'), (7.04, 7.26, '-doop'), (7.26, 7.26, '-a.'),
        (7.26, 8.10, ' Boop'), (8.10, 8.12, '-a'), (8.12, 8.34, '-doop'), (8.34, 8.78, '-a.'),
        (8.92, 9.96, ' Boop'), (9.96, 10.16, '-a'), (10.16, 10.22, '-doop'), (10.22, 10.22, '-a.'),
        (10.22, 11.20, ' Boop'), (12.71, 12.93, '-a'), (12.93, 13.19, '-doop'), (13.19, 13.43, '-a.'),
        (14.37, 15.41, ' Boop'), (15.41, 16.49, '-a'), (16.52, 23.82, '-doop'), (23.82, 24.34, '-a.'),
    ]
    return seg_from_tokens(toks)


def whole_words(piece):
    return 1 + sum(1 for w in piece['words'][1:] if w['word'][:1].isspace())


class NoInsideCutMixin:
    def assert_no_inside_cut(self, seg, pieces):
        self.assertIsNotNone(pieces)
        self.assertTrue(NS.validate_split(seg, pieces))
        flat = [w for p in pieces for w in p['words']]
        self.assertEqual(len(flat), len(seg['words']))
        for a, b in zip(flat, seg['words']):
            self.assertIs(a, b)
        for p in pieces[1:]:
            self.assertTrue(p['words'][0]['word'][:1].isspace(), [q['text'] for q in pieces])
        # nessuno spazio inserito dentro una parola: unire i pezzi con uno
        # spazio ridà esattamente il testo del segmento
        self.assertEqual(' '.join(p['text'] for p in pieces), seg['text'])
        # vincoli duri: superabili solo da un pezzo di UNA parola intera
        for p in pieces:
            if len(p['text']) > 84 or p['end'] - p['start'] > 9.0 + 1e-9:
                self.assertEqual(whole_words(p), 1, p['text'])


class TestBoop(NoInsideCutMixin, unittest.TestCase):
    def test_boop_synthetic_new_split(self):
        seg = boop_segment()
        # precondizione: e' il caso che prima ricadeva sullo split originale
        n_nospace = sum(1 for w in seg['words'][1:] if not w['word'][:1].isspace())
        self.assertGreater(n_nospace * 2, len(seg['words']) - 1)
        self.assertTrue(any(not p['words'][0]['word'][:1].isspace() for p in ORIG(seg)[1:]))
        pieces = NS.sentence_aware_split(seg)
        self.assert_no_inside_cut(seg, pieces)
        self.assertEqual(pieces[0]['text'], 'Trying mighty hard to sound like Gary.')
        for p in pieces[1:]:
            self.assertRegex(p['text'], r'^(Boop-a-doop-a\. ?)+$')
        # l'ultima parola dura 9,97 s: resta intera, da sola
        self.assertEqual(pieces[-1]['text'], 'Boop-a-doop-a.')

    def test_boop_engine_hook(self):
        seg = boop_segment()
        on = TS.engine_method(True)(seg)
        self.assert_no_inside_cut(seg, on)
        self.assertEqual(on, NS.sentence_aware_split(seg))
        self.assertEqual(TS.engine_method(False)(seg), ORIG(seg))   # opzione spenta: invariato

    def test_boop_real_segment(self):
        if not RAPPAPORT.exists():
            self.skipTest('dati reali non disponibili')
        segs = json.loads(RAPPAPORT.read_text(encoding='utf-8'))['segments']
        seg = next(s for s in segs if abs(s['start'] - 4628.5) < 0.01)
        self.assert_no_inside_cut(seg, NS.sentence_aware_split(seg))


class TestFallbackLimits(NoInsideCutMixin, unittest.TestCase):
    """Il ripiego sui limiti di lunghezza/durata non taglia dentro le parole."""

    def test_duration_limit_moves_cut_to_word_boundary(self):
        # regressione (non discriminante: anche la versione a token la
        # passava, un'alternativa fra parole c'era): parole a passo 0,5 s,
        # "fuck" + "-ton" vicino al punto in cui i 9 s obbligano a tagliare.
        # Il taglio dentro parola e' FORZATO solo se la parola intera supera i
        # limiti: casi coperti dai due test seguenti.
        toks, t = [], 0.0
        text = ('I happen to know a whole lot about it and I will tell you all of it '
                'right here in front of everybody so that nobody can say fuck -ton of '
                'things were never said in this room tonight')
        for w in text.split():
            toks.append((round(t, 2), round(t + 0.45, 2), (w if w.startswith('-') else ' ' + w)))
            t += 0.5
        seg = seg_from_tokens(toks)
        pieces = NS.sentence_aware_split(seg)
        self.assert_no_inside_cut(seg, pieces)
        self.assertTrue(any('fuck-ton' in p['text'] for p in pieces))

    def test_word_longer_than_hard_chars_kept_whole(self):
        # parola composta di 3 token attaccati, 101 caratteri: > 84
        giant = [(1.0, 1.5, ' ' + 'x' * 50), (1.5, 2.0, '-' + 'y' * 30), (2.0, 2.5, '-' + 'z' * 18)]
        toks = [(0.0, 0.5, ' Look'), (0.5, 0.9, ' at')] + giant + [
            (2.6, 3.0, ' and'), (3.0, 3.4, ' then'), (3.4, 3.8, ' go'), (3.8, 4.2, ' home.')]
        seg = seg_from_tokens(toks)
        pieces = NS.sentence_aware_split(seg)
        self.assert_no_inside_cut(seg, pieces)
        big = [p for p in pieces if 'x' * 50 in p['text']]
        self.assertEqual(len(big), 1)
        self.assertIn('y' * 30 + '-' + 'z' * 18, big[0]['text'])
        self.assertEqual(whole_words(big[0]), 1)

    def test_word_longer_than_hard_duration_kept_whole(self):
        toks = [(0.0, 0.5, ' So'), (0.5, 1.0, ' she'), (1.0, 1.5, ' said'),
                (1.6, 2.0, ' Mm'), (2.0, 12.0, '-hmm.'),          # 10,4 s
                (12.2, 12.6, ' And'), (12.6, 13.0, ' then'), (13.0, 13.4, ' she'), (13.4, 13.8, ' left'),
                (13.8, 14.2, ' the'), (14.2, 14.6, ' house'), (14.6, 15.0, ' forever.')]
        seg = seg_from_tokens(toks)
        pieces = NS.sentence_aware_split(seg)
        self.assert_no_inside_cut(seg, pieces)
        self.assertTrue(any('Mm-hmm.' in p['text'] for p in pieces))

    def test_leading_nospace_first_token_is_not_a_cut(self):
        toks = [(0.0, 0.4, '-and')] + [(0.4 + 0.3 * i, 0.65 + 0.3 * i, ' w%d' % i) for i in range(40)]
        seg = seg_from_tokens(toks)
        pieces = NS.sentence_aware_split(seg)
        self.assert_no_inside_cut(seg, pieces)


class TestGuards(unittest.TestCase):
    def test_cjk_segment_still_uses_original(self):
        # faster-whisper zh/ja: un token per carattere, senza spazi -> None
        chars = '我们今天晚上不能留在这里。暴风雨要来了，午夜之前道路就会封闭。我们必须现在就走，趁天还没黑。' * 2
        toks = [(0.2 * i, 0.2 * i + 0.18, ch) for i, ch in enumerate(chars)]
        seg = seg_from_tokens(toks)
        self.assertIsNone(NS.sentence_aware_split(seg))
        self.assertEqual(TS.engine_method(True)(seg), ORIG(seg))

    def test_hallucination_loop_of_attached_tokens_uses_original(self):
        # 600 token "-ha" attaccati = una "parola" da 1800 caratteri: non la
        # si tiene intera (blocco enorme) -> None, lo split originale decide
        toks = [(0.0, 0.05, ' ha')] + [(0.05 * i, 0.05 * i + 0.04, '-ha') for i in range(1, 600)]
        seg = seg_from_tokens(toks)
        self.assertIsNone(NS.sentence_aware_split(seg))
        self.assertEqual(TS.engine_method(True)(seg), ORIG(seg))
        # sotto la soglia (2 x 84) la parola resta intera
        seg2 = seg_from_tokens([(0.0, 0.3, ' Well,')] + [(0.3 + 0.1 * i, 0.38 + 0.1 * i, ' ha' if i == 0 else '-ha')
                                                          for i in range(40)]
                               + [(4.5 + 0.3 * i, 4.8 + 0.3 * i, ' w%d' % i) for i in range(25)])
        self.assertIsNotNone(NS.sentence_aware_split(seg2))

    def test_italian_titles_are_abbreviations(self):
        for w in ('Sig.', 'Dott.', 'Avv.', 'Ing.'):
            self.assertEqual(NS.boundary_type(' ' + w, ' Rossi'), NS.ABBREV, w)


if __name__ == '__main__':
    unittest.main()
