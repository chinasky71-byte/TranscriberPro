"""Regole v2 (prova confermativa): endpoint primari GEMBA + COMET, chrF descrittivo."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _common  # noqa: F401
from split_eval import decision_rules_split as V1
from split_eval import decision_rules_split_v2 as V2
from split_eval import score_split as SS


def summary(**kw):
    good = {'n_films': 8, 'n_windows': 40, 'gain': 1.0, 'ci_lo': 0.3, 'ci_hi': 1.7, 'wilcoxon_p': 0.01}
    bad_chrf = {**good, 'gain': -0.6, 'ci_lo': -1.3, 'ci_hi': 0.02, 'wilcoxon_p': 0.5}
    s = {'n_failed': 0, 'fp_hashes': ['a'], 'merges_without_midcut': 0, 'chrf_bf': bad_chrf,
         'chrf_bi': dict(bad_chrf), 'comet': {**good, 'gain': 0.03, 'ci_lo': 0.02},
         'empty_pct_bf': 0.0, 'dropped_pct_bf': 0.0, 'fallback_pct': 1.0, 'cps_high_pct_a': 20.0,
         'cps_high_pct_bf': 19.0, 'over84_pct_a': 5.0, 'over84_pct_bf': 1.0, 'imbalance_p90': 0.1,
         'untr_a': 0, 'untr_b': 0, 'neg_mean_abs_drift_bf': 0.0, 'neg_iso_changed': 0,
         'llm_unit_budget': ['']}
    s.update(kw)
    return s


def gemba(a, b, films=None, tie=5):
    films = films if films is not None else {f'f{i}': [3, 9, 0] for i in range(8)}
    return {'n': a + b + tie, 'pref_a': a, 'pref_b': b, 'tie': tie, 'mqm_a': 6.0, 'mqm_b': 4.0, 'per_film': films}


class TestV2(unittest.TestCase):
    def test_v1_unchanged_chrf_gate(self):
        d = SS.decide(summary(), gemba=gemba(80, 170), rules=V1.SPLIT_RULES)
        self.assertEqual(d['verdict'], 'ARCHIVIA')
        self.assertTrue(any('chrF' in r for r in d['reasons']))

    def test_v2_ignores_chrf_and_passes(self):
        d = SS.decide(summary(), gemba=gemba(80, 170), rules=V2.SPLIT_RULES)
        self.assertEqual(d['verdict'], 'PROPOSTA_PRODUZIONE', d['reasons'])

    def test_v2_gemba_share_too_low(self):
        d = SS.decide(summary(), gemba=gemba(120, 130), rules=V2.SPLIT_RULES)
        self.assertEqual(d['verdict'], 'ARCHIVIA')
        self.assertTrue(any('GEMBA: quota B' in r for r in d['reasons']))

    def test_v2_insufficient_decisive(self):
        d = SS.decide(summary(), gemba=gemba(30, 60), rules=V2.SPLIT_RULES)
        self.assertEqual(d['verdict'], 'INSUFFICIENTE')

    def test_v2_missing_gemba_is_insufficient(self):
        self.assertEqual(SS.decide(summary(), gemba=None, rules=V2.SPLIT_RULES)['verdict'], 'INSUFFICIENTE')

    def test_v2_film_majority_required(self):
        films = {f'f{i}': ([9, 3, 0] if i < 4 else [3, 9, 0]) for i in range(8)}   # B maggioranza in 4/8
        d = SS.decide(summary(), gemba=gemba(72, 108, films), rules=V2.SPLIT_RULES)
        self.assertEqual(d['verdict'], 'ARCHIVIA')
        self.assertTrue(any('film' in r and 'maggioranza' in r for r in d['reasons']))

    def test_v2_comet_must_pass(self):
        s = summary(comet={'n_films': 8, 'n_windows': 40, 'gain': 0.0, 'ci_lo': -0.01, 'ci_hi': 0.01, 'wilcoxon_p': 0.4})
        d = SS.decide(s, gemba=gemba(80, 170), rules=V2.SPLIT_RULES)
        self.assertEqual(d['verdict'], 'ARCHIVIA')

    def test_v2_guards_still_apply(self):
        d = SS.decide(summary(empty_pct_bf=3.0), gemba=gemba(80, 170), rules=V2.SPLIT_RULES)
        self.assertEqual(d['verdict'], 'ARCHIVIA')

    def test_binomial_exact(self):
        self.assertAlmostEqual(SS._binom_upper(10, 8), 56 / 1024)
        self.assertAlmostEqual(SS._binom_upper(4, 0), 1.0)

    def test_gemba_sample_is_seeded_and_excludes_dev(self):
        units = [{'id': i, 'win_id': f"en__x__{i:02d}" if i % 5 else f"en__x__dev{i}", 'film': 'x',
                  'source': 's', 'reference': '', 'a': 'a', 'b': 'b'} for i in range(1, 101)]
        with tempfile.TemporaryDirectory() as td, mock.patch.object(V2, 'GEMBA_SAMPLE_N', 20), \
                mock.patch.object(SS, 'DRS', V2):
            work = Path(td)
            (work / 'units_e.jsonl').write_text('\n'.join(json.dumps(u) for u in units), encoding='utf-8')
            src1, _, _, n1 = SS.gemba_inputs(work, 'e')
            ids1 = [json.loads(l)['id'] for l in src1.read_text(encoding='utf-8').splitlines()]
            _, _, _, n2 = SS.gemba_inputs(work, 'e')
            ids2 = [json.loads(l)['id'] for l in src1.read_text(encoding='utf-8').splitlines()]
        self.assertEqual((n1, n2), (20, 20))
        self.assertEqual(ids1, ids2)
        self.assertFalse(any(i % 5 == 0 for i in ids1))

    def test_rules_sha_follows_selected_module(self):
        from split_eval import translate_arms as TA
        with mock.patch.dict('os.environ', {'SPLIT_RULES_MODULE': 'split_eval.decision_rules_split_v2'}):
            sha_v2 = TA.rules_sha()
        self.assertNotEqual(sha_v2, TA.rules_sha())


if __name__ == '__main__':
    unittest.main()
