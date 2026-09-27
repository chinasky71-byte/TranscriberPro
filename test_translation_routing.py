"""Instradamento automatico del motore di traduzione per sorgenti non inglesi (v1.25.0).
Nessun modello, nessuna GPU: solo la funzione pura di instradamento.
Esecuzione:  venv\\Scripts\\python.exe -m unittest test_translation_routing -v   (dalla cartella del progetto)"""
import unittest

from core.pipeline import ProcessingPipeline as PP


class RoutingTests(unittest.TestCase):
    def test_llm_su_sorgente_inglese_resta_llm(self):
        self.assertEqual(PP._route_non_english_away_from_llm('llm', 'en'), 'llm')

    def test_llm_su_sorgente_francese_va_a_nllb_finetuned(self):
        self.assertEqual(PP._route_non_english_away_from_llm('llm', 'fr'), 'nllb_finetuned')

    def test_alias_storico_aya_instradato_come_llm(self):
        self.assertEqual(PP._route_non_english_away_from_llm('aya', 'de'), 'nllb_finetuned')

    def test_maiuscole_e_spazi_non_sfuggono_alla_regola(self):
        self.assertEqual(PP._route_non_english_away_from_llm('LLM', 'fr'), 'nllb_finetuned')

    def test_altri_motori_non_toccati(self):
        # NLLB base, NLLB fine-tuned, Claude, OpenAI, OpenSubtitles dichiarano gia'
        # la lingua sorgente vera nel loro prompt: la scelta esplicita dell'utente resta.
        for motore in ('nllb', 'nllb_finetuned', 'claude', 'openai', 'opensubtitles'):
            self.assertEqual(PP._route_non_english_away_from_llm(motore, 'fr'), motore)

    def test_valore_vuoto_o_none_non_esplode(self):
        self.assertEqual(PP._route_non_english_away_from_llm('', 'fr'), '')
        self.assertEqual(PP._route_non_english_away_from_llm(None, 'fr'), None)


if __name__ == '__main__':
    unittest.main()
