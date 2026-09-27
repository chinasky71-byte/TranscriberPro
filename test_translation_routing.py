"""Instradamento automatico del motore di traduzione per sorgenti non inglesi (v1.25.0).
Nessun modello, nessuna GPU: solo la funzione pura di instradamento, condivisa fra
`core/pipeline.py` (coda principale) e `core/ocr_auto.py` (OCR bitmap, anche Library Scanner).
Esecuzione:  venv\\Scripts\\python.exe -m unittest test_translation_routing -v   (dalla cartella del progetto)"""
import unittest
from unittest import mock

from core.pipeline import ProcessingPipeline as PP
from core.translator import (LLMSubtitleTranslator, NLLBTranslator,
                             route_non_english_away_from_llm)


class RoutingTests(unittest.TestCase):
    """Sulla funzione condivisa: `core.pipeline.ProcessingPipeline._route_non_english_away_from_llm`
    e' solo un delegato di comodo, testato separatamente sotto."""

    def test_llm_su_sorgente_inglese_resta_llm(self):
        self.assertEqual(route_non_english_away_from_llm('llm', 'en'), 'llm')

    def test_llm_su_sorgente_francese_va_a_nllb_finetuned(self):
        self.assertEqual(route_non_english_away_from_llm('llm', 'fr'), 'nllb_finetuned')

    def test_alias_storico_aya_instradato_come_llm(self):
        self.assertEqual(route_non_english_away_from_llm('aya', 'de'), 'nllb_finetuned')

    def test_maiuscole_e_spazi_non_sfuggono_alla_regola(self):
        self.assertEqual(route_non_english_away_from_llm('LLM', 'fr'), 'nllb_finetuned')

    def test_altri_motori_non_toccati(self):
        # NLLB base, NLLB fine-tuned, Claude, OpenAI, OpenSubtitles dichiarano gia'
        # la lingua sorgente vera nel loro prompt: la scelta esplicita dell'utente resta.
        for motore in ('nllb', 'nllb_finetuned', 'claude', 'openai', 'opensubtitles'):
            self.assertEqual(route_non_english_away_from_llm(motore, 'fr'), motore)

    def test_valore_vuoto_o_none_non_esplode(self):
        self.assertEqual(route_non_english_away_from_llm('', 'fr'), '')
        self.assertIsNone(route_non_english_away_from_llm(None, 'fr'))

    def test_lingua_und_non_regredisce(self):
        # 'und' (lingua non riconosciuta) era gia' mappata a inglese sia da NLLB
        # sia da LLM prima di questa modifica: instradare non deve toglierle
        # copertura (route_non_english_away_from_llm la considera "non inglese"
        # e la manda a NLLB fine-tuned, che la accetta comunque: nessuna regressione).
        self.assertIn('und', NLLBTranslator.LANGUAGE_CODES)
        self.assertEqual(route_non_english_away_from_llm('llm', 'und'), 'nllb_finetuned')

    def test_ogni_codice_llm_e_coperto_da_nllb(self):
        # Invariante su cui si regge l'instradamento incondizionato: nessun
        # codice che LLMSubtitleTranslator accetta puo' mancare in NLLB
        # (altrimenti instradare "alla cieca" romperebbe una lingua che oggi
        # funziona). Se questo test rompe dopo aver aggiunto una lingua a
        # LLMSubtitleTranslator.LANGUAGE_CODES, aggiungerla anche a NLLB.
        mancanti = set(LLMSubtitleTranslator.LANGUAGE_CODES) - set(NLLBTranslator.LANGUAGE_CODES)
        self.assertEqual(mancanti, set())

    def test_delegato_su_processingpipeline_coerente(self):
        self.assertEqual(PP._route_non_english_away_from_llm('llm', 'fr'), 'nllb_finetuned')
        self.assertEqual(PP._route_non_english_away_from_llm('llm', 'en'), 'llm')


class OcrRoutingTests(unittest.TestCase):
    """Il percorso OCR bitmap (core/ocr_auto.py) chiama get_translator() a parte
    dallo STEP 6 di pipeline.py: deve applicare lo stesso instradamento."""

    def _run(self, content_lang):
        import tempfile
        from pathlib import Path
        import core.ocr_auto as OA

        calls = {}

        def fake_get_translator(model_type=None, **kw):
            calls['model_type'] = model_type
            t = mock.Mock()
            t.translate_file.return_value = True
            t.unload.return_value = None
            return t

        fake_cfg = mock.Mock()
        fake_cfg.get_translation_model.return_value = 'llm'

        with tempfile.TemporaryDirectory() as d:
            video_path = Path(d) / 'film.mkv'
            ocr = mock.Mock()
            ocr.video_path = video_path
            ocr.write_sidecar.return_value = str(video_path.with_name(f'film.{content_lang}.srt'))
            ocr._cfg.return_value = 'sidecar'   # WRITEBACK_SIDECAR: niente mux/writeback

            with mock.patch('core.translator.get_translator', side_effect=fake_get_translator), \
                 mock.patch('utils.config.get_config', return_value=fake_cfg), \
                 mock.patch('core.pgs_types.events_to_srt', return_value='1\n00:00:01,000 --> 00:00:02,000\nx\n'):
                OA.convert_and_translate(ocr, events=[object()], content_lang=content_lang)

        return calls.get('model_type')

    def test_ocr_instrada_sorgente_non_inglese_su_llm(self):
        self.assertEqual(self._run('fr'), 'nllb_finetuned')

    def test_ocr_non_tocca_sorgente_inglese(self):
        self.assertEqual(self._run('en'), 'llm')


if __name__ == '__main__':
    unittest.main()
