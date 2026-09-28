"""
Test CPU delle regole TEDESCHE di core/whisper_sentence_split.py (lang='de'), portati da
whisper_split_eval/de_prelim/test_rules_de.py (28/09/2026) sul modulo di produzione, e di CONT_WORDS['de'].
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT))
from split_eval.midcut import CONT_WORDS  # noqa: E402
CONT_WORDS_DE = CONT_WORDS['de']


def _real_module():
    import test_support as TS
    return TS.real_new_module()


M = _real_module()
R = M


def de(w, n):
    return M.boundary_type(' ' + w, (' ' + n) if n is not None else None, 'de')


def make_segment(text, word_s=0.32, pauses=None):
    """Segmento sintetico stile faster-whisper: token con spazio iniziale,
    0,32 s a parola, pause opzionali {indice_parola: secondi} DOPO la parola."""
    pauses = pauses or {}
    words, t = [], 0.0
    for i, w in enumerate(text.split()):
        words.append({'word': ' ' + w, 'start': round(t, 3), 'end': round(t + word_s, 3), 'probability': 0.9})
        t += word_s + 0.04 + pauses.get(i, 0.0)
    return {'start': words[0]['start'], 'end': words[-1]['end'],
            'text': ''.join(w['word'] for w in words), 'words': words}


def split(seg):
    pieces = M.sentence_aware_split(seg, lang='de')
    assert pieces is not None
    assert M.validate_split(seg, pieces)
    return [p['text'] for p in pieces]


def cut_pairs(texts):
    return [(a.split()[-1], b.split()[0]) for a, b in zip(texts, texts[1:])]


class TestModuleSupportsDe(unittest.TestCase):
    def test_de_supported_and_codes(self):
        self.assertIn('de', M.SUPPORTED_LANGS)
        for code in ('de', 'ger', 'deu', 'DE'):
            self.assertEqual(M._norm_lang(code), 'de', code)
        self.assertIsNotNone(M.sentence_aware_split(make_segment('Wort ' * 40), lang='ger'))


class TestCapitalNouns(unittest.TestCase):
    """(a) sostantivi maiuscoli: punto + maiuscola non basta."""

    def test_normal_word_dot_capital_is_sentence_end(self):
        # dati de1: "sass. Aber", "Pflicht.", "Stock. Und"
        for w, n in (('sass.', 'Aber'), ('essen.', 'Obwohl'), ('Stock.', 'Und'), ('Hause.', 'Morgen'),
                     ('gemacht?', 'Wir'), ('Nein!', 'Das')):
            self.assertIn(de(w, n), (R.SENT,), (w, n))

    def test_letter_dot_noun_is_not_sentence_end(self):
        self.assertEqual(de('B.', 'Hunde'), R.ABBREV)          # z. B. Hunde
        self.assertEqual(de('J.', 'Müller'), R.ABBREV)         # Hans J. Müller
        self.assertEqual(de('B.', 'Wir'), R.SENT_WEAK)         # Plan B. Wir gehen
        self.assertEqual(de('A.', 'Ich'), R.SENT_WEAK)

    def test_dot_lowercase_is_not_sentence_end(self):
        # in tedesco una frase non apre in minuscola: abbreviazione ignota
        self.assertEqual(de('Str.', 'und'), R.ABBREV)
        self.assertEqual(de('Haus.', 'aber'), R.ABBREV)
        # dopo ... ? ! resta fine incerta, come en/it
        self.assertEqual(de('Na...', 'und'), R.SENT_WEAK)
        self.assertEqual(de('Wirklich?', 'dachte'), R.SENT_WEAK)


class TestOrdinals(unittest.TestCase):
    """(b) punto dopo numero."""

    def test_ordinal_before_month_or_noun(self):
        for w, n in (('3.', 'Mai'), ('24.', 'Dezember'), ('1.', 'März'), ('1.', 'Maerz'),
                     ('2.', 'Weltkrieg'), ('20.', 'Jahrhundert'), ('3.', 'Stock')):
            self.assertEqual(de(w, n), R.ABBREV, (w, n))

    def test_ordinal_before_lowercase(self):
        # "am 3. und 4. Mai", "der 2. große Krieg": minuscola -> NON fine frase
        # (deviazione dichiarata dalla consegna "salvo minuscola")
        self.assertEqual(de('3.', 'und'), R.ABBREV)
        self.assertEqual(de('2.', 'große'), R.ABBREV)

    def test_number_dot_opener_or_end(self):
        self.assertEqual(de('5.', 'Ich'), R.SENT_WEAK)          # "Es ist 5. Ich gehe"
        self.assertEqual(de('5.', None), R.SENT)                # fine segmento

    def test_roman_numerals(self):
        self.assertEqual(de('XIV.', 'war'), R.ABBREV)           # Ludwig XIV. war
        self.assertEqual(de('XIV.', 'König'), R.ABBREV)
        self.assertEqual(de('XIV.', 'Er'), R.SENT_WEAK)
        self.assertEqual(de('XIV.', None), R.SENT)

    def test_years_are_plain_numbers(self):
        self.assertEqual(de('1945.', 'Deutschland'), R.SENT)
        self.assertEqual(de('1945.', 'Dann'), R.SENT)


class TestAbbreviations(unittest.TestCase):
    """(c) abbreviazioni, anche spezzate in due token."""

    def test_split_abbreviations(self):
        for w, n in (('z.', 'B.'), ('d.', 'h.'), ('u.', 'a.'), ('z.', 'B')):
            self.assertEqual(de(w, n), R.ABBREV, (w, n))
        self.assertEqual(de('h.', 'wir'), R.ABBREV)             # d. h. wir
        self.assertEqual(de('a.', 'Berlin'), R.ABBREV)          # u. a. Berlin

    def test_compact_and_listed(self):
        for w, n in (('z.B.', 'Hunde'), ('d.h.', 'dass'), ('bzw.', 'die'), ('ca.', '20'), ('Nr.', '5'),
                     ('Dr.', 'Schmidt'), ('Prof.', 'Huber'), ('Hr.', 'Meier'), ('Fr.', 'Weber'),
                     ('St.', 'Pauli'), ('evtl.', 'morgen'), ('ggf.', 'auch'), ('vgl.', 'Seite')):
            self.assertEqual(de(w, n), R.ABBREV, (w, n))

    def test_usw_can_end_sentence(self):
        self.assertEqual(de('usw.', 'und'), R.ABBREV)
        self.assertEqual(de('usw.', 'Dann'), R.SENT_WEAK)
        self.assertEqual(de('etc.', 'Wir'), R.SENT_WEAK)

    def test_names_not_abbreviations(self):
        # "Max." "Art." sono parole/nomi: fine frase
        self.assertEqual(de('Max.', 'Wir'), R.SENT)
        self.assertEqual(de('Art.', 'Das'), R.SENT)


class TestEszett(unittest.TestCase):
    """(d) primeline scrive ss per ß: entrambe le grafie."""

    def test_both_spellings(self):
        for a, b in (('dass', 'daß'), ('muss', 'muß'), ('musste', 'mußte'), ('ausser', 'außer')):
            self.assertEqual(de('Zeit', a), de('Zeit', b), (a, b))
            self.assertEqual(de(a, 'Wort'), de(b, 'Wort'), (a, b))
        self.assertEqual(de('weiss', 'dass'), R.CONJ)           # "Ich weiss | dass"
        self.assertEqual(de('so', 'dass'), R.FUNC)
        self.assertEqual(de('so', 'daß'), R.FUNC)
        self.assertEqual(de('dass', 'er'), R.FUNC)
        self.assertEqual(de('daß', 'er'), R.FUNC)
        self.assertIn('dass', CONT_WORDS_DE)
        self.assertIn('daß', CONT_WORDS_DE)
        self.assertIn('ausser', CONT_WORDS_DE)
        self.assertIn('außer', CONT_WORDS_DE)


class TestQuotesAndDashes(unittest.TestCase):
    """(e) virgolette tedesche e trattini."""

    def test_module_helpers_miss_german_closing_quote(self):
        # perche' servono chiusure locali: con le funzioni del modulo "Nein.“" non e' fine frase
        spec = importlib.util.spec_from_file_location('_wss_q', ROOT / 'core' / 'whisper_sentence_split.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.boundary_type(' Nein.“', ' Er', 'it'), mod.WORD)
        self.assertEqual(mod.boundary_type(' Nein.“', ' Er', 'en'), mod.WORD)
        self.assertEqual(M.boundary_type(' Nein.“', ' Er', 'de'), R.SENT)

    def test_german_closing_quotes(self):
        self.assertEqual(de('Nein.“', 'Er'), R.SENT)
        self.assertEqual(de('Nein.«', 'Er'), R.SENT)
        self.assertEqual(de('kommen?“', 'fragte'), R.SENT_WEAK)
        self.assertEqual(de('sagte:', '„Komm'), R.CLAUSE)
        self.assertEqual(de('Ja,“', 'sagte'), R.COMMA)

    def test_opening_quote_lowercase(self):
        # "„und" dopo un punto: la virgoletta d'apertura non nasconde la minuscola
        self.assertEqual(de('Haus.', '„und'), R.ABBREV)
        self.assertEqual(de('3.', '»Mai«'), R.ABBREV)

    def test_isolated_quote_or_dash_never_ends_piece(self):
        self.assertEqual(de('„', 'Komm'), R.FUNC)
        self.assertEqual(de('-', 'Und'), R.FUNC)
        self.assertEqual(de('–', 'Nein'), R.FUNC)

    def test_dialogue_dash_after_sentence(self):
        self.assertEqual(de('Stock.', '-Und'), R.SENT)
        self.assertEqual(de('Stock.', '-'), R.SENT)

    def test_suspended_hyphen(self):
        self.assertEqual(de('Ein-', 'und'), R.FUNC)            # Ein- und Ausgang
        self.assertEqual(de('Vor-', 'oder'), R.FUNC)
        self.assertEqual(de('wollte-', 'Ich'), R.COMMA)        # interruzione


class TestFunctionAndConjunction(unittest.TestCase):
    def test_no_cut_after_articles_prepositions(self):
        for w, n in (('der', 'Universität'), ('ein', 'Kind'), ('im', 'Deutschen'), ('zu', 'Mittag'),
                     ('mit', 'Ihnen'), ('Ihr', 'Bruder'), ('habe', 'ich'), ('nicht', 'gelesen'),
                     ('um', 'zwölf'), ('einen', 'seiner')):
            self.assertEqual(de(w, n), R.FUNC, (w, n))

    def test_conjunction_before(self):
        for w, n in (('Zettel', 'und'), ('Witze', 'aber'), ('gezeigt', 'wo'), ('Tagen', 'weil'),
                     ('Geburtstag', 'und')):
            self.assertEqual(de(w, n), R.CONJ, (w, n))

    def test_clause_final_function_words_allow_cut(self):
        # aux / pronome / dimostrativo / prefisso separabile chiudono la frase
        for w, n in (('habe', 'und'), ('ich', 'aber'), ('das', 'aber'), ('an', 'und'), ('auf', 'wenn'),
                     ('nicht', 'weil')):
            self.assertEqual(de(w, n), R.CONJ, (w, n))

    def test_never_after_conjunction_and_glue(self):
        for w, n in (('und', 'wenn'), ('weil', 'wir'), ('als', 'ob'), ('ohne', 'dass'), ('auch', 'wenn'),
                     ('statt', 'dass'), ('mehr', 'als'), ('größer', 'als'), ('grösser', 'als'),
                     ('eine', 'und')):
            self.assertEqual(de(w, n), R.FUNC, (w, n))

    def test_inside_word(self):
        self.assertEqual(M.boundary_type(' Nerven', '-klinik', 'de'), R.INSIDE)


class TestEndToEnd(unittest.TestCase):
    """sentence_aware_split (copia privata del modulo) con le regole tedesche:
    tagli buoni e tagli cattivi evitati; invarianti validate_split."""

    def test_cut_at_sentence_not_at_ordinal(self):
        t = split(make_segment('Wir haben am 3. Mai im Englischen Garten zu Mittag gegessen und danach '
                               'sind wir zusammen spazieren gegangen. Dann kam der Hausmeister und '
                               'hat uns alle nach Hause geschickt.'))
        self.assertTrue(any(a == 'gegangen.' and b == 'Dann' for a, b in cut_pairs(t)), t)
        self.assertFalse(any(a == '3.' for a, b in cut_pairs(t)), t)

    def test_no_cut_inside_zb(self):
        t = split(make_segment('Es gibt viele Tiere im Garten hinter dem Haus meiner Grossmutter, z. B. '
                               'Hunde, Katzen und Vögel, und wir haben uns um alle gekümmert, jeden Tag.'))
        for a, b in cut_pairs(t):
            self.assertNotIn((a, b), (('z.', 'B.'), ('B.', 'Hunde,')), t)

    def test_no_cut_after_article_in_long_clause(self):
        # nessuna punteggiatura: non tagliare dopo der/die/das/ein/im/zu
        t = split(make_segment('Ich habe meinem Bruder das psychologische Institut gezeigt wo ich öfters '
                               'Vorlesungen besuche und dann sind wir zusammen in den ersten Stock '
                               'zu der Vorlesung von Professor Huber gegangen'))
        bad = {'das', 'der', 'den', 'ein', 'im', 'zu', 'in', 'von', 'meinem'}
        for a, _ in cut_pairs(t):
            self.assertNotIn(a.lower(), bad, t)

    def test_cut_before_conjunction_when_no_punctuation(self):
        # (con 155 caratteri il taglio "sass | aber" lascerebbe un primo pezzo > 84: testo accorciato)
        t = split(make_segment('Gisela sass in der Vorlesung von Professor Huber über Philosophie '
                               'aber die ist im ersten Stock und wir waren im zweiten'))
        self.assertIn(('Philosophie', 'aber'), cut_pairs(t), t)

    def test_dialogue_dash_opens_piece(self):
        t = split(make_segment('Ich habe meinem Bruder das psychologische Institut gezeigt, wo ich öfters '
                               'Vorlesungen besuche. - Und wo befanden sich da die Flugblätter, die Sie '
                               'überall gesehen haben?'))
        for a in t:
            self.assertFalse(a.endswith(' -'), t)
        self.assertTrue(any(p.startswith('- Und') for p in t), t)

    def test_quotes(self):
        t = split(make_segment('Er sagte zu mir: „Komm sofort nach Hause, wir müssen reden.“ Dann ist er '
                               'gegangen und hat die Tür hinter sich zugemacht, ohne ein Wort.'))
        self.assertIn(('reden.“', 'Dann'), cut_pairs(t), t)


class TestContWords(unittest.TestCase):
    def test_contents(self):
        for w in ('und', 'aber', 'weil', 'dass', 'daß', 'wenn', 'zum', 'im', 'ein', 'über'):
            self.assertIn(w, CONT_WORDS_DE)
        for w in ('der', 'die', 'das', 'ich', 'sie', 'keine'):
            self.assertNotIn(w, CONT_WORDS_DE)

    def test_midcut_with_runtime_rebind(self):
        sys.path.insert(0, str(ROOT))
        from split_eval import midcut
        saved = midcut.CONT_WORDS
        try:
            midcut.CONT_WORDS = {**saved, 'de': CONT_WORDS_DE}
            self.assertEqual(midcut.pair_kind('Ich habe die Zettel gesehen', 'Und nicht gelesen.', 0.1, 'de'),
                             'midcut')
            self.assertIsNone(midcut.pair_kind('Das liegt im Stock.', 'Und wo?', 0.1, 'de'))
            self.assertIsNone(midcut.pair_kind('heute um zwölf', 'Uhr im Seehaus.', 0.1, 'de'))  # limite
        finally:
            midcut.CONT_WORDS = saved
        self.assertIs(midcut.CONT_WORDS, saved)


if __name__ == '__main__':
    unittest.main()


class TestEngineGateDe(unittest.TestCase):
    """Il motore accende lo split tedesco anche con codici a 3 lettere ('ger'[:2] = 'ge' era il rischio)."""

    def test_ger_code_uses_german_rules_only_when_listed(self):
        import test_support as TS
        import common as C
        orig = C.orig_split_mod().orig_split
        seg = make_segment('Ich habe mich gestern Abend umentschieden. Dann bin ich in die Universität gegangen, '
                           'um Gisela abzusagen, weil wir heute zusammen essen wollten.')
        off = TS.FakeConfig({'whisper_split_sentence_aware': True, 'whisper_split_sentence_langs': ['en', 'it', 'fr']})
        on = TS.FakeConfig({'whisper_split_sentence_aware': True, 'whisper_split_sentence_langs': ['en', 'it', 'fr', 'de']})
        for code in ('de', 'ger', 'deu'):
            self.assertEqual(TS.engine_method(True, config=off, lang=code)(seg), orig(seg), code)
            self.assertNotEqual(TS.engine_method(True, config=on, lang=code)(seg), orig(seg), code)
