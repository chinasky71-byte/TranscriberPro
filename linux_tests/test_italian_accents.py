# -*- coding: utf-8 -*-
"""Apostrofi -> accenti nell'italiano (core/italian_accents.py + cleaner)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.italian_accents import count_fixes, fix_srt_text, fix_text  # noqa: E402
from core.subtitle_cleaner import SubtitleCleaner  # noqa: E402


def test_parole_note():
    assert fix_text("Si', e' cosi'.") == "Sì, è così."
    assert fix_text("Perche' no?") == "Perché no?"
    assert fix_text("Non puo' piu' venire") == "Non può più venire"
    assert fix_text("c'e' un problema") == "c'è un problema"
    assert fix_text("com'e' andata? dov'e'?") == "com'è andata? dov'è?"
    assert fix_text("la citta' e la qualita'") == "la città e la qualità"


def test_maiuscole_preservate():
    assert fix_text("E' vero.") == "È vero."
    assert fix_text("Si'.") == "Sì."
    assert fix_text("PERCHE'?") == "PERCHÉ?"


def test_forme_corrette_non_toccate():
    for text in ("un po' di pane", "d'accordo con te", "va' via", "sta' zitto",
                 "fa' presto", "da' retta", "di' la verita'", "be'", "vent'anni"):
        fixed = fix_text(text)
        assert "'" in fixed or "verità" in fixed, text          # l'apostrofo legittimo resta
    assert fix_text("vent'anni") == "vent'anni"
    assert fix_text("d'accordo") == "d'accordo"
    assert fix_text("un po'") == "un po'"


def test_testo_senza_apostrofi_invariato():
    text = "Nessuna modifica necessaria qui."
    assert fix_text(text) == text
    assert fix_text("") == ""


def test_srt_preserva_i_timestamp():
    srt = ("1\n00:00:01,000 --> 00:00:03,500\nE' andato via, perche' era tardi.\n")
    fixed = fix_srt_text(srt)
    assert "00:00:01,000 --> 00:00:03,500" in fixed
    assert "È andato via, perché era tardi." in fixed


def test_count_fixes():
    assert count_fixes("e' si' po'") == 2


def test_cleaner_con_e_senza_flag(tmp_path):
    source = tmp_path / "in.srt"
    source.write_text("1\n00:00:01,000 --> 00:00:03,000\nSi', e' cosi'.\n", encoding="utf-8")
    plain = tmp_path / "plain.srt"
    SubtitleCleaner.clean_file(source, plain)
    assert "Si'" in plain.read_text(encoding="utf-8")
    fixed = tmp_path / "fixed.srt"
    SubtitleCleaner.clean_file(source, fixed, italian_accents=True)
    text = fixed.read_text(encoding="utf-8")
    assert "Sì, è così." in text


def test_il_pipeline_attiva_gli_accenti_solo_per_italiano():
    """La correzione va all'uscita, non nel cleaner: quello gira prima della traduzione."""
    text = (ROOT / "core/pipeline.py").read_text(encoding="utf-8")
    assert "if final_language_639_1 == 'it':" in text
    assert "fix_srt_text(raw)" in text
    assert "italian_accents=_target" not in text          # niente correzione sul testo inglese


def test_contesto_asr_dal_glossario():
    """Il contesto per l'ASR viene dai nomi del glossario, e resta vuoto senza."""
    text = (ROOT / "core/pipeline.py").read_text(encoding="utf-8")
    assert "'asr_context': _context" in text
    engine = (ROOT / "core/engines/qwen3_asr_engine.py").read_text(encoding="utf-8")
    assert "context=self._context()" in engine
    from core.engines.qwen3_asr_engine import Qwen3AsrEngine
    engine_obj = object.__new__(Qwen3AsrEngine)

    class Cfg:
        def __init__(self, values):
            self.values = values

        def get(self, key, default=None):
            return self.values.get(key, default)

    engine_obj.config = Cfg({})
    assert engine_obj._context() == ""
    engine_obj.config = Cfg({"asr_context": " Borden, Lizzie "})
    assert engine_obj._context() == "Borden, Lizzie"
