"""Test di core/timing_aligner.py su dati sintetici (nessun video, nessuna GPU).
Esecuzione:  venv\\Scripts\\python.exe -m unittest test_timing_aligner -v   (dalla cartella del progetto)"""
import random
import unittest

import numpy as np

from core import timing_aligner as TA


def make_speech(seed=1, total=2400.0):
    """Battute sintetiche con pause irregolari (parlato tipico di un episodio)."""
    rnd = random.Random(seed)
    t, out = 5.0, []
    while t < total:
        d = rnd.uniform(1.0, 4.5)
        out.append((t, t + d))
        t += d + rnd.choice([rnd.uniform(0.2, 1.0), rnd.uniform(1.5, 9.0), rnd.uniform(10, 40)])
    return out


def errors(res, truth):
    return np.abs(np.array([a for a, _ in res.new_intervals]) - np.array([a for a, _ in truth]))


class TimingAlignerTests(unittest.TestCase):
    def setUp(self):
        self.truth = make_speech()
        self.ref = list(self.truth)

    def test_affine(self):
        ext = [(a * 1.001 + 3.5, b * 1.001 + 3.5) for a, b in self.truth]
        res = TA.align(ext, self.ref)
        self.assertLess(errors(res, self.truth).max(), 0.2)
        self.assertGreater(res.mean_coverage, 0.95)

    def test_framerate_ratio(self):
        r = 25 / 23.976
        ext = [(a * r + 2.0, b * r + 2.0) for a, b in self.truth]
        res = TA.align(ext, self.ref)
        self.assertLess(errors(res, self.truth).max(), 0.2)

    def test_jumps_beyond_old_window(self):
        """Cinque stacchi in avanti: l'offset cumulato (~130 s) supera la vecchia finestra di +-90 s."""
        cuts = [300, 700, 1100, 1500, 1900]
        sizes = [20, 35, 15, 40, 25]
        off = lambda x: sum(z for c, z in zip(cuts, sizes) if x >= c)
        ext = [(a + off(a), b + off(a)) for a, b in self.truth]
        res = TA.align(ext, self.ref)
        self.assertLess(errors(res, self.truth).max(), 0.5)

    def test_extra_scene_in_srt(self):
        ref = [(a, b) for a, b in self.truth if not (1200 <= a <= 1290)]
        ext = [(a + 4.0, b + 4.0) for a, b in self.truth]
        res = TA.align(ext, ref)
        self.assertLess(errors(res, self.truth).max(), 0.5)

    def test_missing_scene_in_srt(self):
        keep = [c for c in self.truth if not (1200 <= c[0] <= 1290)]
        ext = [(a - 6.0, b - 6.0) for a, b in keep]
        res = TA.align(ext, self.ref)
        self.assertLess(errors(res, keep).max(), 0.5)

    def test_jitter(self):
        rnd = random.Random(3)
        ext = []
        for a, b in self.truth:
            j = rnd.uniform(-0.3, 0.3)
            ext.append((a + 7.0 + j, b + 7.0 + j))
        res = TA.align(ext, self.ref)
        self.assertLess(errors(res, self.truth).max(), 0.7)

    def test_backward_jump_cannot_reorder_lines(self):
        """Un salto all'indietro piu' grande della pausa fra due battute e' vietato: l'ordine si conserva."""
        res = TA.align([(a + 3, b + 3) for a, b in self.truth], self.ref)
        starts = [a for a, _ in res.new_intervals]
        self.assertTrue(all(y >= x - 1e-6 for x, y in zip(starts, starts[1:])))

    def test_unrelated_reference_has_low_coverage(self):
        other = make_speech(seed=99)
        res = TA.align(self.truth, other)
        self.assertLess(res.mean_coverage, 0.8)

    def test_lift_separates_right_and_wrong_pairs(self):
        right = TA.align([(a + 3.5, b + 3.5) for a, b in self.truth], self.ref)
        wrong = TA.align(self.truth, make_speech(seed=99))
        self.assertGreater(right.lift, 0.85)
        self.assertLess(wrong.lift, 0.6)      # soglia di rifiuto per riferimento = sottotitoli

    def test_synchronizer_rejects_wrong_pair_and_accepts_right_one(self):
        from core.subtitle_synchronizer import SubtitleSynchronizer, SyncSubtitle
        sync = SubtitleSynchronizer.__new__(SubtitleSynchronizer)
        sync._switch_cost, sync._anchor_kind, sync.last_error, sync._log_callback = 5.0, 'sub', None, None
        mk = lambda iv: [SyncSubtitle(i + 1, SyncSubtitle._sec_to_ts(a), SyncSubtitle._sec_to_ts(b), 'x')
                         for i, (a, b) in enumerate(iv)]
        ext = mk([(a + 3.5, b + 3.5) for a, b in self.truth])
        self.assertIsNotNone(sync._step23_timing_align(mk(self.ref), ext))
        self.assertIsNone(sync._step23_timing_align(mk(make_speech(seed=99)), mk(self.truth)))
        self.assertRegex(sync.last_error, r'ERRORE|ERROR')    # il messaggio segue la lingua dell'interfaccia (IT/EN)

    def test_empty_inputs(self):
        self.assertIsNone(TA.align([], self.ref))
        self.assertIsNone(TA.align(self.truth, []))


if __name__ == '__main__':
    unittest.main()
