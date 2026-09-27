"""Test della lingua sorgente nel prompt del traduttore LLM (nessun modello, nessuna GPU).

Copre: (a) default -> il motore riceve 'en'; (b) source_lang='fr' -> 'fr';
(c) motori con firma vecchia (senza src_lang e/o senza budget) continuano a
funzionare; (d) la scelta dell'etichetta in LLMSubtitleTranslator.
Esecuzione:  venv\\Scripts\\python.exe -m unittest test_llm_source_label -v   (dalla cartella del progetto)"""
import os
import unittest
from unittest import mock

from core.llm_subtitle_translator.prompt_builder import SubtitleUnit
from core.llm_subtitle_translator.translator import SubtitleLLMTranslator
from core.translator import LLMSubtitleTranslator


class FakeEngine:
    """Motore finto: registra gli argomenti di mt_messages e risponde a generate()."""

    def __init__(self):
        self.calls = []

    def mt_messages(self, text, src_lang="en", tgt_lang="it", budget=0):
        self.calls.append({"text": text, "src_lang": src_lang,
                           "tgt_lang": tgt_lang, "budget": budget})
        return [{"role": "user", "content": [{
            "type": "text", "source_lang_code": src_lang,
            "target_lang_code": tgt_lang, "text": text}]}]

    def generate(self, conversations, max_new_tokens=512, **overrides):
        return ["Ciao a tutti, come state oggi"] * len(conversations)


class OldSignatureEngine:
    """Firma vecchia: solo il testo (nessun src_lang, nessun budget)."""

    def __init__(self):
        self.calls = []

    def mt_messages(self, text):
        self.calls.append(text)
        return [{"role": "user", "content": text}]


class BudgetOnlyEngine:
    """Firma intermedia: budget ma non src_lang."""

    def __init__(self):
        self.calls = []

    def mt_messages(self, text, budget=0):
        self.calls.append((text, budget))
        return [{"role": "user", "content": text}]


def make_translator(engine, **kw):
    # Il gestore batch adattivo guarderebbe la GPU: qui non serve.
    with mock.patch.object(SubtitleLLMTranslator, "_make_batch_manager",
                           return_value=None):
        return SubtitleLLMTranslator(engine=engine, **kw)


UNIT = SubtitleUnit(id=1, text="Bonjour tout le monde, comment allez-vous ?",
                    duration=2.0)


class MtPromptTests(unittest.TestCase):
    def test_default_e_en(self):
        eng = FakeEngine()
        tr = make_translator(eng)
        self.assertEqual(tr.source_lang, "en")
        msgs = tr._mt_prompt(UNIT)
        self.assertEqual(eng.calls[-1]["src_lang"], "en")
        self.assertEqual(msgs[0]["content"][0]["source_lang_code"], "en")
        self.assertEqual(eng.calls[-1]["budget"], UNIT.budget)

    def test_source_lang_fr(self):
        eng = FakeEngine()
        tr = make_translator(eng, source_lang="fr")
        msgs = tr._mt_prompt(UNIT)
        self.assertEqual(eng.calls[-1]["src_lang"], "fr")
        self.assertEqual(eng.calls[-1]["tgt_lang"], "it")
        self.assertEqual(eng.calls[-1]["budget"], UNIT.budget)
        self.assertEqual(msgs[0]["content"][0]["source_lang_code"], "fr")

    def test_istanza_senza_init(self):
        """Costruita con __new__ (come nelle sonde): ricade su 'en'."""
        eng = FakeEngine()
        tr = SubtitleLLMTranslator.__new__(SubtitleLLMTranslator)
        tr.engine = eng
        tr._mt_prompt(UNIT)
        self.assertEqual(eng.calls[-1]["src_lang"], "en")

    def test_firma_vecchia_solo_testo(self):
        eng = OldSignatureEngine()
        tr = make_translator(eng, source_lang="fr")
        msgs = tr._mt_prompt(UNIT)
        self.assertEqual(eng.calls, [UNIT.text])
        self.assertEqual(msgs[0]["content"], UNIT.text)

    def test_firma_intermedia_budget_senza_lingua(self):
        eng = BudgetOnlyEngine()
        tr = make_translator(eng, source_lang="fr")
        tr._mt_prompt(UNIT)
        self.assertEqual(eng.calls, [(UNIT.text, UNIT.budget)])

    def test_motore_senza_mt_messages(self):
        """Ripiego storico: build_mt_messages, nessun errore."""
        tr = make_translator(object(), source_lang="fr")
        msgs = tr._mt_prompt(UNIT)
        self.assertIn(UNIT.text, msgs[0]["content"])

    def test_lingua_arriva_anche_al_retry_e_al_secondo_giro(self):
        """`translate` e `_translate_mt` (usato dal recupero L2) passano da _mt_prompt."""
        eng = FakeEngine()
        tr = make_translator(eng, source_lang="fr")
        tr._quiet_bar = True
        tr._translate_mt([UNIT])
        self.assertTrue(eng.calls)
        self.assertTrue(all(c["src_lang"] == "fr" for c in eng.calls))


