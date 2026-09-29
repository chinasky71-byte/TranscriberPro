"""
Test CPU delle regole SPAGNOLE di core/whisper_sentence_split.py (lang='es'), scritte a priori il 29/09/2026
senza dati di taratura, e di CONT_WORDS['es'] / naked_cuts.CONJ['es']. Solo esempi sintetici: nessun dialogo reale.
Lo spagnolo NON e' acceso in produzione: la guardia del motore lo lascia allo split originale finche' 'es' non
e' nella lista 'whisper_split_sentence_langs'.

Esecuzione:
  cd whisper_split_eval\\tests
  set PYTHONIOENCODING=utf-8 & ..\\..\\venv\\Scripts\\python.exe -m unittest test_spanish -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(ROOT))

import common as C  # noqa: E402
import test_support as TS  # noqa: E402
from split_eval import midcut  # noqa: E402

M = TS.real_new_module()
ORIG = C.orig_split_mod().orig_split


def es(w, n):
    return M.boundary_type(' ' + w, (' ' + n) if n is not None else None, 'es')


def make_segment(text, word_s=0.32, pauses=None):
    pauses = pauses or {}
    words, t = [], 0.0
    for i, w in enumerate(text.split()):
        words.append({'word': ' ' + w, 'start': round(t, 3), 'end': round(t + word_s, 3), 'probability': 0.9})
        t += word_s + 0.04 + pauses.get(i, 0.0)
    return {'start': words[0]['start'], 'end': words[-1]['end'],
            'text': ''.join(w['word'] for w in words), 'words': words}


def split(seg):
    pieces = M.sentence_aware_split(seg, lang='es')
    assert pieces is not None
    assert M.validate_split(seg, pieces)
    return [p['text'] for p in pieces]


def cut_pairs(texts):
    return [(a.split()[-1], b.split()[0]) for a, b in zip(texts, texts[1:])]


class TestSupportAndCodes(unittest.TestCase):
    def test_es_supported_and_codes(self):
        self.assertIn('es', M.SUPPORTED_LANGS)
        for code in ('es', 'spa', 'ES', ' spa'):
            self.assertEqual(M._norm_lang(code), 'es', code)
        self.assertIsNotNone(M.sentence_aware_split(make_segment('palabra ' * 40), lang='spa'))

    def test_midcut_lang2(self):
        self.assertEqual(midcut._lang2('spa'), 'es')
        self.assertEqual(midcut._lang2('spanish'), 'es')
        self.assertIn('¿', midcut._LEAD.pattern)
        self.assertIn('¡', midcut._LEAD.pattern)


class TestInvertedMarks(unittest.TestCase):
    def test_isolated_opening_mark_never_ends_piece(self):
        for w in ('¿', '¡', '«¿', '"¡'):
            self.assertEqual(es(w, 'Qué'), M.FUNC, w)

    def test_first_word_of_open_question(self):
        self.assertEqual(es('¿Qué', 'haces'), M.FUNC)
        self.assertEqual(es('¡Vamos', 'ya'), M.FUNC)
        self.assertEqual(es('—¿Dónde', 'estás?'), M.FUNC)

    def test_closed_question_or_exclamation(self):
        self.assertEqual(es('¿Qué?', 'No'), M.SENT)
        self.assertEqual(es('¡Vamos!', 'Rápido'), M.SENT)
        self.assertEqual(es('¿Sí?', '¿Y'), M.SENT)
        self.assertEqual(es('haces?', '¡Ven'), M.SENT)

    def test_cut_before_inverted_mark(self):
        self.assertEqual(es('casa.', '¿Vienes'), M.SENT)
        self.assertEqual(es('Oye', '¿qué'), M.COMMA)          # virgola mancante
        self.assertEqual(es('mira', '¡Cuidado!'), M.COMMA)
        self.assertEqual(es('de', '¿Qué'), M.FUNC)            # la parola funzionale prevale

    def test_starts_lower_skips_inverted(self):
        self.assertTrue(M._starts_lower(' ¿qué'))
        self.assertTrue(M._starts_lower(' ¡ay'))
        self.assertEqual(es('Bueno...', '¿qué'), M.SENT_WEAK)
        self.assertEqual(es('Bueno...', '¿Qué'), M.SENT)

    def test_detached_closing_punct_never_opens_piece(self):
        for p in ('?', '!', '?!', '»'):
            self.assertEqual(es('haces', p), M.INSIDE, p)


class TestAbbreviations(unittest.TestCase):
    def test_titles(self):
        for w, n in (('Sr.', 'García'), ('Sra.', 'López'), ('Srta.', 'Ruiz'), ('Dr.', 'Pérez'),
                     ('Dra.', 'Gómez'), ('Ud.', 'sabe'), ('Uds.', 'Son'), ('Vd.', 'no'),
                     ('D.', 'Quijote'), ('Dña.', 'Juana'), ('núm.', '5'), ('pág.', '12'), ('Prof.', 'Soto')):
            self.assertEqual(es(w, n), M.ABBREV, (w, n))

    def test_por_ejemplo(self):
        self.assertEqual(es('p.', 'ej.'), M.ABBREV)
        self.assertEqual(es('ej.', 'los'), M.ABBREV)
        self.assertEqual(es('ej.', 'Madrid'), M.ABBREV)
        self.assertEqual(es('p.ej.', 'Madrid'), M.ABBREV)

    def test_eeuu(self):
        self.assertEqual(es('EE.', 'UU.'), M.ABBREV)
        self.assertEqual(es('UU.', 'tiene'), M.ABBREV)
        self.assertEqual(es('UU.', '5'), M.ABBREV)
        self.assertEqual(es('UU.', 'Mañana'), M.SENT_WEAK)
        self.assertEqual(es('UU.', None), M.SENT)
        self.assertEqual(es('EE.UU.', 'y'), M.ABBREV)
        self.assertEqual(es('EE.UU.', 'Ella'), M.SENT_WEAK)

    def test_etc_ambiguous(self):
        self.assertEqual(es('etc.', 'y'), M.ABBREV)
        self.assertEqual(es('etc.', 'Bueno'), M.SENT_WEAK)

    def test_initials_and_numbers(self):
        self.assertEqual(es('B.', 'Vamos'), M.SENT_WEAK)       # el plan B. Vamos
        self.assertEqual(es('C.', 'y'), M.ABBREV)              # 300 a. C. y
        self.assertEqual(es('a.', 'C.'), M.ABBREV)
        self.assertEqual(es('42.', 'Ella'), M.SENT)            # numero col punto: fine frase
        self.assertEqual(es('2001.', 'Una'), M.SENT)
        self.assertEqual(es('casa.', 'Luego'), M.SENT)
        self.assertEqual(es('casa.', 'luego'), M.SENT_WEAK)
        self.assertEqual(es('No.', 'Vete'), M.SENT)            # "No." non e' un'abbreviazione


class TestFunctionAndConjunction(unittest.TestCase):
    def test_function_words(self):
        for w in ('el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'lo', 'a', 'al', 'de', 'del',
                  'en', 'con', 'por', 'para', 'sin', 'sobre', 'entre', 'hasta', 'desde', 'hacia', 'contra',
                  'según', 'tras', 'me', 'te', 'se', 'nos', 'os', 'le', 'les', 'yo', 'tú', 'él', 'ella',
                  'he', 'has', 'ha', 'hemos', 'habéis', 'han', 'había', 'estoy', 'está', 'están', 'es',
                  'son', 'era', 'fue', 'ser', 'estar', 'mi', 'mis', 'tu', 'tus', 'su', 'sus', 'nuestro',
                  'no', 'muy', 'más', 'tan', 'que'):
            self.assertEqual(es(w, 'cosa'), M.FUNC, w)

    def test_never_after_conjunction(self):
        for w in ('y', 'e', 'o', 'u', 'pero', 'sino', 'aunque', 'porque', 'pues', 'que', 'como',
                  'cuando', 'si', 'mientras', 'donde', 'ni'):
            self.assertEqual(es(w, 'cosa'), M.FUNC, w)

    def test_cut_before_conjunction(self):
        for w, n in (('casa', 'y'), ('tarde', 'pero'), ('cansado', 'porque'), ('dije', 'que'),
                     ('mañana', 'cuando'), ('sabes', 'si')):
            self.assertEqual(es(w, n), M.CONJ, (w, n))

    def test_locutions_stay_together(self):
        for w, n in (('ya', 'que'), ('así', 'que'), ('para', 'que'), ('sin', 'que'), ('lo', 'que'),
                     ('el', 'que'), ('la', 'que'), ('más', 'que'), ('tanto', 'como'), ('o', 'sea'),
                     ('antes', 'de'), ('después', 'de'), ('pesar', 'de'), ('de', 'que'), ('a', 'pesar'),
                     ('puesto', 'que'), ('siempre', 'que')):
            self.assertEqual(es(w, n), M.FUNC, (w, n))

    def test_accented_interrogatives_are_not_conjunctions(self):
        self.assertEqual(es('sé', 'qué'), M.WORD)
        self.assertEqual(es('dime', 'cómo'), M.WORD)

    def test_punctuation_and_dashes(self):
        self.assertEqual(es('Bueno,', 'vamos'), M.COMMA)
        self.assertEqual(es('dijo:', '«Ven'), M.CLAUSE)
        self.assertEqual(es('casa.»', 'Luego'), M.SENT)
        self.assertEqual(es('—', 'Hola'), M.FUNC)
        self.assertEqual(es('-', 'Hola'), M.FUNC)
        self.assertEqual(es('quería-', 'Mira'), M.COMMA)

    def test_inside_word(self):
        self.assertEqual(M.boundary_type(' anti', '-edad', 'es'), M.INSIDE)


class TestEndToEnd(unittest.TestCase):
    def assert_no_bad_edges(self, texts):
        for p in texts:
            self.assertFalse(p.lstrip()[:1] in ('?', '!'), texts)
            self.assertFalse(p.rstrip()[-1:] in ('¿', '¡'), texts)

    def test_cut_at_sentence_before_question(self):
        t = split(make_segment('Ayer fuimos al mercado con mis padres y compramos mucha fruta para toda la '
                               'semana. ¿Quieres venir con nosotros mañana por la tarde a la playa?'))
        self.assertIn(('semana.', '¿Quieres'), cut_pairs(t), t)
        self.assert_no_bad_edges(t)

    def test_isolated_marks_end_to_end(self):
        t = split(make_segment('Ayer fuimos al mercado con mis padres y compramos mucha fruta para toda la '
                               'semana ¿ Quieres venir con nosotros mañana por la tarde a la playa ? ¡ Claro '
                               'que sí , vamos todos juntos ahora mismo !'))
        self.assert_no_bad_edges(t)

    def test_no_cut_after_function_words(self):
        t = split(make_segment('Mi hermano me dijo que el profesor de la universidad no había llegado a la '
                               'hora de la clase porque su coche se había quedado sin gasolina en la carretera'))
        bad = {'el', 'la', 'de', 'a', 'que', 'no', 'mi', 'me', 'su', 'se', 'sin', 'en', 'había', 'porque'}
        for a, _ in cut_pairs(t):
            self.assertNotIn(a.lower(), bad, t)

    def test_eeuu_not_split(self):
        t = split(make_segment('Mi primo vive en los EE. UU. desde hace muchos años y trabaja en una empresa '
                               'muy grande de tecnología. Nos visita cada verano con toda su familia.'))
        for a, b in cut_pairs(t):
            self.assertNotEqual((a, b), ('EE.', 'UU.'), t)
        self.assertIn(('tecnología.', 'Nos'), cut_pairs(t), t)

    def test_title_abbreviation_not_cut(self):
        t = split(make_segment('Esta mañana hablé con el Sr. García sobre el problema del edificio y con la '
                               'Dra. López sobre los resultados. Ninguno de los dos sabía nada del asunto.'))
        for a, _ in cut_pairs(t):
            self.assertNotIn(a, ('Sr.', 'Dra.'), t)
        # (qui due pezzi bastano: il taglio cade su "edificio | y", il secondo pezzo sta in 84 caratteri)
        self.assertEqual(len(t), 2, t)

    def test_locution_ya_que(self):
        t = split(make_segment('No pudimos salir de casa durante todo el fin de semana ya que llovía muchísimo '
                               'y las calles del barrio estaban completamente inundadas'))
        self.assertNotIn(('ya', 'que'), cut_pairs(t), t)

    def test_open_question_first_word_not_cut(self):
        t = split(make_segment('Oye ¿qué piensas hacer este fin de semana con tus amigos del colegio y con '
                               'tu hermana pequeña cuando vuelva de su viaje por el sur del país?'))
        self.assertFalse(any(p.split()[-1].startswith('¿') for p in t), t)
        self.assert_no_bad_edges(t)


class TestEngineGuard(unittest.TestCase):
    """Con la lista di default (en,it,fr,de) lo spagnolo resta sullo split originale; acceso solo se in lista."""

    def seg(self):
        return make_segment('Ayer fuimos al mercado con mis padres y compramos mucha fruta para toda la semana. '
                            '¿Quieres venir con nosotros mañana por la tarde a la playa?')

    def test_default_list_keeps_original(self):
        seg = self.seg()
        off = TS.FakeConfig({'whisper_split_sentence_aware': True,
                             'whisper_split_sentence_langs': ['en', 'it', 'fr', 'de']})
        for code in ('es', 'spa', 'ES'):
            self.assertEqual(TS.engine_method(True, config=off, lang=code)(seg), ORIG(seg), code)
        self.assertEqual(TS.engine_method(True, lang='es')(seg), ORIG(seg))   # lista assente = ['en']

    def test_listed_spanish_uses_new_split(self):
        seg = self.seg()
        on = TS.FakeConfig({'whisper_split_sentence_aware': True,
                            'whisper_split_sentence_langs': ['en', 'it', 'fr', 'de', 'es']})
        for code in ('es', 'spa'):
            self.assertNotEqual(TS.engine_method(True, config=on, lang=code)(seg), ORIG(seg), code)
        off = TS.FakeConfig({'whisper_split_sentence_aware': False,
                             'whisper_split_sentence_langs': ['es']})
        self.assertEqual(TS.engine_method(True, config=off, lang='es')(seg), ORIG(seg))

    def test_production_default_list_has_spanish(self):
        # v1.29.0: acceso di default insieme al passaggio a Whisper per lo spagnolo
        # (scelta dell'utente, mt_eval/asr_es/RESULT.md) — prima era ancora spento.
        src = (ROOT / 'utils' / 'config.py').read_text(encoding='utf-8')
        import re
        m = re.search(r"'whisper_split_sentence_langs'\s*:\s*(\[[^\]]*\])", src)
        self.assertIsNotNone(m)
        self.assertIn("'es'", m.group(1))


class TestMetricLists(unittest.TestCase):
    def test_cont_words_es(self):
        cw = midcut.CONT_WORDS['es']
        for w in ('y', 'pero', 'que', 'porque', 'cuando', 'donde', 'de', 'del', 'al', 'en', 'para', 'el', 'la', 'un'):
            self.assertIn(w, cw)
        for w in ('qué', 'cómo', 'dónde', 'yo', 'no'):
            self.assertNotIn(w, cw)
        self.assertEqual(midcut.pair_kind('Fuimos al mercado', 'Y compramos fruta.', 0.1, 'es'), 'midcut')
        self.assertEqual(midcut.pair_kind('Fuimos al mercado', '¿y tú?', 0.1, 'es'), 'midcut')
        self.assertIsNone(midcut.pair_kind('Fuimos al mercado.', 'Y compramos fruta.', 0.1, 'es'))

    def test_naked_cuts_es(self):
        import naked_cuts as NC
        self.assertEqual(NC.CONJ['es'], frozenset(
            'y e o u ni pero sino aunque porque pues que como cuando si mientras donde'.split()))
        bl = [{'start': 0.0, 'end': 1.0, 'text': 'Fuimos al mercado'},
              {'start': 1.1, 'end': 2.0, 'text': 'y compramos fruta'},
              {'start': 2.1, 'end': 3.0, 'text': 'para toda la'},
              {'start': 3.1, 'end': 4.0, 'text': 'Semana.'}]
        self.assertEqual(NC.naked_flags(bl, 'es'), [False, True, True, False])


if __name__ == '__main__':
    unittest.main()
