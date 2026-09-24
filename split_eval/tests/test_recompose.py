import random
import unittest

import _common  # noqa: F401
from _common import blk
from split_eval import recompose as R


def roundtrip(blocks, translations, **cfg):
    units, mapping = R.recompose(blocks, cfg or None)
    tr = {u['uid']: translations(u) for u in units}
    out, rep = R.resplit(tr, mapping)
    return units, mapping, out, rep, tr


class TestRecompose(unittest.TestCase):
    def test_real_example(self):
        bl = [blk(10.0, 13.5, 'Sure, she is a bitch. But can you blame her?\nAfter all, Dad tried to send her'),
              blk(13.6, 15.2, 'husband to jail.'), blk(16.0, 17.0, 'Whatever.')]
        it = {1: "Certo, è una stronza. Ma puoi biasimarla? Dopo tutto, papà ha cercato di mandare "
                 "suo marito in prigione.", 2: 'Come vuoi.'}
        units, mapping = R.recompose(bl)
        self.assertEqual([u['blocks'] for u in units], [[0, 1], [2]])
        self.assertTrue(units[0]['text'].endswith('send her husband to jail.'))
        out, rep = R.resplit(it, mapping)
        self.assertEqual([(b['start'], b['end']) for b in out], [(10.0, 13.5), (13.6, 15.2), (16.0, 17.0)])
        self.assertIn('papà', out[0]['text'])
        self.assertIn('marito', out[1]['text'])
        self.assertFalse(rep['units'][0]['fallback'])
        self.assertTrue(R.check_invariant(it[1], [out[0]['text'], out[1]['text']]))
        self.assertEqual(out[2]['text'], 'Come vuoi.')
        for b in out:
            self.assertTrue(all(len(l) <= 42 for l in b['text'].split('\n')))
            self.assertLessEqual(len(b['text'].split('\n')), 2)

    def test_quotes_and_chain_of_three(self):
        bl = [blk(0, 1, 'He told me "I know that'), blk(1.1, 2, 'you were there'), blk(2.1, 3, 'and you lied."'),
              blk(3.2, 4, 'Then he left.')]
        units, mapping = R.recompose(bl)
        self.assertEqual([u['blocks'] for u in units], [[0, 1, 2], [3]])
        t = 'Mi ha detto "So che eri lì e hai mentito."'
        out, rep = R.resplit({1: t, 2: 'Poi se ne è andato.'}, mapping)
        self.assertTrue(R.check_invariant(t, [b['text'] for b in out[:3]]))
        self.assertTrue(all(b['text'] for b in out[:3]))

    def test_max_blocks(self):
        bl = [blk(i, i + 0.9, w) for i, w in enumerate(['one and', 'two and', 'three and', 'four and', 'five.'])]
        units, _ = R.recompose(bl, {'max_blocks': 3})
        self.assertEqual([u['blocks'] for u in units], [[0, 1, 2], [3, 4]])

    def test_never_across_speaker_dialogue_or_strong_punct(self):
        self.assertEqual(len(R.recompose([blk(0, 1, 'I think', speaker='A'),
                                          blk(1.1, 2, 'so too.', speaker='B')])[0]), 2)
        self.assertEqual(len(R.recompose([blk(0, 1, 'I think', speaker='A'),
                                          blk(1.1, 2, 'so too.', speaker='A')])[0]), 1)
        self.assertEqual(len(R.recompose([blk(0, 1, '- Hi.\n- I think'), blk(1.1, 2, 'so too.')])[0]), 2)
        self.assertEqual(len(R.recompose([blk(0, 1, 'Hi.'), blk(1.1, 2, 'and you?')])[0]), 2)
        self.assertEqual(len(R.recompose([blk(0, 1, 'I think'), blk(2.5, 3, 'so too.')])[0]), 2)   # gap
        self.assertEqual(len(R.recompose([blk(0, 1, 'I think'), blk(1.1, 2, 'Larry is here.')])[0]), 2)

    def test_italian_source(self):
        units, mapping = R.recompose([blk(0, 1, 'Non so se'), blk(1.1, 2, 'ce la faccio.')], {'lang': 'it'})
        self.assertTrue(units[0]['merged'])
        self.assertEqual(units[0]['text'], 'Non so se ce la faccio.')

    def test_singleton_text_identical(self):
        units, _ = R.recompose([blk(0, 1, 'Line one,\nline two.'), blk(3, 4, '- A.\n- B.')])
        self.assertEqual(units[0]['text'], 'Line one,\nline two.')
        self.assertEqual(units[1]['text'], '- A.\n- B.')

    def test_prefers_punctuation_and_avoids_articles(self):
        pieces, info = R.split_text('Quando sono arrivato, la porta era aperta.',
                                    ['When I arrived,', 'the door was open.'], [1.5, 1.5])
        self.assertEqual(pieces, ['Quando sono arrivato,', 'la porta era aperta.'])
        pieces, _ = R.split_text("Ho visto l'uomo con il cappello rosso.",
                                 ['I saw the man', 'with the red hat.'], [1.5, 1.5])
        self.assertFalse(pieces[0].endswith("l'"))
        self.assertNotIn(pieces[0].split()[-1].lower(), R.BAD_END['it'])

    def test_numbers_stay_with_unit(self):
        pieces, _ = R.split_text('Costa 20 dollari a notte, tasse incluse.',
                                 ['It costs 20', 'dollars a night, taxes included.'], [1.0, 2.0])
        self.assertFalse(pieces[0].endswith('20'))

    def test_fallback_policies(self):
        bl = [blk(0, 1, 'I think'), blk(1.1, 2, 'so too.')]
        units, mapping = R.recompose(bl)
        out, rep = R.resplit({1: 'Sì.'}, mapping)                      # 1 parola, 2 blocchi
        self.assertEqual([b['text'] for b in out], ['Sì.', ''])
        self.assertEqual(rep['n_fallback'], 1)
        self.assertEqual((out[0]['end'], out[1]['drop']), (1, False))
        out, rep = R.resplit({1: 'Sì.'}, mapping, {**mapping['config'], 'fallback': 'span'})
        self.assertEqual((out[0]['end'], out[1]['drop'], out[1]['text']), (2, True, ''))
        out, rep = R.resplit({1: ''}, mapping)                          # traduzione vuota
        self.assertEqual([b['text'] for b in out], ['', ''])
        self.assertEqual(rep['n_empty_text'], 1)
        # scostamento eccessivo -> ripiego SOLO con la politica v1 'first'
        # (esplicita: dal 24/09 il default e' 'force', v. test_force_policy)
        pieces, info = R.split_text('uno due tre quattro cinque sei sette otto nove dieci.',
                                    ['a b c d e f g h i', 'j.'], [1, 1], {'max_dev': 0.01, 'fallback': 'first'})
        self.assertTrue(info['fallback'])
        self.assertEqual(pieces[1], '')

    def test_force_policy(self):
        """Default 'force': con lo scostamento oltre max_dev si taglia comunque
        (scostamento minimo), mai un blocco vuoto se ci sono abbastanza parole;
        il dev del taglio forzato resta nel report (non si nasconde)."""
        text = 'uno due tre quattro cinque sei sette otto nove dieci.'
        pieces, info = R.split_text(text, ['a b c d e f g h i', 'j.'], [1, 1], {'max_dev': 0.01})
        self.assertFalse(info['fallback'])
        self.assertTrue(info['forced'])
        self.assertTrue(all(pieces))
        self.assertTrue(R.check_invariant(text, pieces))
        self.assertTrue(info['dev'] and max(info['dev']) > 0.01)
        # parole < blocchi: il ripiego 'first' resta inevitabile anche in 'force'
        pieces, info = R.split_text('Tornerò.', ["I'll come", 'back.'], [1, 1])
        self.assertEqual((pieces, info['fallback']), (['Tornerò.', ''], True))

    def test_real_worst_cases_v2(self):
        """Casi REALI del banco v2 (work_conf, NLLB-FT) che la v1 mandava in
        ripiego (2o blocco vuoto) o tagliava lontano dalla proporzione."""
        cases = [  # (sorgenti EN, traduzione IT, pezzi attesi)
            (['Here we', 'go.'], 'Ci siamo.', ['Ci', 'siamo.']),
            (['but', 'her stories'], 'ma le sue storie', ['ma', 'le sue storie']),
            (['You think', 'not anymore.'], 'Non lo pensi più.', ['Non lo', 'pensi più.']),
            (['And', 'as far as I know, my house is the only.'],
             "E per quanto ne so, la mia casa è l'unica.",
             ['E', "per quanto ne so, la mia casa è l'unica."]),
            # apocope: dopo "po'" si puo' tagliare (prima era vietato come elisione)
            (['She was a', 'bit older than me, so when the\nresistance started, she signed up.'],
             "Era un po' più grande di me, quindi quando è iniziata la resistenza, si è arruolata.",
             ["Era un po'", 'più grande di me, quindi quando è iniziata la resistenza, si è arruolata.']),
        ]
        for src, it, want in cases:
            pieces, info = R.split_text(it, src, [1.0, 1.0])
            self.assertEqual(pieces, want, (src, it))
            self.assertFalse(info['fallback'])
            self.assertTrue(R.check_invariant(it, pieces))
        # v1 ('first') su "Here we | go." lasciava il blocco vuoto
        self.assertEqual(R.split_text('Ci siamo.', ['Here we', 'go.'], [1, 1], {'fallback': 'first'})[0],
                         ['Ci siamo.', ''])

    def test_elision_vs_apocope(self):
        self.assertIsNone(R._cut_bonus("l'", 'uomo', R.make_config()))
        self.assertIsNone(R._cut_bonus("dell'", 'anno', R.make_config()))
        self.assertIsNotNone(R._cut_bonus("po'", 'più', R.make_config()))
        self.assertIsNotNone(R._cut_bonus("'ciao'", 'disse', R.make_config()))
        pieces, _ = R.split_text("Ho visto l' uomo alto.", ['I saw the', 'tall man.'], [1, 1])
        self.assertFalse(pieces[0].endswith("l'"))

    def test_mirror_dangling_source(self):
        self.assertTrue(R.src_dangles('And', 'en'))
        self.assertTrue(R.src_dangles("It's", 'en'))
        self.assertFalse(R.src_dangles('I know,', 'en'))
        self.assertFalse(R.src_dangles('the house', 'en'))

    def test_edge_cases(self):
        units, mapping = R.recompose([])
        self.assertEqual((units, mapping['n_blocks']), ([], 0))
        self.assertEqual(R.resplit({}, mapping)[0], [])
        units, mapping = R.recompose([blk(0, 1, 'Alone')])
        out, _ = R.resplit({1: 'Solo'}, mapping)
        self.assertEqual(out[0]['text'], 'Solo')
        with self.assertRaises(KeyError):
            R.make_config({'nope': 1})
        with self.assertRaises(ValueError):
            R.make_config({'fallback': 'x'})
        self.assertEqual(R.make_config()['fallback'], 'force')

    def test_invariant_fuzz(self):
        rng = random.Random(7)
        vocab = "il la di che e non un per è con mi si ma lo casa, porta. sempre? ciao! l' 20 dollari".split()
        for _ in range(300):
            k = rng.randint(2, 3)
            src = [' '.join(rng.choice(['and', 'the', 'house', 'go', 'to']) for _ in range(rng.randint(1, 8)))
                   for _ in range(k)]
            text = ' '.join(rng.choice(vocab) for _ in range(rng.randint(0, 30)))
            durs = [rng.uniform(0.3, 4) for _ in range(k)]
            for pol in ('force', 'first'):
                pieces, info = R.split_text(text, src, durs, {'fallback': pol})
                self.assertEqual(len(pieces), k)
                self.assertTrue(R.check_invariant(text, pieces), (text, pieces))
                if not info['fallback'] and text.strip():
                    self.assertTrue(all(p for p in pieces))
                if pol == 'force' and len(text.split()) >= k:
                    # 'force': mai blocchi vuoti con abbastanza parole (salvo
                    # un testo fatto solo di elisioni staccate)
                    if not info['fallback']:
                        self.assertTrue(all(p for p in pieces))
                for p in pieces[:-1]:                     # mai un taglio dopo l' staccato
                    if p:
                        self.assertNotEqual(p.split()[-1], "l'")


if __name__ == '__main__':
    unittest.main()
