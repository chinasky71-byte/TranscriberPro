import random
import unittest

import _common  # noqa: F401
import stats as ST


class TestWilcoxon(unittest.TestCase):
    def test_n5_all_positive(self):
        w, p, n = ST.wilcoxon_exact([0.01, 0.02, 0.03, 0.04, 0.05])
        self.assertEqual((w, n), (15.0, 5))
        self.assertAlmostEqual(p, 0.0625, places=10)
        self.assertAlmostEqual(ST.min_p_wilcoxon(5), 0.0625)

    def test_against_scipy_no_ties(self):
        from scipy.stats import wilcoxon
        rng = random.Random(7)
        for n in range(1, 16):
            for _ in range(5):
                x = [rng.uniform(-1, 1) for _ in range(n)]
                if n < 2:
                    continue
                _, p, _ = ST.wilcoxon_exact(x)
                ref = wilcoxon(x, method='exact', alternative='two-sided').pvalue
                self.assertAlmostEqual(p, ref, places=10, msg=str(x))

    def test_ties_and_zeros(self):
        w, p, n = ST.wilcoxon_exact([0, 1, 1, -1, 2, 2, 2])
        self.assertEqual(n, 6)
        self.assertTrue(0 < p <= 1)
        # simmetria: invertire i segni non cambia p
        _, p2, _ = ST.wilcoxon_exact([0, -1, -1, 1, -2, -2, -2])
        self.assertAlmostEqual(p, p2)


class TestBootstrap(unittest.TestCase):
    def setUp(self):
        rng = random.Random(3)
        self.films = {f"f{i}": [(rng.randint(40, 60), rng.randint(30, 45), 300) for _ in range(10)]
                      for i in range(9)}

    def test_ci_contains_mean_and_is_deterministic(self):
        g = ST.mean_gain(self.films)
        lo, hi = ST.bootstrap_gain(self.films, 2000, seed=1)
        self.assertLess(lo, g)
        self.assertGreater(hi, g)
        self.assertEqual((lo, hi), ST.bootstrap_gain(self.films, 2000, seed=1))
        self.assertGreater(lo, 0)

    def test_decide_en(self):
        guard = {'halluc_per_h': 1.0, 'missed_pct': 2.0, 'names_pct': 90.0}
        d = ST.decide_en(self.films, dict(list(self.films.items())[:4]), guard, guard, 0.17, 0,
                         rules={**ST.DECISION_RULES, 'bootstrap_n': 1000})
        self.assertEqual(d['verdict'], 'CAMBIO_PROPOSTO', d['reasons'])
        bad = {'halluc_per_h': 5.0, 'missed_pct': 2.0, 'names_pct': 90.0}
        d = ST.decide_en(self.films, self.films, guard, bad, 0.17, 0, rules={**ST.DECISION_RULES, 'bootstrap_n': 500})
        self.assertEqual(d['verdict'], 'PAREGGIO')
        d = ST.decide_en(dict(list(self.films.items())[:5]), {}, guard, guard, 0.17, 0)
        self.assertEqual(d['verdict'], 'INSUFFICIENTE')
        d = ST.decide_en(self.films, self.films, guard, guard, 0.17, 3)
        self.assertEqual(d['verdict'], 'NON_VALUTABILE')

    def test_guard_interpretation(self):
        self.assertEqual(ST.guard_violations({'halluc_per_h': 0.0}, {'halluc_per_h': 1.5}), [])
        self.assertTrue(ST.guard_violations({'halluc_per_h': 0.0}, {'halluc_per_h': 2.5}))
        self.assertEqual(ST.guard_violations({'halluc_per_h': 10.0}, {'halluc_per_h': 14.0}), [])

    def test_decide_it_indicative(self):
        films = {'a': [(50, 40, 300)], 'b': [(60, 50, 300)], 'c': [(55, 45, 300)]}
        origin = {'a': 'doppiato', 'b': 'doppiato', 'c': 'nato_ita'}
        g = {'halluc_per_h': 0.0, 'missed_pct': 1.0, 'names_pct': 90.0}
        d = ST.decide_it(films, origin, g, g, 0.18, 0, rules={**ST.DECISION_RULES, 'bootstrap_n': 200})
        self.assertEqual(d['verdict'], 'INDICATIVO_SFIDANTE')
        films['c'] = [(40, 45, 300)]
        d = ST.decide_it(films, origin, g, g, 0.18, 0, rules={**ST.DECISION_RULES, 'bootstrap_n': 200})
        self.assertEqual(d['verdict'], 'INDICATIVO_PAREGGIO')


if __name__ == '__main__':
    unittest.main()
