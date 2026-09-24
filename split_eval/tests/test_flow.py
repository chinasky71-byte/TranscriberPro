"""Flusso completo build -> translate -> score -> report con un traduttore
FINTO (nessun modello, nessuna GPU), in una cartella temporanea: niente
viene scritto in asr_eval/work."""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

import _common
import asr_bench as AB
import runners as RN
import sandbox
from split_eval import decision_rules_split as DRS
from split_eval import prodmods, srtio
from split_eval import run_split_bench as RSB
from split_eval import score_split as SS
from split_eval import translate_arms as TA

SPLIT = [("After all, Dad tried to send her", "husband to jail."),
         ("I called my landlord and told him that", "the smell was getting worse."),
         ("We need to talk about", "the money you owe me.")]
WHOLE = ["Good morning.", "Where is the car?", "I don't know.", "Let's go home now.", "It is late."]


class FakeCfg:
    def __init__(self):
        self.settings = {'nllb_num_beams': 7, 'reservoir_engine': 'auto'}

    def get(self, k, d=None):
        return self.settings.get(k, d)


class StubTranslator:
    """Traduce parola per parola ('x' + parola), conserva righe e indici,
    applica la stessa rifinitura di produzione (postprocess.process) e scrive
    la riga di audit come BaseTranslator._log_audit."""
    calls = []

    def __init__(self):
        self.cb = None
        self.cleaned = False

    def set_log_callback(self, cb):
        self.cb = cb

    def translate_file(self, input_path, output_path, src_lang, tgt_lang, context=None):
        StubTranslator.calls.append((Path(input_path).name, src_lang, tgt_lang, context))
        subs = srtio.parse_like_translator(Path(input_path).read_text(encoding='utf-8'))
        texts = ['\n'.join(' '.join('x' + w for w in line.split()) for line in t.split('\n')) for _, _, _, t in subs]
        pp = prodmods.postprocess_module()
        res = pp.process({i: t for i, t in enumerate(texts)}, order=list(range(len(texts))))
        out = []
        for (idx, a, b, _), i in zip(subs, range(len(texts))):
            out += [str(idx), f"{a} --> {b}", res[i], '']
        Path(output_path).write_text('\n'.join(out), encoding='utf-8')
        self.cb("  Traduzione completata | riparati L1: 0 | recuperati L2: 0 | serbatoio L3: 0 | "
                "identici confermati: 0 | inglese residuo: 0")
        return True

    def cleanup(self):
        self.cleaned = True


def make_asr_work(root: Path, films=('filma-2020', 'filmb-2021'), per_film=3):
    asr = root / 'asr'
    wins, audit = [], {'films': {}}
    for fi, film in enumerate(films):
        it_cues_abs = []
        for k in range(per_film):
            t0 = 100.0 * (k + 1)
            segs, cues = [], []
            t = 1.0
            with_split = k != per_film - 1          # l'ultima finestra di ogni film: controllo negativo
            items = []
            if with_split:
                for a, b in SPLIT:
                    items += [(a, False), (b, True)]
            items += [(w, False) for w in WHOLE]
            for text, _cont in items:
                segs.append({'start': t, 'end': t + 2.0, 'text': text, 'words': []})
                cues.append({'s': t, 'e': t + 2.0, 'text': text, 'music': False, 'sound_only': False,
                             'italic': False})
                it_cues_abs.append((t0 + t, t0 + t + 2.0, 'ita ' + text))
                t += 2.6                              # gap 0,6 s: stessa scena, oltre MERGE_GAP del formatter
            wid = f"en__{film}__{k + 1:02d}"
            wins.append({'win_id': wid, 'film': film, 'lang': 'en', 'role': 'test', 'group': 'main',
                         'tag': f"{k + 1:02d}", 'idx': k + 1, 't0': t0, 't1': t0 + 60.0, 'dur': 60.0,
                         'sha': {'vocals': 'v' + wid, 'raw': 'r' + wid}, 'cues': cues})
            RN.write_json_atomic(asr / 'hyp' / 'canary__vocals' / f"{wid}.json",
                                 {'schema': RN.SCHEMA_HYP, 'win_id': wid, 'status': 'ok', 'wav_sha': 'v' + wid,
                                  'segments': segs})
        (asr / 'subs' / film).mkdir(parents=True, exist_ok=True)
        (asr / 'subs' / film / '7.srt').write_text(_common.srt(it_cues_abs), encoding='utf-8')
        audit['films'][film] = {'key': film, 'file': f'Z:/{film}.mkv', 'name': f'{film}.mkv', 'subs': [
            {'index': 7, 'lang': 'ita', 'kind': 'normal', 'text': True, 'codec': 'subrip', 'provenance': 'ok'}]}
    AB.write_jsonl_atomic(asr / 'windows.jsonl', wins)
    RN.write_json_atomic(asr / 'audit.json', audit)
    RN.write_json_atomic(asr / 'audit_overrides.json', {'tracks': {}})
    return asr


