"""Colonne e sezione 'frasi spezzate' (midcut, split_eval/midcut.py) nel banco."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

import _common  # noqa: F401
import asr_bench as AB
import metrics as M


def seg(s, e, text):
    return {'start': s, 'end': e, 'text': text, 'words': []}


def cue(s, e, text):
    return {'s': s, 'e': e, 'text': text, 'music': False, 'sound_only': False, 'italic': False}


class TestMidcutColumns(unittest.TestCase):
    SEGS = [seg(0, 2, 'After all, Dad tried to send her'), seg(2.6, 4.6, 'husband to jail.'),
            seg(5.2, 7.2, 'Good morning.')]
    CUES = [cue(0, 2, 'After all, Dad tried to send her'), cue(2.6, 4.6, 'husband to jail.'),
            cue(5.2, 7.2, 'Good morning.')]

    def test_score_window_fields(self):
        r = M.score_window(self.CUES, self.SEGS, 'en')
        self.assertEqual((r['hyp_midcut_n'], r['hyp_midcut_den']), (1, 3))
        self.assertEqual((r['ref_midcut_n'], r['ref_midcut_den']), (1, 3))
        self.assertAlmostEqual(r['hyp_midcut'], round(1 / 3, 4))
        for k in ('hyp_midcut', 'ref_midcut', 'fmt_midcut'):
            self.assertIn(k, AB.SCORE_COLUMNS)

    def test_formatter_fields_with_fake_core(self):
        saved = sys.modules.get('core')
        sys.modules['core'] = types.ModuleType('core')      # come in test_flow_fake
        try:
            f = AB.fmt_midcut_fields(self.SEGS, 'en')
        finally:
            if saved is None:
                sys.modules.pop('core', None)
            else:
                sys.modules['core'] = saved
        self.assertEqual((f['fmt_midcut_n'], f['fmt_midcut_den']), (1, 3))
        self.assertNotIn('torch', sys.modules)
        self.assertEqual(AB.fmt_midcut_fields([], 'en')['fmt_midcut'], None)

    def test_report_section(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            row = {c: '' for c in AB.SCORE_COLUMNS}
            row.update(win_id='en__f__01', film='f', lang='en', role='test', group='main', engine='canary',
                       arm='vocals', status='ok', dur_s='60', n_ref_c='10', Sc='1', Dc='0', Ic='0',
                       hyp_midcut_n='2', hyp_midcut_den='20', fmt_midcut_n='1', fmt_midcut_den='10',
                       ref_midcut_n='3', ref_midcut_den='30')
            AB.write_csv_atomic(work / 'scores.csv', AB.SCORE_COLUMNS, [row])
            rep = AB.build_report(work)
        self.assertIn("Frasi spezzate (midcut", rep)
        self.assertIn('canary/vocals: segmenti 10.00  blocchi formatter 10.00  riferimento 10.00', rep)


if __name__ == '__main__':
    unittest.main()
