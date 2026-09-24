import unittest
from datetime import date

import _common
import refs as R
from decision_rules import IT_FIDELITY_MIN_WPM_EXCESS, IT_FIDELITY_TRANSLATION_LCS


class TestSrt(unittest.TestCase):
    def test_parse_flags(self):
        text = ('﻿1\r\n00:00:01,000 --> 00:00:02,500\r\n{\\an8}<i>Ciao</i>\r\n\r\n'
                '2\n00:00:03,000 --> 00:00:04,000\n♪ canzone ♪\n\n'
                '3\n00:00:05,000 --> 00:00:06,000\n[porta che sbatte]\n\n'
                '4\n00:00:07.000 --> 00:00:08,000\n- Io.\n- Tu.\n\n')
        cues = R.parse_srt_text(text)
        self.assertEqual(len(cues), 4)
        self.assertEqual((cues[0]['s'], cues[0]['e']), (1.0, 2.5))
        self.assertTrue(cues[0]['italic'])
        self.assertTrue(cues[1]['music'])
        self.assertTrue(cues[2]['sound_only'])
        self.assertFalse(cues[3]['sound_only'])
        self.assertEqual(cues[3]['text'], '- Io.\n- Tu.')

    def test_provenance(self):
        today = date(2026, 9, 24)
        s = lambda **t: {'tags': t}
        self.assertEqual(R.provenance(s(language='it', title='Regular - SRT'), 'x.mkv', today)[0], 'reject')
        self.assertEqual(R.provenance(s(language='it'), 'x.mkv', today)[0], 'reject')
        self.assertEqual(R.provenance(s(language='ita', _STATISTICS_WRITING_DATE_UTC='2026-07-02 04:21:15'),
                                      'Scordato-chinasky.mkv', today)[0], 'reject')
        self.assertEqual(R.provenance(s(language='ita', _STATISTICS_WRITING_DATE_UTC='2026-06-24 23:15:03'),
                                      'Office.mkv', today)[0], 'confirm')
        self.assertEqual(R.provenance(s(language='ita', _STATISTICS_WRITING_DATE_UTC='2025-05-24'),
                                      'x-chinasky.mkv', today)[0], 'ok')

    def test_kind_and_key(self):
        k = lambda title='', **d: R.sub_kind({'tags': {'title': title}, 'disposition': d})
        self.assertEqual(k('Dubtitle'), 'dubtitle')
        self.assertEqual(k('SDH'), 'sdh')
        self.assertEqual(k('Italiano [CC]'), 'sdh')
        self.assertEqual(k('NON UDENTI'), 'sdh')
        self.assertEqual(k('', hearing_impaired=1), 'sdh')
        self.assertEqual(k('Forced'), 'forced')
        self.assertEqual(k('Regular'), 'normal')
        self.assertEqual(R.sub_kind({'tags': {'NUMBER_OF_FRAMES': '5'}}), 'forced')
        self.assertEqual(R.film_key("Office Romance 2026 1080p FullHD WEBRip.mkv"), 'office-romance-2026')

    def test_lcs(self):
        self.assertEqual(R.lcs_len('a b c d'.split(), 'a c d e'.split()), 3)
        self.assertEqual(R.lcs_len([], ['a']), 0)

    def test_names(self):
        cues = [{'s': i, 'e': i + 1, 'text': t, 'music': False} for i, t in enumerate(
            ["Ciao, Rachael.", "Dov'è Rachael?", "Parla con Rachael e George.", "Rachael arriva.",
             "Il Presidente.", "Il presidente.", "Il presidente."])]
        names = R.names_from_cues(cues, 'it')
        self.assertIn('rachael', names)
        self.assertNotIn('presidente', names)

    @unittest.skipUnless((_common.DESIGN / 'or_ita_dub.srt').exists(), "file del progettista assenti")
    def test_fidelity_office_romance(self):
        dub = R.parse_srt(_common.DESIGN / 'or_ita_dub.srt')
        reg = R.parse_srt(_common.DESIGN / 'or_ita_regular.srt')
        f = R.fidelity_it(dub, reg, {'translation_lcs': IT_FIDELITY_TRANSLATION_LCS,
                                     'min_wpm_excess': IT_FIDELITY_MIN_WPM_EXCESS})
        self.assertEqual(f['decision'], 'candidato')
        self.assertTrue(0.45 <= f['lcs_share_cand'] <= 0.65, f)
        self.assertTrue(0.55 <= f['lcs_share_normal'] <= 0.72, f)
        same = R.fidelity_it(reg, reg, {'translation_lcs': 0.85, 'min_wpm_excess': 0.10})
        self.assertEqual(same['decision'], 'traduzione')

    @unittest.skipUnless((_common.DESIGN / 'or_eng.srt').exists(), "file del progettista assenti")
    def test_en_choice(self):
        en = R.parse_srt(_common.DESIGN / 'or_eng.srt')
        self.assertEqual(R.en_choice(en, en, 0.95)['use'], 'normal')
        self.assertEqual(R.en_choice(en, None, 0.95)['use'], 'normal')
        self.assertEqual(R.en_choice(en[:300], en, 0.95)['use'], 'sdh')


if __name__ == '__main__':
    unittest.main()
