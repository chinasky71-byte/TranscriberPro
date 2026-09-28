"""
Test CPU delle regole FRANCESI di core/whisper_sentence_split.py (lang='fr'), scritte a priori il 28/09/2026
(piano_split_frasi_fr_de) prima dei dati di taratura. Solo esempi sintetici: nessun dialogo reale.

Esecuzione:
  cd whisper_split_eval\\tests
  set PYTHONIOENCODING=utf-8 & ..\\..\\venv\\Scripts\\python.exe -m unittest test_french -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EVAL))

import test_support as TS  # noqa: E402

NS = TS.real_new_module()


def bt(w, n):
    return NS.boundary_type(w, n, 'fr')


def seg(toks):
    words = [{'start': s, 'end': e, 'word': w} for s, e, w in toks]
    return {'start': words[0]['start'], 'end': words[-1]['end'],
            'text': ''.join(w['word'] for w in words).strip(), 'words': words}


class TestBoundaryFr(unittest.TestCase):
    def test_sentence_end(self):
        self.assertEqual(bt(' vacances.', ' Tu'), NS.SENT)
        self.assertEqual(bt(' passé?', ' Je'), NS.SENT)
        self.assertEqual(bt(' vrai!', ' Allez'), NS.SENT)
        self.assertEqual(bt(' sais...', ' mais'), NS.SENT_WEAK)

    def test_spaced_punctuation_never_cut_before(self):
        # tipografia francese: " ?" / " !" / " :" / " »" sono token staccati
        for p in (' ?', ' !', ' :', ' ;', ' »', ' ?!'):
            self.assertEqual(bt(' passé', p), NS.INSIDE, p)
        self.assertEqual(bt(' ?', ' Je'), NS.SENT)

    def test_abbreviations(self):
        self.assertEqual(bt(' M.', ' Dupont'), NS.ABBREV)
        self.assertEqual(bt(' Mme.', ' Martin'), NS.ABBREV)
        self.assertEqual(bt(' Dr.', ' House'), NS.ABBREV)
        self.assertEqual(bt(' etc.', ' et'), NS.ABBREV)
        self.assertEqual(bt(' etc.', ' Bon'), NS.SENT_WEAK)
        self.assertEqual(bt(' B.', ' On'), NS.SENT_WEAK)          # "le plan B. On"

    def test_function_words(self):
        for w in (' le', ' la', ' les', ' une', ' du', ' de', ' au', ' dans', ' pour', ' avec',
                  ' je', ' tu', ' il', ' nous', ' ne', ' mon', ' ce', ' est', ' suis', ' ai', ' très'):
            self.assertEqual(bt(w, ' truc'), NS.FUNC, w)

    def test_elision_is_one_token(self):
        # "l'homme", "qu'il": un solo token con spazio iniziale -> nessun taglio possibile dopo l'apostrofo
        self.assertEqual(bt(' parce', " qu'il"), NS.FUNC)          # locuzione "parce qu'il"
        self.assertEqual(bt(' fatigué', " qu'il"), NS.CONJ)
        self.assertEqual(bt(' homme', " lorsqu'il"), NS.CONJ)

    def test_conjunction_glue(self):
        self.assertEqual(bt(' alors', ' que'), NS.FUNC)
        self.assertEqual(bt(' même', ' si'), NS.FUNC)
        self.assertEqual(bt(' bien', ' que'), NS.FUNC)
        self.assertEqual(bt(' maison', ' et'), NS.CONJ)
        self.assertEqual(bt(' partir', ' mais'), NS.CONJ)

    def test_clause_and_comma(self):
        self.assertEqual(bt(' Bon,', ' on'), NS.COMMA)
        self.assertEqual(bt(' écoute;', ' on'), NS.CLAUSE)

    def test_attached_token(self):
        self.assertEqual(bt(' aujourd', "'hui"), NS.INSIDE)

    def test_three_letter_code(self):
        self.assertEqual(NS.boundary_type(' le', ' truc', 'fre'), NS.FUNC)
        self.assertEqual(NS.boundary_type(' le', ' truc', 'fra'), NS.FUNC)


class TestSplitFr(unittest.TestCase):
    def test_split_prefers_sentence_end(self):
        toks = [(0.0, 0.3, ' Laisse'), (0.3, 0.6, '-moi'), (0.6, 0.9, ' te'), (0.9, 1.3, ' prouver'),
                (1.3, 1.6, ' que'), (1.6, 1.8, ' je'), (1.8, 2.1, ' suis'), (2.1, 2.4, ' toujours'),
                (2.4, 2.7, " l'homme"), (2.7, 2.9, ' que'), (2.9, 3.1, ' tu'), (3.1, 3.5, ' aimes.'),
                (3.6, 3.9, ' Trois'), (3.9, 4.3, ' jours,'), (4.3, 4.6, " c'est"), (4.6, 4.9, ' pas'),
                (4.9, 5.2, ' grand'), (5.2, 5.6, ' chose,'), (5.6, 5.9, ' trois'), (5.9, 6.4, ' jours.'),
                (6.5, 6.9, ' Allez,'), (6.9, 7.3, " s'il"), (7.3, 7.5, ' te'), (7.5, 7.9, ' plaît.')]
        s = seg(toks)
        pieces = NS.sentence_aware_split(s, 80, 6.0, lang='fr')
        self.assertIsNotNone(pieces)
        self.assertTrue(NS.validate_split(s, pieces))
        texts = [p['text'] for p in pieces]
        self.assertTrue(texts[0].endswith('aimes.'), texts)
        self.assertFalse(any(t.endswith('Laisse-moi') for t in texts), texts)

    def test_never_cut_before_spaced_question_mark(self):
        toks = [(0.0, 0.5, ' Tu'), (0.5, 1.0, ' crois'), (1.0, 1.5, " qu'on"), (1.5, 2.0, ' parle'),
                (2.0, 2.5, ' pas'), (2.5, 3.0, ' ici'), (3.0, 3.2, ' ?'), (4.3, 4.8, ' Regarde'),
                (4.8, 5.3, '-moi'), (5.3, 5.8, ' quand'), (5.8, 6.3, ' je'), (6.3, 6.8, ' te'),
                (6.8, 7.4, ' parle'), (7.4, 7.6, ' !'), (7.7, 8.2, ' Imbécile'), (8.2, 8.4, ' !')]
        s = seg(toks)
        pieces = NS.sentence_aware_split(s, 40, 3.0, lang='fr')
        self.assertIsNotNone(pieces)
        self.assertTrue(NS.validate_split(s, pieces))
        for p in pieces:
            self.assertNotIn(p['text'][:1], '?!', [q['text'] for q in pieces])


class TestLanguageGate(unittest.TestCase):
    def test_french_off_by_default(self):
        # con la lista di default di produzione (en, it) il francese usa lo split originale
        toks = [(0.0, 0.4, ' On'), (0.4, 0.8, ' y'), (0.8, 1.2, ' va.'), (2.5, 3.0, ' Il'), (3.0, 3.5, ' est'),
                (3.5, 4.0, ' tard'), (4.0, 4.5, ' et'), (4.5, 5.0, ' il'), (5.0, 5.5, ' fait'), (5.5, 6.2, ' froid.'),
                (7.0, 7.4, ' Vite.')]
        s = seg(toks)
        import common as C
        orig = C.orig_split_mod().orig_split
        cfg = TS.FakeConfig({'whisper_split_sentence_aware': True, 'whisper_split_sentence_langs': ['en', 'it']})
        self.assertEqual(TS.engine_method(True, config=cfg, lang='fr')(s), orig(s))
        cfg_on = TS.FakeConfig({'whisper_split_sentence_aware': True, 'whisper_split_sentence_langs': ['en', 'it', 'fr']})
        self.assertNotEqual(TS.engine_method(True, config=cfg_on, lang='fr')(s), orig(s))


if __name__ == '__main__':
    unittest.main()
