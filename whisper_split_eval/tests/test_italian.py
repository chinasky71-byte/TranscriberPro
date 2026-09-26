"""
Test CPU delle regole ITALIANE di core/whisper_sentence_split.py (lang='it')
e della guardia di lingua nel motore ('whisper_split_sentence_langs').

Esempi presi dai 3 file italiani di TARATURA (work_it_runs/raw: Casper 1995,
Il diavolo veste Prada 2006, The Bad Guy); i segmenti reali usati sono copiati
in data_it_segments.json. data_en_baseline.json = output della versione
solo-inglese del modulo su 90 segmenti inglesi reali (l'inglese non cambia).

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
IT_RAW = EVAL / 'work_it_runs' / 'raw'
HAVE_DATA = (HERE / 'data_it_segments.json').exists() and (HERE / 'data_en_baseline.json').exists()
NEED_DATA = unittest.skipUnless(HAVE_DATA, 'fixture con dialoghi reali non pubblicate (.gitignore): non disponibili')


def load_it_cases():
    return json.loads((HERE / 'data_it_segments.json').read_text(encoding='utf-8'))['cases']


def it_case(key):
    return next(c['segment'] for c in load_it_cases() if key in c['keys'])


def cuts(pieces):
    """Coppie (fine pezzo, inizio pezzo successivo) come testo."""
    return [(a['text'], b['text']) for a, b in zip(pieces, pieces[1:])]


def has_cut(pieces, left_end, right_start):
    return any(a.endswith(left_end) and b.startswith(right_start) for a, b in cuts(pieces))


def whole_words(piece):
    return 1 + sum(1 for w in piece['words'][1:] if w['word'][:1].isspace())


class ItInvariants:
    def assert_ok(self, seg, pieces):
        self.assertIsNotNone(pieces)
        self.assertTrue(NS.validate_split(seg, pieces))
        flat = [w for p in pieces for w in p['words']]
        self.assertEqual(len(flat), len(seg['words']))
        for a, b in zip(flat, seg['words']):
            self.assertIs(a, b)
        joined = pieces[0]['text']
        for prev, p in zip(pieces, pieces[1:]):
            # mai tagli dentro parola ("l" | "'avevo"), tranne un salto >= 9 s (timestamp errato di Whisper)
            attached = not p['words'][0]['word'][:1].isspace()
            if attached:
                self.assertGreaterEqual(p['words'][0]['start'] - prev['words'][-1]['end'], 9.0,
                                        [q['text'] for q in pieces])
            joined += ('' if attached else ' ') + p['text']
        self.assertEqual(' '.join(joined.split()), ' '.join(''.join(w['word'] for w in seg['words']).split()))
        for p in pieces:
            if whole_words(p) >= 2:
                self.assertLessEqual(len(p['text']), 84)
                self.assertLessEqual(p['end'] - p['start'], 9.0 + 1e-9)


class TestBoundaryIt(unittest.TestCase):
    def it(self, w, n):
        return NS.boundary_type(' ' + w, (' ' + n) if n is not None else None, 'it')

    def en(self, w, n):
        return NS.boundary_type(' ' + w, (' ' + n) if n is not None else None)

    def test_function_words_not_cut_after(self):
        # regole EN sull'italiano: "un negozio del | centro", "di suo | figlio",
        # "Non | mi era mai capitato", "ha abbandonato la | psichiatria"
        for w, n in (('del', 'centro'), ('suo', 'figlio'), ('Non', 'mi'), ('la', 'psichiatria'),
                     ('una', 'mano'), ('di', 'demarcazione'), ('sei', 'totalmente'), ('Ti', 'ricorda')):
            self.assertEqual(self.it(w, n), NS.FUNC, (w, n))
            self.assertNotEqual(self.en(w, n), NS.FUNC, (w, n))

    def test_conjunction_before(self):
        # "per comprare un bel costume | che ho visto", "di suo figlio | e di aver"
        for w, n in (('costume', 'che'), ('figlio', 'e'), ('Maisel', 'e'), ('altri', 'quando'),
                     ('lavoro', 'ma'), ('domandarmi', 'se')):
            self.assertEqual(self.it(w, n), NS.CONJ, (w, n))

    def test_function_word_wins_over_conjunction(self):
        # "il motivo per | cui devo cambiare", "il genere di | cui ci occupiamo"
        for w, n in (('per', 'cui'), ('di', 'cui'), ('è', 'che'), ('ma', 'che')):
            self.assertEqual(self.it(w, n), NS.FUNC, (w, n))

    def test_conjunctive_phrases_glued(self):
        # "tutto quello | che" (37 nei dati), "prima | che loro le presentino", "Solo | quando"
        for w, n in (('quello', 'che'), ('prima', 'che'), ('Solo', 'quando'), ('solo', 'che'),
                     ('cosa', 'che'), ('anche', 'se'), ('visto', 'che')):
            self.assertEqual(self.it(w, n), NS.FUNC, (w, n))
        self.assertEqual(self.en('quello', 'che'), NS.WORD)

    def test_so_is_a_verb_not_english_conjunction(self):
        # coppie reali: "Non lo so" e "so che" (11 nei dati). Con le liste EN
        # "so" e' la congiunzione inglese: "lo | so" = CONJ (taglio incoraggiato),
        # "so | che" = FUNC (taglio scoraggiato). Nessun effetto MISURATO sui
        # 3 file (0 tagli "lo | so" in entrambi i bracci).
        self.assertEqual(self.en('lo', 'so'), NS.CONJ)
        self.assertEqual(self.it('lo', 'so'), NS.FUNC)
        self.assertEqual(self.en('so', 'che'), NS.FUNC)
        self.assertEqual(self.it('so', 'che'), NS.CONJ)

    def test_numbers_with_dot_end_sentences(self):
        # nessuna regola "ordinali": nei dati "42. Che", "38. Io", "2001. Una" sono fini frase
        for w, n in (('42.', 'Che'), ('38.', 'Io'), ('2001.', 'Una'), ('59.', 'E')):
            self.assertEqual(self.it(w, n), NS.SENT, (w, n))

    def test_no_dot_digit_is_sentence_end_in_italian(self):
        # la regola inglese "No. 5" non vale: in italiano "No." davanti a un numero chiude la frase
        self.assertEqual(self.en('No.', '5'), NS.ABBREV)
        self.assertEqual(self.it('No.', '5'), NS.SENT)

    def test_attached_tokens_are_inside(self):
        # elisioni, migliaia, orari: token senza spazio (dati: " l" + "'avevo",
        # " 1" + ".200" + ".000", " 12" + ".30.", " c" + "'è")
        for w, n in ((' l', "'avevo"), (' dell', "'umorismo?"), (' 1', '.200'), ('.200', '.000'),
                     (' 12', '.30.'), (' c', "'è"), (' J', '.K.')):
            self.assertEqual(NS.boundary_type(w, n, 'it'), NS.INSIDE, (w, n))

    def test_ellipsis(self):
        # 146 puntini nei dati; minuscola dopo = frase che prosegue
        self.assertEqual(self.it('vuoi...', 'non'), NS.SENT_WEAK)
        self.assertEqual(self.it('che...', 'È'), NS.SENT)
        # "in linea. Bene. ...che con un'appropriata": 1 solo caso, effetto
        # incerto -> nessuna regola italiana, stesso trattamento dell'inglese
        self.assertEqual(self.it('Bene.', '...che'), self.en('Bene.', '...che'))

    def test_single_capital_initial_is_weak_sentence_end(self):
        # dati: "un piano B. Sai che", "un piano A. È tornata!", "con la O. A me":
        # 3 su 3 fini frase (in inglese "J. Edgar" -> abbreviazione, invariato)
        for w, n in (('B.', 'Sai'), ('A.', 'È'), ('O.', 'A')):
            self.assertEqual(self.it(w, n), NS.SENT_WEAK, w)
            self.assertEqual(self.en(w, n), NS.ABBREV, w)

    def test_abbreviations_a_priori(self):
        # a priori: ZERO occorrenze "X." di queste abbreviazioni nei dati di taratura
        for w in ('Sig.', 'sig.', 'Dott.', 'Prof.', 'Avv.', 'Ing.', 'Geom.', 'Arch.', 'On.', 'Mons.',
                  'Gen.', 'Col.', 'Tel.', 'cfr.', 'es.', 'pag.', 'n.', 'Dr.'):
            self.assertEqual(self.it(w, 'Rossi'), NS.ABBREV, w)
        # dati: "Papà, ma sono io. Sono Cap." = nome a fine frase -> "cap" NON e' in lista
        self.assertEqual(self.it('Cap.', 'Sai'), NS.SENT)
        self.assertEqual(self.it('Art.', 'Sai'), NS.SENT)
        self.assertEqual(self.it('ecc.', 'e'), NS.ABBREV)
        self.assertEqual(self.it('ecc.', 'Poi'), NS.SENT_WEAK)
        self.assertEqual(self.it('ecc.', None), NS.SENT_WEAK)

    def test_punctuation(self):
        self.assertEqual(self.it('proprietà!', 'No,'), NS.SENT)
        self.assertEqual(self.it('davvero?!', 'Sì'), NS.SENT)
        self.assertEqual(self.it('fine.»', 'Poi'), NS.SENT)
        self.assertEqual(self.it('Miranda,', 'ma'), NS.COMMA)
        self.assertEqual(self.it("E'", 'muerto'), NS.FUNC)     # "E'" = "è" scritto con l'apostrofo

    def test_language_codes(self):
        for lang in ('it', 'IT', 'ita', 'italian'):
            self.assertEqual(NS.boundary_type(' del', ' centro', lang), NS.FUNC, lang)


@NEED_DATA
class TestSplitItReal(ItInvariants, unittest.TestCase):
    def test_di_suo_figlio(self):
        seg = it_case('di suo figlio')
        en = NS.sentence_aware_split(seg, lang='en')
        it = NS.sentence_aware_split(seg, lang='it')
        self.assert_ok(seg, it)
        self.assertTrue(has_cut(en, 'di suo', 'figlio'))
        self.assertFalse(has_cut(it, 'di suo', 'figlio'))
        self.assertTrue(has_cut(it, 'di suo figlio', 'e di aver'))

    def test_negozio_del_centro(self):
        seg = it_case('negozio del centro')
        self.assertTrue(has_cut(NS.sentence_aware_split(seg, lang='en'), 'negozio del', 'centro.'))
        it = NS.sentence_aware_split(seg, lang='it')
        self.assert_ok(seg, it)
        self.assertFalse(any(a.endswith(' del') for a, _ in cuts(it)))

    def test_per_il_quale_sei(self):
        seg = it_case('per il quale sei')
        self.assertTrue(has_cut(NS.sentence_aware_split(seg, lang='en'), 'per il quale sei', 'totalmente'))
        it = NS.sentence_aware_split(seg, lang='it')
        self.assert_ok(seg, it)
        self.assertFalse(has_cut(it, 'sei', 'totalmente'))

    def test_relative_and_conjunctive_phrases(self):
        for key, left, right in (('motivo per cui', 'per', 'cui'), ('genere di cui', 'di', 'cui'),
                                 ('prima che loro', 'prima', 'che loro'), ('Solo quando', 'Solo', 'quando')):
            seg = it_case(key)
            it = NS.sentence_aware_split(seg, lang='it')
            self.assert_ok(seg, it)
            self.assertFalse(has_cut(it, ' ' + left, right), (key, cuts(it)))

    def test_long_gap_forces_cut(self):
        # "Cos" ... "'è successo?": salto di 105 s DENTRO la parola (timestamp errato di Whisper): oltre
        # glitch_gap_s (9 s) il token attaccato e' una parola a se' e si taglia li' (il blocco non
        # trascina piu' il resto del segmento 100 s in anticipo)
        seg = it_case("Cos'è successo? Papà")
        it = NS.sentence_aware_split(seg, lang='it')
        self.assert_ok(seg, it)
        self.assertTrue(has_cut(it, 'Cos', "'è"), [q['text'] for q in it])

    def test_all_tuning_segments_invariants(self):
        if not IT_RAW.exists():
            self.skipTest('dati di taratura italiani non disponibili')
        n = 0
        for p in sorted(IT_RAW.glob('*.json')):
            for seg in json.loads(p.read_text(encoding='utf-8'))['segments']:
                it = NS.sentence_aware_split(seg, lang='it')
                if len(seg['text']) <= 80 and seg['end'] - seg['start'] <= 6.0:
                    self.assertEqual(it, ORIG(seg))
                    continue
                n += 1
                self.assert_ok(seg, it)
                self.assertEqual(TS.engine_method(None, config=TS.FakeConfig({
                    'whisper_split_sentence_aware': True,
                    'whisper_split_sentence_langs': ['en', 'it']}), lang='it')(seg), it)
        self.assertGreater(n, 300)

    def test_short_and_empty_identical_to_original(self):
        seg = {'start': 0.0, 'end': 2.0, 'text': 'Ciao. Come stai?',
               'words': [{'start': 0.0, 'end': 0.5, 'word': ' Ciao.'}, {'start': 0.6, 'end': 1.0, 'word': ' Come'},
                         {'start': 1.0, 'end': 2.0, 'word': ' stai?'}]}
        self.assertEqual(NS.sentence_aware_split(seg, lang='it'), ORIG(seg))
        seg2 = {'start': 0.0, 'end': 20.0, 'text': 'x' * 200, 'words': []}
        self.assertEqual(NS.sentence_aware_split(seg2, lang='it'), ORIG(seg2))


@NEED_DATA
class TestEnglishUnchanged(unittest.TestCase):
    """(i) lang='en' (e default) == baseline solo-inglese su 90 segmenti reali."""

    def test_matches_baseline(self):
        cases = json.loads((HERE / 'data_en_baseline.json').read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(cases), 90)
        for c in cases:
            seg = c['segment']
            for out in (NS.sentence_aware_split(seg), NS.sentence_aware_split(seg, 80, 6.0, None, 'en'),
                        NS.sentence_aware_split(seg, lang='eng')):
                got = [{'start': x['start'], 'end': x['end'], 'text': x['text'], 'n_words': len(x['words'])}
                       for x in out]
                self.assertEqual(got, c['expected'], c['src'])


@NEED_DATA
class TestEngineLanguageList(unittest.TestCase):
    def seg(self):
        return it_case('di suo figlio')

    def test_default_config_italian_uses_original(self):
        # (ii) opzione accesa, lista lingue assente (default ['en']) -> italiano = split originale
        seg = self.seg()
        self.assertEqual(TS.engine_method(True, lang='it')(seg), ORIG(seg))
        cfg = TS.FakeConfig({'whisper_split_sentence_aware': True, 'whisper_split_sentence_langs': ['en']})
        self.assertEqual(TS.engine_method(None, config=cfg, lang='it')(seg), ORIG(seg))

    def test_italian_enabled_uses_italian_rules(self):
        # (iii) lista ['en', 'it'] -> split nuovo con le regole ITALIANE
        seg = self.seg()
        cfg = TS.FakeConfig({'whisper_split_sentence_aware': True, 'whisper_split_sentence_langs': ['en', 'it']})
        out = TS.engine_method(None, config=cfg, lang='it')(seg)
        self.assertEqual(out, NS.sentence_aware_split(seg, lang='it'))
        self.assertNotEqual(out, ORIG(seg))
        self.assertNotEqual(out, NS.sentence_aware_split(seg, lang='en'))
        # l'inglese resta con le regole inglesi anche con l'italiano in lista
        en_seg = json.loads((HERE / 'data_en_baseline.json').read_text(encoding='utf-8'))['cases'][0]['segment']
        self.assertEqual(TS.engine_method(None, config=cfg, lang='en')(en_seg), NS.sentence_aware_split(en_seg))

    def test_language_list_variants(self):
        seg = self.seg()
        it_split = NS.sentence_aware_split(seg, lang='it')
        for langs, expect_new in ((['IT'], True), (['ita'], True), ('it', True), (('en', 'it'), True),
                                  ([], False), (None, False), (5, False), (['en'], False), (['fr'], False)):
            cfg = TS.FakeConfig({'whisper_split_sentence_aware': True, 'whisper_split_sentence_langs': langs})
            out = TS.engine_method(None, config=cfg, lang='it')(seg)
            self.assertEqual(out, it_split if expect_new else ORIG(seg), langs)
        # valore None salvato in config = default ['en'] (l'inglese resta acceso)
        en_seg = json.loads((HERE / 'data_en_baseline.json').read_text(encoding='utf-8'))['cases'][0]['segment']
        for langs, expect_new in ((None, True), ([], False), (['it'], False)):
            cfg = TS.FakeConfig({'whisper_split_sentence_aware': True, 'whisper_split_sentence_langs': langs})
            out = TS.engine_method(None, config=cfg, lang='en')(en_seg)
            self.assertEqual(out, NS.sentence_aware_split(en_seg) if expect_new else ORIG(en_seg), langs)

    def test_option_off_ignores_language_list(self):
        seg = self.seg()
        for flag in (False, None):
            cfg = TS.FakeConfig({'whisper_split_sentence_langs': ['en', 'it']}
                                | ({} if flag is None else {'whisper_split_sentence_aware': flag}))
            self.assertEqual(TS.engine_method(None, config=cfg, lang='it')(seg), ORIG(seg))
            self.assertNotIn('whisper_split_sentence_langs', cfg.calls)

    def test_unsupported_language_falls_back(self):
        # lingua in lista ma senza regole (es. 'fr'): il modulo ritorna None -> split originale
        seg = self.seg()
        self.assertIsNone(NS.sentence_aware_split(seg, lang='fr'))
        cfg = TS.FakeConfig({'whisper_split_sentence_aware': True, 'whisper_split_sentence_langs': ['en', 'fr']})
        self.assertEqual(TS.engine_method(None, config=cfg, lang='fr')(seg), ORIG(seg))


if __name__ == '__main__':
    unittest.main()