class ResolveSourceLabelTests(unittest.TestCase):
    R = staticmethod(LLMSubtitleTranslator._resolve_source_label)

    def test_default_storico(self):
        self.assertEqual(LLMSubtitleTranslator.SOURCE_LABEL, "en")
        self.assertEqual(self.R("fr", "en"), "en")

    def test_auto_usa_la_lingua_reale(self):
        self.assertEqual(self.R("fr", None), "fr")
        self.assertEqual(self.R("fr", "auto"), "fr")

    def test_forzato(self):
        self.assertEqual(self.R("de", "fr"), "fr")
        self.assertEqual(self.R("de", "pt_BR"), "pt_BR")

    def test_etichetta_non_valida_ricade_su_en(self):
        for bad in ("", "  ", "francese lingua", "1234", "f"):
            self.assertEqual(self.R("fr", bad), "en", bad)
        # 'auto' con una lingua sorgente vuota/assente: stessa guardia.
        self.assertEqual(self.R("", None), "en")
        self.assertEqual(self.R(None, "auto"), "en")

    def test_codici_639_2_e_maiuscoli_diventano_639_1(self):
        # Le chiavi del chat template sono solo ISO 639-1 e sensibili alle maiuscole.
        for raw in ("FR", "fra", "fre", "French", " fr "):
            self.assertEqual(self.R("de", raw), "fr", raw)
        self.assertEqual(self.R("fre", "auto"), "fr")
        self.assertEqual(self.R("fra", None), "fr")

    def test_attributo_d_istanza_modificabile(self):
        tr = LLMSubtitleTranslator.__new__(LLMSubtitleTranslator)
        tr.source_label = LLMSubtitleTranslator.SOURCE_LABEL
        self.assertEqual(self.R("fr", tr.source_label), "en")
        tr.source_label = "fr"
        self.assertEqual(self.R("de", tr.source_label), "fr")
        self.assertEqual(LLMSubtitleTranslator.SOURCE_LABEL, "en")


class TemplateErrorTests(unittest.TestCase):
    def test_errore_del_template_risale_e_non_svuota_il_file(self):
        """Un prompt invalido e' deterministico: non va inghiottito batch dopo batch."""
        import jinja2

        class EngineTemplateRotto(FakeEngine):
            def generate(self, conversations, max_new_tokens=512, **overrides):
                raise jinja2.exceptions.UndefinedError("'dict object' has no attribute 'xyz'")

        tr = make_translator(EngineTemplateRotto(), source_lang="xyz")
        tr._quiet_bar = True
        with self.assertRaises(jinja2.TemplateError):
            tr._translate_mt([SubtitleUnit(id=1, text="Bonjour", duration=2.0)])


class ChatTemplateRealeTests(unittest.TestCase):
    """Compila il chat template VERO di TranslateGemma finale (CPU, sola lettura)."""
    TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models",
                            "translategemma-12b-it-finale", "chat_template.jinja")

    def _render(self, code):
        import jinja2
        env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
        env.globals["raise_exception"] = lambda m: (_ for _ in ()).throw(jinja2.TemplateError(m))
        tpl = env.from_string(open(self.TEMPLATE, encoding="utf-8").read())
        msgs = FakeEngine().mt_messages("Bonjour", src_lang=code)
        return tpl.render(messages=msgs, bos_token="<bos>", add_generation_prompt=True)

    @unittest.skipUnless(os.path.isfile(TEMPLATE), "modello finale non presente")
    def test_etichette_risolte_sono_accettate_dal_template(self):
        for raw in ("fr", "FR", "fra", "fre", "en", "it", "de", "es", "auto"):
            label = LLMSubtitleTranslator._resolve_source_label("fre", raw)
            out = self._render(label)
            self.assertIn("(" + label + ")", out, raw)

    @unittest.skipUnless(os.path.isfile(TEMPLATE), "modello finale non presente")
    def test_codice_assente_dal_template_solleva(self):
        import jinja2
        with self.assertRaises(jinja2.TemplateError):
            self._render("xyz")


if __name__ == "__main__":
    unittest.main()
