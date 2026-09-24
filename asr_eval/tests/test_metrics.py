import unittest

import numpy as np

import _common  # noqa: F401
import metrics as M


def seg(start, end, text, word_times=None):
    words = text.split()
    if word_times is None:
        step = (end - start) / len(words)
        word_times = [(start + i * step, start + (i + 1) * step) for i in range(len(words))]
    return {'start': start, 'end': end, 'text': text,
            'words': [{'start': a, 'end': b, 'word': ' ' + w} for w, (a, b) in zip(words, word_times)]}


def cue(s, e, text, music=False):
    return {'s': s, 'e': e, 'text': text, 'music': music, 'sound_only': False, 'italic': False}


class TestAlign(unittest.TestCase):
    def test_counts(self):
        c = M.count_ops(M.align('a b c d'.split(), 'a x c d e'.split()))
        self.assertEqual((c['C'], c['S'], c['D'], c['I']), (3, 1, 0, 1))
        c = M.count_ops(M.align('a b c'.split(), []))
        self.assertEqual((c['D'], c['I']), (3, 0))
        c = M.count_ops(M.align([], 'a b'.split()))
        self.assertEqual((c['D'], c['I']), (0, 2))
        c = M.count_ops(M.align('the cat sat on the mat'.split(), 'the cat sat on mat'.split()))
        self.assertEqual((c['S'], c['D'], c['I']), (0, 1, 0))

    def test_ops_indices(self):
        ops = M.align(['a', 'b'], ['b'])
        self.assertEqual(ops, [('D', 0, -1), ('C', 1, 0)])

    def test_edit_distance_is_minimal(self):
        import random
        rng = random.Random(1)
        for _ in range(200):
            a = [rng.choice('abc') for _ in range(rng.randint(0, 8))]
            b = [rng.choice('abc') for _ in range(rng.randint(0, 8))]
            c = M.count_ops(M.align(a, b))
            d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
            for i in range(len(a) + 1):
                for j in range(len(b) + 1):
                    if i == 0 or j == 0:
                        d[i][j] = i + j
                    else:
                        d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            self.assertEqual(c['S'] + c['D'] + c['I'], d[len(a)][len(b)])
            self.assertEqual(c['C'] + c['S'] + c['D'], len(a))


class TestWindow(unittest.TestCase):
    def test_perfect_and_fillers(self):
        cues = [cue(1, 3, "Hello John, how are you?"), cue(4, 6, "I'm fine.")]
        segs = [seg(1, 3, "Hello John, uh, how are you?"), seg(4, 6, "I am fine.")]
        r = M.score_window(cues, segs, 'en', names={'john'})
        self.assertEqual(r['werc'], 0.0)
        self.assertEqual(r['I'], 1)
        self.assertEqual((r['names_total'], r['names_hit']), (1, 1))

    def test_missed_line(self):
        cues = [cue(1, 3, "one two three four five"), cue(5, 7, "alpha beta gamma delta")]
        segs = [seg(1, 3, "one two three four five")]
        r = M.score_window(cues, segs, 'en')
        self.assertEqual(r['n_cues_ge3'], 2)
        self.assertEqual(r['n_missed'], 1)
        self.assertEqual(r['Dc'], 4)

    def test_music_dropped_both_sides(self):
        cues = [cue(1, 3, "real words here"), cue(10, 14, "♪ la la love song ♪", music=True)]
        segs = [seg(1, 3, "real words here"), seg(10, 14, "la la love song")]
        r = M.score_window(cues, segs, 'en')
        self.assertEqual((r['n_ref'], r['n_hyp'], r['werc']), (3, 3, 0.0))

    def test_hallucination_needs_silence_and_distance(self):
        cues = [cue(1, 3, "one two three")]
        rms = np.full(int(40 / 0.05), -20.0, dtype=np.float32)
        rms[int(20 / 0.05):int(30 / 0.05)] = -80.0
        segs = [seg(1, 3, "one two three"), seg(22, 25, "phantom words appear here")]
        r = M.score_window(cues, segs, 'en', rms_db=rms, dur_s=40)
        self.assertEqual(r['n_halluc'], 1)
        self.assertEqual(r['halluc_words'], 4)
        loud = np.full(int(40 / 0.05), -20.0, dtype=np.float32)
        r2 = M.score_window(cues, segs, 'en', rms_db=loud, dur_s=40)
        self.assertEqual(r2['n_halluc'], 0)
        segs_near = [seg(1, 3, "one two three"), seg(3.5, 5, "extra words nearby here")]
        r3 = M.score_window(cues, segs_near, 'en', rms_db=rms, dur_s=40)
        self.assertEqual(r3['n_halluc'], 0)

    def test_phantom_phrase(self):
        cues = [cue(1, 3, "one two three")]
        segs = [seg(1, 3, "one two three"), seg(3.2, 4, "thanks for watching")]
        r = M.score_window(cues, segs, 'en', rms_db=None)
        self.assertEqual(r['n_halluc'], 1)

    def test_numbers_and_timing(self):
        cues = [cue(2.0, 4.0, "I have 23 dollars")]
        segs = [seg(2.3, 4.0, "I have twenty-three dollars")]
        r = M.score_window(cues, segs, 'en')
        self.assertEqual(r['werc'], 0.0)
        self.assertEqual((r['num_total'], r['num_hit']), (2, 2))
        self.assertEqual(r['n_timing'], 1)
        self.assertAlmostEqual(r['timing_med_s'], 0.3, places=2)

    def test_segment_without_words(self):
        cues = [cue(1, 3, "a b c d")]
        segs = [{'start': 1, 'end': 3, 'text': 'a b c d', 'words': []}]
        self.assertEqual(M.score_window(cues, segs, 'en')['werc'], 0.0)


if __name__ == '__main__':
    unittest.main()
