"""
Test CPU SENZA fixture di dialoghi reali: la guardia di lingua del motore (lista `whisper_split_sentence_langs`
in tutte le forme) e alcune regole di confine italiane che i test con dati reali non coprono.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EVAL))

import common as C  # noqa: E402
import test_support as TS  # noqa: E402
from test_language_guard import sentence_segment  # noqa: E402

NS = TS.real_new_module()
ORIG = C.orig_split_mod().orig_split


def cfg(langs, aware=True):
    settings = {'whisper_split_sentence_aware': aware}
    if langs != 'ASSENTE':
        settings['whisper_split_sentence_langs'] = langs
    return TS.FakeConfig(settings)


class TestLangList(unittest.TestCase):
    def new_used(self, langs, lang):
        seg = sentence_segment()
        out = TS.engine_method(True, config=cfg(langs), lang=lang)(seg)
        if out == ORIG(seg):
            return False
        return True

    def test_forms_that_enable_italian(self):
        for langs in (['en', 'it'], ['it'], 'it', 'en,it', 'it,en', ' it', 'IT', ['ita'], ('en', 'it'), 'en; it', 'en it'):
            self.assertTrue(self.new_used(langs, 'it'), langs)

    def test_forms_that_keep_italian_on_original(self):
        for langs in (['en'], 'en', None, [], '', 'ASSENTE', 5, {'x': 1}):
            self.assertFalse(self.new_used(langs, 'it'), langs)

    def test_english_follows_the_list_too(self):
        self.assertTrue(self.new_used(['en'], 'en'))
        self.assertTrue(self.new_used('it,en', 'en'))
        self.assertTrue(self.new_used(None, 'en'))          # None = default ['en']
        self.assertTrue(self.new_used('ASSENTE', 'en'))     # chiave assente = default ['en']
        self.assertFalse(self.new_used(['it'], 'en'))       # lista solo italiana: inglese spento
        self.assertFalse(self.new_used(5, 'en'))            # tipo non valido = lista vuota
        self.assertFalse(self.new_used([], 'en'))

    def test_option_off_never_uses_new_split(self):
        seg = sentence_segment()
        for langs in (['en', 'it'], 'ASSENTE'):
            for lang in ('en', 'it'):
                self.assertEqual(TS.engine_method(True, config=cfg(langs, aware=False), lang=lang)(seg), ORIG(seg))


class TestBoundaryItExtra(unittest.TestCase):
    def test_semicolon_and_colon_are_clause(self):
        self.assertEqual(NS.boundary_type(' cosa:', ' Poi', 'it'), NS.CLAUSE)
        self.assertEqual(NS.boundary_type(' cosa;', ' poi', 'it'), NS.CLAUSE)

    def test_dotted_acronym_is_abbreviation(self):
        self.assertEqual(NS.boundary_type(' U.S.A.', ' e', 'it'), NS.ABBREV)

    def test_capital_initial_before_abbreviation_list(self):
        # "N." maiuscolo e' una lettera (fine frase incerta), "n." minuscolo e' l'abbreviazione di numero
        self.assertEqual(NS.boundary_type(' N.', ' Poi', 'it'), NS.SENT_WEAK)
        self.assertEqual(NS.boundary_type(' O.', ' Poi', 'it'), NS.SENT_WEAK)
        self.assertEqual(NS.boundary_type(' n.', ' 3', 'it'), NS.ABBREV)


if __name__ == '__main__':
    unittest.main()
