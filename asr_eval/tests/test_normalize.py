import unittest

import _common  # noqa: F401
import normalize as nz


class TestNumbers(unittest.TestCase):
    def test_en_cardinal_year_ordinal(self):
        self.assertEqual(nz.en_cardinal(0), 'zero')
        self.assertEqual(nz.en_cardinal(1234), 'one thousand two hundred thirty four')
        self.assertEqual(nz.en_cardinal(9999), 'nine thousand nine hundred ninety nine')
        self.assertEqual(nz.en_year(1995), 'nineteen ninety five')
        self.assertEqual(nz.en_year(2005), 'two thousand five')
        self.assertEqual(nz.en_year(1905), 'nineteen oh five')
        self.assertEqual(nz.en_ordinal(21), 'twenty first')
        self.assertEqual(nz.en_ordinal(40), 'fortieth')

    def test_it_cardinal(self):
        cases = {1: 'uno', 21: 'ventuno', 23: 'ventitre', 28: 'ventotto', 101: 'centouno',
                 180: 'centottanta', 1000: 'mille', 1200: 'milleduecento', 2024: 'duemilaventiquattro',
                 3333: 'tremilatrecentotrentatre'}
        for n, w in cases.items():
            self.assertEqual(nz.it_cardinal(n), w, n)

    def test_digits_in_text(self):
        self.assertEqual(nz.normalize_text("It's 1995.", 'en'), ['it', 'is', 'nineteen', 'ninety', 'five'])
        self.assertEqual(nz.normalize_text("Ho 23 anni e 1.500 euro", 'it'),
                         ['ho', 'ventitre', 'anni', 'e', 'millecinquecento', 'euro'])
        self.assertEqual(nz.normalize_text("alle 10:30, il 3,5%", 'it'),
                         ['alle', 'dieci', 'trenta', 'il', 'tre', 'virgola', 'cinque', 'per', 'cento'])
        self.assertEqual(nz.normalize_text("$5 and 1,000", 'en'), ['five', 'dollars', 'and', 'one', 'thousand'])
        self.assertEqual(nz.normalize_text("ventitré", 'it'), nz.normalize_text("23", 'it'))


class TestText(unittest.TestCase):
    def test_contractions(self):
        self.assertEqual(nz.normalize_text("I don't wanna, we're gonna", 'en'),
                         ['i', 'do', 'not', 'want', 'to', 'we', 'are', 'going', 'to'])
        self.assertEqual(nz.normalize_text("OK, o.k.", 'en'), ['okay', 'okay'])
        self.assertEqual(nz.normalize_text("can't won't", 'en'), ['can', 'not', 'will', 'not'])

    def test_apostrophe_and_accents(self):
        self.assertEqual(nz.normalize_text("L'uomo è qui, perche' più", 'it'),
                         ['l', 'uomo', 'e', 'qui', 'perche', 'piu'])
        self.assertEqual(nz.normalize_text("E' così", 'it'), nz.normalize_text("È così", 'it'))

    def test_markup_ass_brackets(self):
        self.assertEqual(nz.normalize_text("{\\an8}Non credi? <i>Sì</i> [ride] (sospira)", 'it'),
                         ['non', 'credi', 'si'])
        self.assertEqual(nz.normalize_text("(unclosed paren\nnext line fine", 'it'), ['next', 'line', 'fine'])

    def test_speaker_and_dashes(self):
        self.assertEqual(nz.normalize_text("- JOHN: Hello there\n- Mike: well-known", 'en'),
                         ['hello', 'there', 'well', 'known'])
        self.assertEqual(nz.normalize_text("Time: 10:30", 'en'), ['ten', 'thirty'])

    def test_fillers_collapse(self):
        toks = 'uh i i i think um so so'.split()
        kept = [toks[i] for i in nz.filter_fillers_collapse(toks, 'en')]
        self.assertEqual(kept, ['i', 'think', 'so'])
        toks = 'ehm io io vado mh'.split()
        self.assertEqual([toks[i] for i in nz.filter_fillers_collapse(toks, 'it')], ['io', 'vado'])

    def test_line_words_keep_source_index(self):
        out = nz.normalize_line_words(['[Music]', ' Hello', "don't", '(laughs)', 'go.'], 'en')
        self.assertEqual(out, [('hello', 1), ('do', 2), ('not', 2), ('go', 4)])

    def test_phantoms_and_numbers(self):
        toks = nz.normalize_text("Thanks for watching!", 'en')
        self.assertEqual(nz.find_phantoms(toks, 'en'), [(0, 3, 'thanks for watching')])
        self.assertTrue(nz.is_number_token('ventitre', 'it'))
        self.assertTrue(nz.is_number_token('twenty', 'en'))
        self.assertFalse(nz.is_number_token('one', 'en'))
        self.assertFalse(nz.is_number_token('settembre', 'it'))


if __name__ == '__main__':
    unittest.main()
