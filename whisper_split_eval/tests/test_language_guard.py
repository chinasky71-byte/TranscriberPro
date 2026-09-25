"""
Test CPU: lo split per frasi nel motore agisce SOLO per l'inglese (unica lingua
misurata). Con lingua diversa, assente o vuota il risultato e' identico allo
split originale, anche con l'opzione accesa.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EVAL))

import common as C  # noqa: E402
import test_support as TS  # noqa: E402

ORIG = C.orig_split_mod().orig_split


def sentence_segment():
    # Due frasi con pausa: il nuovo split le separa, l'originale no (testo corto, 5,5 s < limiti).
    toks = [(0.0, 0.4, ' We'), (0.4, 0.8, ' need'), (0.8, 1.2, ' to'), (1.2, 1.6, ' go.'),
            (3.0, 3.4, ' It'), (3.4, 3.8, ' is'), (3.8, 4.2, ' late'), (4.2, 4.6, ' now'), (4.6, 5.0, ' and'),
            (5.0, 5.4, ' cold'), (5.4, 5.8, ' out'), (5.8, 6.4, ' here.'), (7.0, 7.4, ' Move'), (7.4, 8.0, ' fast.')]
    words = [{'start': s, 'end': e, 'word': w} for s, e, w in toks]
    return {'start': 0.0, 'end': 8.0, 'text': ''.join(w['word'] for w in words).strip(), 'words': words}


class TestLanguageGuard(unittest.TestCase):
    def test_english_uses_new_split(self):
        seg = sentence_segment()
        on = TS.engine_method(True, lang='en')(seg)
        self.assertNotEqual(on, ORIG(seg))
        self.assertGreater(len(on), 1)

    def test_three_letter_english_code(self):
        seg = sentence_segment()
        self.assertEqual(TS.engine_method(True, lang='eng')(seg), TS.engine_method(True, lang='en')(seg))

    def test_other_languages_use_original(self):
        seg = sentence_segment()
        for lang in ('it', 'fr', 'de', 'es', 'ja', 'zh', '', None, 'IT'):
            self.assertEqual(TS.engine_method(True, lang=lang)(seg), ORIG(seg), lang)

    def test_option_off_is_original_even_in_english(self):
        seg = sentence_segment()
        self.assertEqual(TS.engine_method(False, lang='en')(seg), ORIG(seg))
        self.assertEqual(TS.engine_method(None, lang='en')(seg), ORIG(seg))


if __name__ == '__main__':
    unittest.main()
