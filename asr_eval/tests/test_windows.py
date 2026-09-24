import random
import unittest

import numpy as np

import _common
import refs as R
import windows as W
from decision_rules import SYNC_RULES, WINDOW_RULES


def fake_film(duration=6000.0, seed=0):
    """Battute da 2-4 s con pause variabili; ogni tanto una pausa >= 1 s."""
    rng = random.Random(seed)
    cues, t = [], 5.0
    words = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu".split()
    while t < duration - 10:
        d = rng.uniform(1.5, 4.0)
        text = ' '.join(rng.choice(words) for _ in range(rng.randint(4, 9)))
        cues.append((t, t + d, text))
        t += d + (rng.uniform(1.1, 3.0) if rng.random() < 0.3 else rng.uniform(0.05, 0.5))
    return R.parse_srt_text(_common.srt(cues))


class TestSelect(unittest.TestCase):
    def test_synthetic(self):
        cues = fake_film()
        wins = W.select_windows(cues, 6000.0, 'en', WINDOW_RULES, 'film-x')
        self.assertEqual(len(wins), 10)
        pts = W.pause_points(cues, 1.0)
        for w in wins:
            self.assertTrue(120 <= w['t1'] - w['t0'] <= 180)
            self.assertTrue(0.04 * 6000 <= w['t0'] and w['t1'] <= 0.94 * 6000)
            self.assertIn(w['t0'], [round(p, 3) for p in pts])
            self.assertGreaterEqual(w['n_words'], 150)
            for c in cues:
                inside = c['s'] >= w['t0'] and c['e'] <= w['t1']
                outside = c['e'] <= w['t0'] or c['s'] >= w['t1']
                self.assertTrue(inside or outside, "battuta tagliata dal bordo")
        for a, b in zip(wins, wins[1:]):
            self.assertLessEqual(a['t1'], b['t0'])
        self.assertEqual(wins, W.select_windows(cues, 6000.0, 'en', WINDOW_RULES, 'film-x'))
        self.assertNotEqual(wins, W.select_windows(cues, 6000.0, 'en', WINDOW_RULES, 'film-y'))

    def test_dev_extra(self):
        cues = fake_film(seed=2)
        wins = W.select_windows(cues, 6000.0, 'it', WINDOW_RULES, 'or', n_extra=2)
        self.assertEqual(sum(w['role'] == 'dev' for w in wins), 2)
        self.assertEqual(sum(w['role'] == 'test' for w in wins), 10)

    def test_validity_rules(self):
        st = {'n_words': 200, 'music_frac': 0.2, 'sound_frac': 0.0, 'italic_frac': 0.0}
        self.assertFalse(W.window_valid(st, WINDOW_RULES))
        st.update(music_frac=0.05, italic_frac=0.31)
        self.assertFalse(W.window_valid(st, WINDOW_RULES))
        st.update(italic_frac=0.3, n_words=149)
        self.assertFalse(W.window_valid(st, WINDOW_RULES))

    @unittest.skipUnless((_common.REAL_WORK / 'subs' / 'office-romance-2026' / '24.srt').exists(),
                         "sub reale non estratto")
    def test_real_sub(self):
        cues = R.parse_srt(_common.REAL_WORK / 'subs' / 'office-romance-2026' / '24.srt')
        wins = W.select_windows(cues, 6890.911, 'it', WINDOW_RULES, 'office-romance-2026', n_extra=2)
        self.assertEqual(sum(w['role'] == 'test' for w in wins), 10)
        self.assertTrue(all(W.window_valid(w, WINDOW_RULES) for w in wins))


class TestSync(unittest.TestCase):
    def test_synthetic_shift(self):
        rng = np.random.default_rng(0)
        cues = fake_film(duration=400, seed=5)
        n = int(400 / W.FRAME_S)
        for true_off in (0.0, 1.2, -0.85, 2.5):
            rms = np.full(n, -70.0, dtype=np.float32) + rng.normal(0, 2, n).astype(np.float32)
            for c in cues:
                a, b = int((c['s'] + true_off) / W.FRAME_S), int((c['e'] + true_off - 0.3) / W.FRAME_S)
                rms[max(0, a):max(0, b)] = -20.0
            r = W.estimate_offset([(rms, cues, 0.0)], SYNC_RULES)
            # parlato 0,3 s piu' corto della battuta: centro del plateau a -0,15 s
            self.assertAlmostEqual(r['offset_s'], true_off - 0.15, delta=0.101)
            self.assertTrue(r['ok'])
            self.assertEqual(r['apply_s'] != 0.0, abs(true_off) > 0.3)

    def test_origin_shift(self):
        cues = [{'s': 100 + 3 * i, 'e': 101.5 + 3 * i} for i in range(30)]
        n = int(100 / W.FRAME_S)
        rms = np.full(n, -70.0, dtype=np.float32)
        for c in cues:
            a, b = int((c['s'] - 95 + 0.5) / W.FRAME_S), int((c['e'] - 95 + 0.5) / W.FRAME_S)
            rms[a:b] = -20
        r = W.estimate_offset([(rms, cues, 95.0)], SYNC_RULES)
        self.assertAlmostEqual(r['offset_s'], 0.5, delta=0.051)

    @unittest.skipUnless((_common.DESIGN / 'or_ita_audio.wav').exists(), "clip del progettista assente")
    def test_real_clip(self):
        rms = W.rms_db_from_wav(_common.DESIGN / 'or_ita_audio.wav')
        dur = len(rms) * W.FRAME_S
        reg = [c for c in R.parse_srt(_common.DESIGN / 'or_ita_regular.srt') if c['e'] < dur]
        for sh in (0.0, 1.2, -1.2):
            cs = [dict(c, s=c['s'] + sh, e=c['e'] + sh) for c in reg]
            r = W.estimate_offset([(rms, cs, 0.0)], SYNC_RULES)
            self.assertAlmostEqual(r['offset_s'], -sh, delta=0.151, msg=str(r))
            self.assertGreater(r['phi'], 0.3)


if __name__ == '__main__':
    unittest.main()
