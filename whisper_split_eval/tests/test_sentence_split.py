"""
Test CPU (nessun modello) di core/whisper_sentence_split.py e dell'aggancio
in core/engines/faster_whisper_engine.py.

Esecuzione:
  cd whisper_split_eval\\tests
  set PYTHONIOENCODING=utf-8 & ..\\..\\venv\\Scripts\\python.exe -m unittest discover -p "test_*.py" -v
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path.insert(0, str(EVAL))

import common as C  # noqa: E402
import test_support as TS  # noqa: E402

NS = TS.real_new_module()
ORIG = C.orig_split_mod().orig_split


def mkseg(text_words, t0=0.0, step=0.3, gaps=None):
    """Segmento sintetico: parole con ' ' iniziale come faster-whisper."""
    words = []
    t = t0
    gaps = gaps or {}
    for i, w in enumerate(text_words):
        t += gaps.get(i, 0.0)
        words.append({'start': round(t, 3), 'end': round(t + step - 0.05, 3), 'word': ' ' + w})
        t += step
    return {'start': words[0]['start'], 'end': words[-1]['end'],
            'text': ''.join(w['word'] for w in words).strip(), 'words': words}


def check_invariants(tc, seg, pieces, hard_chars=84, hard_dur=9.0):
    tc.assertTrue(pieces)
    flat = [w for p in pieces for w in p['words']]
    tc.assertEqual(len(flat), len(seg['words']))
    for a, b in zip(flat, seg['words']):
        tc.assertIs(a, b)
    prev = None
    for p in pieces:
        tc.assertEqual(p['text'], ''.join(w['word'] for w in p['words']).strip())
        tc.assertEqual(p['start'], p['words'][0]['start'])
        tc.assertEqual(p['end'], p['words'][-1]['end'])
        tc.assertLessEqual(p['start'], p['end'])
        if prev is not None:
            tc.assertGreaterEqual(p['start'], prev)
        prev = p['start']
        if len(p['words']) > 1:
            tc.assertLessEqual(len(p['text']), hard_chars)
            tc.assertLessEqual(p['end'] - p['start'], hard_dur + 1e-9)
    # testo = concatenazione delle parole (i segmenti ricostruiti dagli hyp
    # hanno gia' in seg['text'] gli spazi spuri dello split originale)
    tc.assertEqual(' '.join(p['text'] for p in pieces),
                   ' '.join(''.join(w['word'] for w in seg['words']).split()))
    tc.assertTrue(NS.validate_split(seg, pieces))


class TestBoundaryType(unittest.TestCase):
    def t(self, w, n):
        return NS.boundary_type(' ' + w, ' ' + n if n else None)

    def test_sentence(self):
        self.assertEqual(self.t('home.', 'Then'), NS.SENT)
        self.assertEqual(self.t('what?', 'I'), NS.SENT)
        self.assertEqual(self.t('now!"', 'She'), NS.SENT)
        self.assertEqual(self.t('said.)', 'And'), NS.SENT)
        self.assertEqual(self.t('Okay…', 'Look'), NS.SENT)

    def test_weak_and_ellipsis(self):
        self.assertEqual(self.t('I...', 'think'), NS.SENT_WEAK)
        self.assertEqual(self.t('home.', 'and'), NS.SENT_WEAK)

    def test_abbreviations(self):
        self.assertEqual(self.t('Mr.', 'Smith'), NS.ABBREV)
        self.assertEqual(self.t('Dr.', 'Jones'), NS.ABBREV)
        self.assertEqual(self.t('St.', 'Louis'), NS.ABBREV)
        self.assertEqual(self.t('J.', 'Edgar'), NS.ABBREV)
        self.assertEqual(self.t('No.', '5'), NS.ABBREV)
        self.assertEqual(self.t('No.', 'I'), NS.SENT)
        self.assertEqual(self.t('U.S.', 'army'), NS.ABBREV)

    def test_numbers_are_not_sentence_ends(self):
        self.assertEqual(self.t('3.5', 'million'), NS.WORD)
        self.assertEqual(self.t('$3.50', 'for'), NS.CONJ if 'for' in NS._CONJ else NS.WORD)

    def test_clauses(self):
        self.assertEqual(self.t('wait;', 'she'), NS.CLAUSE)
        self.assertEqual(self.t('this:', 'we'), NS.CLAUSE)
        self.assertEqual(self.t('Look,', 'I'), NS.COMMA)
        self.assertEqual(self.t('home', 'because'), NS.CONJ)
        self.assertEqual(self.t('the', 'man'), NS.FUNC)
        self.assertEqual(self.t("I'm", 'going'), NS.FUNC)
        self.assertEqual(self.t('house', 'yesterday'), NS.WORD)


class TestWrap(unittest.TestCase):
    def test_wrap_matches_formatter(self):
        F = C.prodmods_mod().SubtitleFormatter()
        texts = ['a' * 40, 'word ' * 17, 'The quick brown fox jumps over the lazy dog and runs away fast now.',
                 'x' * 50 + ' ' + 'y' * 30, 'Supercalifragilistic ' * 5]
        for t in texts:
            t = t.strip()
            self.assertEqual(NS.wrap_lines(t, 42), len(F._wrap_cpl(t)), t)


class TestSplitSynthetic(unittest.TestCase):
    def test_short_segment_identical_to_original(self):
        seg = mkseg('Hello there. How are you?'.split())
        self.assertEqual(NS.sentence_aware_split(seg), ORIG(seg))

    def test_no_words_identical_to_original(self):
        seg = {'start': 0.0, 'end': 20.0, 'text': 'x' * 200, 'words': []}
        self.assertEqual(NS.sentence_aware_split(seg), ORIG(seg))
        seg2 = {'start': 0.0, 'end': 20.0, 'text': 'x' * 200}
        self.assertEqual(NS.sentence_aware_split(seg2), ORIG(seg2))

    def test_cuts_at_sentence_ends(self):
        s = ("I told you already that we can't stay here tonight. The storm is coming "
             "and the roads will be closed by midnight. We have to leave now, before it gets dark.")
        seg = mkseg(s.split())
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)
        for p in pieces[:-1]:
            self.assertRegex(p['text'], r'[.?!]$', p['text'])
        # lo split originale invece taglia a meta' frase
        self.assertTrue(any(not p['text'].endswith(('.', '?', '!')) for p in ORIG(seg)[:-1]))

    def test_abbreviation_not_cut(self):
        s = ("We met Mr. Anderson at the station yesterday. He told us Dr. Jones had left "
             "the building an hour before the police arrived at the scene.")
        seg = mkseg(s.split())
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)
        for p in pieces:
            self.assertFalse(p['text'].endswith(('Mr.', 'Dr.')), p['text'])

    def test_long_sentence_cut_at_clause(self):
        s = ("When we finally got to the house on the other side of the river, the door was open "
             "and nobody was inside waiting for us")
        seg = mkseg(s.split())
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)
        self.assertGreaterEqual(len(pieces), 2)
        self.assertTrue(pieces[0]['text'].endswith(','), [p['text'] for p in pieces])

    def test_very_long_sentence_no_punct(self):
        s = ' '.join(['word%d' % i for i in range(80)])
        seg = mkseg(s.split(), step=0.25)
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)
        # nessun pezzo sbilanciato: niente frammenti di 1-2 parole a meta' frase
        for p in pieces:
            self.assertGreaterEqual(len(p['words']), 3)

    def test_quotes_and_parentheses(self):
        s = ('He said "stop right there." Then he ran towards the car (the red one.) '
             'Nobody followed him because everyone was too scared to move at all.')
        seg = mkseg(s.split())
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)
        self.assertTrue(all(p['text'].endswith(('."', '.)', '.')) for p in pieces[:-1]),
                        [p['text'] for p in pieces])

    def test_duration_hard_cap(self):
        s = 'Yes. ' * 3 + 'I know what you mean but I really do not think that this is going to work out'
        seg = mkseg(s.split(), step=0.6)          # parlato lento: > 9 s
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)

    def test_single_giant_word(self):
        seg = mkseg(['x' * 120, 'and', 'then', 'more', 'words', 'here.'], step=2.5)
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)

    def test_never_cuts_inside_hyphenated_word(self):
        # faster-whisper: "post" + "-traumatic" (secondo token senza spazio)
        toks = ("It's a clear case of post -traumatic stress disorder and the doctors at the "
                "hospital said that it would take a very long time to heal completely.").split()
        seg = mkseg(toks)
        for w in seg['words']:
            if w['word'] == ' -traumatic':
                w['word'] = '-traumatic'
        seg['text'] = ''.join(w['word'] for w in seg['words']).strip()
        self.assertEqual(NS.boundary_type(' post', '-traumatic'), NS.INSIDE)
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)
        for p in pieces[1:]:
            self.assertTrue(p['words'][0]['word'].startswith(' '), [q['text'] for q in pieces])

    def test_long_pause_prefers_cut(self):
        s = 'Come here. I need to show you something important about the plan for tomorrow morning at the harbour.'
        seg = mkseg(s.split(), gaps={2: 1.5})
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)
        self.assertEqual(pieces[0]['text'], 'Come here.')

    def test_tail_merge_same_rule(self):
        # coda di 2 parole a meta' frase con pausa breve: unita se ci sta
        s = ('We are going to the old warehouse by the docks to find the missing money '
             'tonight before the others')
        seg = mkseg(s.split(), step=0.33)
        pieces = NS.sentence_aware_split(seg)
        check_invariants(self, seg, pieces)
        self.assertGreaterEqual(len(pieces[-1]['words']), 3)


class TestRealSegments(unittest.TestCase):
    """Segmenti Whisper reali: ricostruiti post-hoc dagli hyp del banco
    (concatenando i pezzi consecutivi con gap < 1 s) e, se presenti, i
    segmenti nativi salvati da run_whisper.py --mode raw."""

    @classmethod
    def setUpClass(cls):
        cls.segs = []
        raw_dir = C.WORK / 'raw'
        for p in sorted(raw_dir.glob('*.json'))[:60] if raw_dir.exists() else []:
            cls.segs.extend(json.loads(p.read_text(encoding='utf-8'))['segments'])
        hyp_dir = C.ASR_WORK / 'hyp' / 'whisper__vocals'
        for p in sorted(hyp_dir.glob('*.json'))[:40] if hyp_dir.exists() else []:
            segs = json.loads(p.read_text(encoding='utf-8'))['segments']
            cur = None
            for s in segs:
                if not s.get('words'):
                    continue
                if cur and s['start'] - cur['end'] < 1.0:
                    cur['words'] = cur['words'] + s['words']
                    cur['end'] = s['end']
                    cur['text'] = cur['text'] + ' ' + s['text']
                else:
                    if cur:
                        cls.segs.append(cur)
                    cur = {'start': s['start'], 'end': s['end'], 'text': s['text'], 'words': list(s['words'])}
            if cur:
                cls.segs.append(cur)

    def test_invariants_on_real(self):
        if not self.segs:
            self.skipTest('nessun dato reale disponibile')
        n_split = 0
        for seg in self.segs:
            pieces = NS.sentence_aware_split(seg)
            self.assertIsNotNone(pieces)
            if len(seg['text']) <= 80 and seg['end'] - seg['start'] <= 6.0:
                self.assertEqual(pieces, ORIG(seg))
                continue
            n_split += 1
            check_invariants(self, seg, pieces)
            if seg['text'] == ''.join(w['word'] for w in seg['words']).strip():
                # testo del segmento Whisper conservato esattamente (niente
                # parole spezzate come "post -traumatic")
                self.assertEqual(' '.join(p['text'] for p in pieces), seg['text'])
        self.assertGreater(n_split, 20)


class TestEngineHook(unittest.TestCase):
    """Il metodo REALE del motore (estratto dal sorgente) con finta config."""

    @classmethod
    def setUpClass(cls):
        cls.segs = []
        raw_dir = C.WORK / 'raw'
        for p in sorted(raw_dir.glob('*.json')) if raw_dir.exists() else []:
            cls.segs.extend(json.loads(p.read_text(encoding='utf-8'))['segments'])
        s = ("I told you already that we can't stay here tonight. The storm is coming "
             "and the roads will be closed by midnight. We have to leave now, before it gets dark.")
        cls.segs.append(mkseg(s.split()))
        cls.segs.append({'start': 0.0, 'end': 20.0, 'text': 'x' * 200, 'words': []})
        cls.segs.append({'start': 0.0, 'end': 20.0, 'text': 'x' * 200})

    def test_option_off_bit_identical(self):
        for flag in (False, None):
            split = TS.engine_method(flag)
            for seg in self.segs:
                self.assertEqual(split(seg), ORIG(seg))

    def test_option_off_does_not_import_module(self):
        boom = types.ModuleType('boom')   # nessun attributo: l'import fallirebbe
        split = TS.engine_method(False, new_module=boom)
        seg = self.segs[-3]
        self.assertEqual(split(seg), ORIG(seg))

    def test_option_on_uses_new_split(self):
        split = TS.engine_method(True)
        seg = self.segs[-3]
        self.assertEqual(split(seg), NS.sentence_aware_split(seg))
        self.assertNotEqual(split(seg), ORIG(seg))

    def test_option_on_exception_falls_back(self):
        bad = types.ModuleType('bad')

        def raise_(*a, **k):
            raise ValueError('boom')
        bad.sentence_aware_split = raise_
        bad.validate_split = NS.validate_split
        split = TS.engine_method(True, new_module=bad)
        for seg in self.segs[-3:]:
            self.assertEqual(split(seg), ORIG(seg))

    def test_option_on_invalid_result_falls_back(self):
        bad = types.ModuleType('bad')
        bad.sentence_aware_split = lambda seg, *a, **k: [{'start': 0, 'end': 1, 'text': 'x', 'words': []}]
        bad.validate_split = NS.validate_split
        split = TS.engine_method(True, new_module=bad)
        seg = self.segs[-3]
        self.assertEqual(split(seg), ORIG(seg))
        bad.sentence_aware_split = lambda seg, *a, **k: None
        self.assertEqual(split(seg), ORIG(seg))
        # parola persa -> non valido
        bad.sentence_aware_split = lambda seg, *a, **k: NS.sentence_aware_split(
            dict(seg, words=seg['words'][:-1], text=''.join(w['word'] for w in seg['words'][:-1]).strip()))
        self.assertEqual(split(seg), ORIG(seg))

    def test_option_on_real_segments_valid(self):
        split = TS.engine_method(True)
        for seg in self.segs:
            out = split(seg)
            flat = [w for p in out for w in p.get('words', [])]
            self.assertEqual(len(flat), len(seg.get('words') or []))

    def test_validate_rejects(self):
        seg = self.segs[-3]
        good = NS.sentence_aware_split(seg)
        self.assertTrue(NS.validate_split(seg, good))
        self.assertFalse(NS.validate_split(seg, []))
        self.assertFalse(NS.validate_split(seg, good[::-1]))
        dup = [dict(good[0])] + good
        self.assertFalse(NS.validate_split(seg, dup))
        altered = [dict(good[0], text=good[0]['text'] + ' X')] + good[1:]
        self.assertFalse(NS.validate_split(seg, altered))


if __name__ == '__main__':
    unittest.main()
