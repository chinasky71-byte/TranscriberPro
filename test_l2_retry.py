"""Fase L2 di LLMSubtitleTranslator.translate_file: un blocco bocciato dal validatore al
primo giro (L1) e di nuovo al secondo (L2) NON deve essere accettato come "recuperato".
Nessun modello, nessuna GPU.
Esecuzione:  venv\\Scripts\\python.exe -m unittest test_l2_retry -v   (dalla cartella del progetto)"""
import unittest
from unittest import mock

from core.llm_subtitle_translator.prompt_builder import SubtitleUnit
from core.llm_subtitle_translator.translator import SubtitleLLMTranslator
from core.translator import LLMSubtitleTranslator

ISOLATE = LLMSubtitleTranslator._run_with_isolated_unresolved


class _FakeTranslator:
    """Un giro di traduzione che boccia sempre gli id in `bad`."""

    def __init__(self, already, bad):
        self.unresolved_ids = set(already)
        self.bad = set(bad)

    def run(self):
        self.unresolved_ids |= self.bad
        return {'ok': True}


class IsolatedUnresolvedTests(unittest.TestCase):
    def test_bocciato_in_l1_e_in_l2_resta_bocciato(self):
        # Il caso del difetto: id 5 gia' bocciato in L1, bocciato di nuovo in L2.
        t = _FakeTranslator(already={5}, bad={5})
        result, flagged = ISOLATE(t, t.run)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(flagged, {5})
        # Il vecchio delta lo avrebbe perso:
        self.assertEqual(({5} | {5}) - {5}, set())

    def test_solo_i_bocciati_di_questo_giro(self):
        t = _FakeTranslator(already={1, 2}, bad={3})
        _, flagged = ISOLATE(t, t.run)
        self.assertEqual(flagged, {3})

    def test_stato_ripristinato_come_unione(self):
        t = _FakeTranslator(already={1, 2}, bad={2, 3})
        ISOLATE(t, t.run)
        self.assertEqual(t.unresolved_ids, {1, 2, 3})

    def test_stato_ripristinato_anche_in_errore(self):
        t = _FakeTranslator(already={1}, bad=set())

        def boom():
            t.unresolved_ids.add(9)
            raise RuntimeError('generazione fallita')
        with self.assertRaises(RuntimeError):
            ISOLATE(t, boom)
        self.assertEqual(t.unresolved_ids, {1, 9})


class DegenerateEngine:
    """Motore finto: risponde sempre con un'uscita degenerata (ripetitiva)."""

    def mt_messages(self, text, src_lang="en", tgt_lang="it", budget=0):
        return [{"role": "user", "content": [{"type": "text", "source_lang_code": src_lang,
                                              "target_lang_code": tgt_lang, "text": text}]}]

    def generate(self, conversations, max_new_tokens=512, **kw):
        return ["So, so. So, so. So, so. So, so. So, so."] * len(conversations)


class RealTranslatorTests(unittest.TestCase):
    def test_translate_mt_reale_bocciato_due_volte(self):
        with mock.patch.object(SubtitleLLMTranslator, "_make_batch_manager", return_value=None):
            tr = SubtitleLLMTranslator(engine=DegenerateEngine())
        tr._quiet_bar = True
        unit = SubtitleUnit(id=78, text="So, so.", duration=2.0)
        tr.unresolved_ids.add(78)                      # bocciato gia' al primo giro (L1)
        _, flagged = ISOLATE(tr, lambda: tr._translate_mt([unit]))
        self.assertIn(78, flagged)


if __name__ == '__main__':
    unittest.main()
