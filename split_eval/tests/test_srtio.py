import unittest

import _common  # noqa: F401
from split_eval import split_metrics as SM
from split_eval import srtio


class TestSrtio(unittest.TestCase):
    def test_roundtrip_with_digit_lines(self):
        blocks = [{'index': 1, 'start': 1.0, 'end': 2.0, 'text': 'Hello there\nsecond line'},
                  {'index': 2, 'start': 3.0, 'end': 4.0, 'text': '42'},
                  {'index': 5, 'start': 5.0, 'end': 6.5, 'text': 'Take\n10\nsteps'}]
        self.assertEqual(srtio.roundtrip_problems(blocks), [])
        back = srtio.parse_blocks(srtio.render(blocks))
        self.assertEqual([(b['index'], b['start'], b['end'], b['text']) for b in back],
                         [(b['index'], b['start'], b['end'], b['text']) for b in blocks])

    def test_render_skips_empty_and_drop(self):
        blocks = [{'start': 0, 'end': 1, 'text': 'a'}, {'start': 1, 'end': 2, 'text': ''},
                  {'start': 2, 'end': 3, 'text': 'b', 'drop': True}, {'start': 3, 'end': 4, 'text': 'c'}]
        self.assertEqual([b['text'] for b in srtio.parse_blocks(srtio.render(blocks, renumber=True))], ['a', 'c'])
        self.assertEqual(srtio.ts(3723.4567), '01:02:03,457')

    def test_chrf_own_matches_sacrebleu(self):
        pairs = [('Il gatto è sul tavolo.', 'Il gatto sta sul tavolo.'), ('ciao', 'arrivederci'),
                 ('Dopo tutto, papà ha cercato di mandare suo marito in prigione.',
                  "Dopotutto papà ha provato a far finire suo marito all'ergastolo.")]
        try:
            from sacrebleu.metrics import CHRF
        except ImportError:
            self.skipTest('sacrebleu assente')
        for h, r in pairs:
            self.assertAlmostEqual(SM.chrf_own(h, r), CHRF().sentence_score(h, [r]).score, places=6)

    def test_structural_and_untranslated(self):
        bl = [{'start': 0, 'end': 1, 'text': 'x' * 30}, {'start': 1, 'end': 2, 'text': ''},
              {'start': 2, 'end': 3, 'text': 'y' * 43 + '\n' + 'z' * 43}]
        st = SM.structural(bl, {1, 2})
        self.assertEqual((st['empty'], st['over84'], st['over_cpl'], st['cps_high']), (1, 1, 1, 2))
        self.assertEqual(st['in_units']['n'], 2)
        self.assertEqual(SM.untranslated_units({1: 'It was an Ark.', 2: 'Ok.'}, {1: 'It was an ark', 2: 'Ok.'}), [1])


if __name__ == '__main__':
    unittest.main()