class TestFlow(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.asr = make_asr_work(root)
        self.work = root / 'split'
        StubTranslator.calls = []

    def tearDown(self):
        self.td.cleanup()

    def test_full_flow(self):
        rows = TA.build(self.work, self.asr, 'canary__vocals', extract_it=False, emit=lambda m: None)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r['status'] == 'ok' for r in rows), rows)
        by = {r['win_id']: r for r in rows}
        self.assertEqual(by['en__filma-2020__01']['n_merged_units'], 3)
        self.assertEqual(by['en__filma-2020__03']['n_merged_units'], 0)
        self.assertEqual(by['en__filma-2020__01']['midcut_fmt']['n_midcut'], 3)
        self.assertEqual(by['en__filma-2020__03']['midcut_fmt']['n_midcut'], 0)
        self.assertEqual(by['en__filma-2020__01']['it_ref_status'], 'ok')
        refs = json.loads((self.work / 'it_refs.json').read_text(encoding='utf-8'))
        self.assertTrue(refs['filma-2020']['sync']['ok'])
        units = srtio.parse_blocks((self.work / 'build' / 'en__filma-2020__01' / 'units.srt').read_text(encoding='utf-8'))
        self.assertIn('After all, Dad tried to send her husband to jail.', [u['text'] for u in units])

        rc = TA.translate(self.work, 'nllb_finetuned', factory=lambda e: StubTranslator(), cfg=FakeCfg(),
                          emit=lambda m: None)
        self.assertEqual(rc, 0)
        # firma reale della pipeline: codici 639-1, contesto None; A e B per ogni finestra
        self.assertEqual(len(StubTranslator.calls), 12)
        self.assertTrue(all(c[1:] == ('en', 'it', None) for c in StubTranslator.calls))
        res = json.loads((self.work / 'out' / 'nllb_finetuned' / 'en__filma-2020__01.json').read_text(encoding='utf-8'))
        self.assertEqual(res['status'], 'ok')
        mpos = set(res['merged_positions'])
        self.assertEqual(len(mpos), 6)
        for i, (a, bi, bf) in enumerate(zip(res['a_texts'], res['b_iso_texts'], res['b_full_texts'])):
            if i not in mpos:
                self.assertEqual(a, bi)            # b_iso: blocchi singoli presi da A (process idempotente)
                self.assertEqual(a, bf)            # traduttore deterministico: nessuna deriva
        # nessuna parola persa/duplicata nelle unita' fuse
        for mu in res['merged_units']:
            words_b = ' '.join(res['b_full_texts'][j] for j in mu['blocks']).split()
            words_u = res['units_translated'][str(mu['uid'])].split()
            self.assertEqual(words_b, words_u)
        self.assertEqual(res['times'], res['times_b'])
        self.assertEqual(res['audit']['A']['inglese residuo'], 0)
        # ripresa: una seconda chiamata non ritraduce nulla
        StubTranslator.calls = []
        TA.translate(self.work, 'nllb_finetuned', factory=lambda e: StubTranslator(), cfg=FakeCfg(),
                     emit=lambda m: None)
        self.assertEqual(StubTranslator.calls, [])

        rows = SS.score(self.work, emit=lambda m: None)
        self.assertEqual(len(rows), 6)
        r1 = next(r for r in rows if r['win_id'] == 'en__filma-2020__01')
        self.assertIsNotNone(r1['chrf_a'])
        self.assertEqual(r1['u_empty_bf'], 0)
        units = AB.read_jsonl(self.work / 'units_nllb_finetuned.jsonl')
        self.assertEqual(len(units), 3 * 4)
        self.assertTrue(all(u['reference'] for u in units))
        src, pa, pb, n = SS.gemba_inputs(self.work, 'nllb_finetuned')
        self.assertEqual(n, sum(1 for u in units if u['a'] != u['b']))
        rep = SS.build_report(self.work)
        self.assertIn('MOTORE nllb_finetuned', rep)
        self.assertIn('VERDETTO: INSUFFICIENTE', rep)
        self.assertIn('Midcut', rep)

        # CLI: report e midcut sulla cartella temporanea
        self.assertEqual(RSB.main(['x', '--work', str(self.work), '--asr-work', str(self.asr), 'report']), 0)
        self.assertTrue((self.work / 'report_split.txt').exists())
        self.assertEqual(RSB.main(['x', '--work', str(self.work), '--asr-work', str(self.asr), 'midcut']), 0)
        mc = json.loads((self.work / 'midcut.json').read_text(encoding='utf-8'))
        self.assertEqual(mc['hyp']['canary__vocals']['formatter']['n_midcut'], 3 * 4)

    def test_translate_refuses_busy_gpu_before_sandbox(self):
        orig = (AB.require_gpu_free, sandbox.activate)
        called = []

        def busy():
            raise SystemExit(3)
        AB.require_gpu_free = busy
        sandbox.activate = lambda *a, **k: called.append(1)
        try:
            with self.assertRaises(SystemExit):
                TA.translate(self.work, 'nllb_finetuned', emit=lambda m: None)
        finally:
            AB.require_gpu_free, sandbox.activate = orig
        self.assertEqual(called, [])

    def test_failed_window_when_indices_lost(self):
        TA.build(self.work, self.asr, 'canary__vocals', extract_it=False, emit=lambda m: None)

        class Lossy(StubTranslator):
            def translate_file(self, input_path, output_path, src_lang, tgt_lang, context=None):
                super().translate_file(input_path, output_path, src_lang, tgt_lang, context)
                txt = Path(output_path).read_text(encoding='utf-8').split('\n\n')
                Path(output_path).write_text('\n\n'.join(txt[:-2]), encoding='utf-8')
                return True
        rc = TA.translate(self.work, 'nllb_finetuned', limit=1, factory=lambda e: Lossy(), cfg=FakeCfg(),
                          emit=lambda m: None)
        self.assertEqual(rc, 6)
        res = json.loads(next((self.work / 'out' / 'nllb_finetuned').glob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(res['status'], 'failed')
        self.assertIn('braccio A', res['error'])


class TestDecide(unittest.TestCase):
    def base(self, **kw):
        good = {'n_films': 8, 'n_windows': 40, 'gain': 1.0, 'ci_lo': 0.3, 'ci_hi': 1.7, 'wilcoxon_p': 0.01}
        s = {'n_failed': 0, 'fp_hashes': ['a'], 'merges_without_midcut': 0, 'chrf_bf': dict(good),
             'chrf_bi': dict(good), 'comet': {**good, 'gain': 0.01, 'ci_lo': 0.002},
             'empty_pct_bf': 0.0, 'dropped_pct_bf': 0.0, 'fallback_pct': 1.0, 'cps_high_pct_a': 20.0,
             'cps_high_pct_bf': 21.0, 'over84_pct_a': 0.0, 'over84_pct_bf': 0.5, 'imbalance_p90': 0.1,
             'untr_a': 0, 'untr_b': 0, 'neg_mean_abs_drift_bf': 0.1, 'neg_iso_changed': 0}
        s.update(kw)
        return s

    def test_verdicts(self):
        self.assertEqual(SS.decide(self.base())['verdict'], 'PROPOSTA_PRODUZIONE')
        self.assertEqual(SS.decide(self.base(comet={'n_windows': 0, 'ci_lo': None}))['verdict'], 'INDICATIVO_B')
        self.assertEqual(SS.decide(self.base(empty_pct_bf=3.0))['verdict'], 'ARCHIVIA')
        self.assertEqual(SS.decide(self.base(neg_mean_abs_drift_bf=2.0))['verdict'], 'ARCHIVIA')
        self.assertEqual(SS.decide(self.base(chrf_bi={'gain': -0.5}))['verdict'], 'ARCHIVIA')
        self.assertEqual(SS.decide(self.base(), other={'chrf_bf': {'gain': -1.0}})['verdict'], 'ARCHIVIA')
        self.assertEqual(SS.decide(self.base(), gemba={'pref_a': 10, 'pref_b': 5})['verdict'], 'ARCHIVIA')
        self.assertEqual(SS.decide(self.base(n_failed=1))['verdict'], 'NON_VALUTABILE')
        self.assertEqual(SS.decide(self.base(merges_without_midcut=2))['verdict'], 'NON_VALIDO')
        self.assertEqual(SS.decide(self.base(), rules_changed=True)['verdict'], 'NON_VALIDO')
        small = self.base()
        small['chrf_bf'] = {**small['chrf_bf'], 'n_films': 3}
        self.assertEqual(SS.decide(small)['verdict'], 'INSUFFICIENTE')
        self.assertEqual(DRS.FROZEN_ON, '2026-09-24')

    def test_delta_stats(self):
        rows = [{'film': f, 'd': str(d)} for f, d in [('a', 1), ('a', 2), ('b', 1), ('c', 3), ('d', 2), ('e', 1),
                                                       ('f', 1)]]
        st = SS.delta_stats(rows, 'd')
        self.assertEqual((st['n_films'], st['n_windows']), (6, 7))
        self.assertAlmostEqual(st['gain'], (1.5 + 1 + 3 + 2 + 1 + 1) / 6)
        self.assertGreater(st['ci_lo'], 0)
        self.assertAlmostEqual(st['wilcoxon_p'], 2 / 64)


class TestBudgetPatch(unittest.TestCase):
    def test_patch_only_merged_units_and_restored(self):
        from core.llm_subtitle_translator import prompt_builder as PB
        self.assertNotIn('torch', sys.modules)
        u1 = PB.SubtitleUnit(id=1, text='x', duration=10.0)
        u2 = PB.SubtitleUnit(id=2, text='x', duration=10.0)
        self.assertEqual((u1.budget, u2.budget), (84, 84))
        with TA.llm_unit_budget_patch({1: 1, 2: 3}):
            self.assertEqual((u1.budget, u2.budget), (84, 170))
            self.assertEqual(PB.SubtitleUnit(id=2, text='x', duration=0).budget, 252)
        self.assertEqual(u2.budget, 84)


if __name__ == '__main__':
    unittest.main()
