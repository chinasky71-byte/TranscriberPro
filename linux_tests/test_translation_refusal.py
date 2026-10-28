# -*- coding: utf-8 -*-
"""ADR-009 — unico motore di traduzione (TranslateGemma-12B GGUF).

Il motore e' addestrato sulla sola coppia inglese→italiano. Una sorgente non
inglese non ha piu' un motore: la traduzione viene RIFIUTATA e dichiarata, mai
degradata in silenzio. Questi test fissano le due meta' della regola:

  - nessun instradamento automatico esiste piu' (il vecchio
    `route_non_english_away_from_llm` mandava FR/DE/ES su NLLB fine-tuned);
  - il punto di chiamata rifiuta PRIMA di costruire un traduttore, su entrambi
    i percorsi che traducono: STEP 6 della coda (`ProcessingPipeline`) e OCR
    bitmap (`core/ocr_auto.convert_and_translate`).

Esecuzione (dalla radice):  python -m pytest linux_tests/test_translation_refusal.py -q
"""
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.ocr_auto as ocr_auto  # noqa: E402
import core.pipeline as pipeline_mod  # noqa: E402
import core.translator as translator_mod  # noqa: E402


def test_instradamento_non_esiste_piu():
    """La funzione che sceglieva NLLB per le sorgenti non inglesi e' stata rimossa insieme al motore."""
    assert not hasattr(translator_mod, 'route_non_english_away_from_llm')
    assert not hasattr(pipeline_mod.ProcessingPipeline, '_route_non_english_away_from_llm')


def _bare_pipeline():
    """ProcessingPipeline senza __init__: la rifiuto scatta prima di ogni uso di
    config, VRAM, eventi. `_log` registra le righe per poterle controllare."""
    pipe = object.__new__(pipeline_mod.ProcessingPipeline)
    pipe.lines: list = []
    pipe._log = pipe.lines.append          # tipo: Callable[[str], None]
    return pipe


def test_sorgente_francese_rifiutata_senza_costruire_il_traduttore(monkeypatch):
    pipe = _bare_pipeline()
    chiamate = []
    monkeypatch.setattr(pipeline_mod, 'get_translator',
                        lambda *a, **k: chiamate.append((a, k)))
    out = pipe._translate_step(Path('/tmp/x.srt'), 'fra', 'ita')
    assert out == (Path('/tmp/x.srt'), 'fr', False, True)
    assert chiamate == []
    from utils.translations import tr
    attesa = tr('pl_translation_refused_non_english_source').format(src='fr')
    assert attesa in pipe.lines


def test_lingua_non_riconosciuta_rifiutata(monkeypatch):
    pipe = _bare_pipeline()
    monkeypatch.setattr(pipeline_mod, 'get_translator', lambda *a, **k: 1 / 0)
    out = pipe._translate_step(Path('/tmp/x.srt'), 'und', 'ita')
    assert out[1:] == ('und', False, True)


def test_ocr_non_inglese_rifiutato_senza_tradurre(tmp_path):
    video = tmp_path / 'film.mkv'
    ocr = mock.Mock()
    ocr.video_path = video
    ocr.write_sidecar.return_value = str(tmp_path / 'film.fr.srt')

    with mock.patch('core.translator.get_translator',
                    side_effect=AssertionError('traduttore costruito su sorgente non inglese')):
        ok = ocr_auto.convert_and_translate(
            ocr, events='1\n00:00:01,000 --> 00:00:02,000\nBonjour.\n',
            content_lang='fr')

    assert ok is False
    ocr.write_sidecar.assert_called_once()
    assert not (tmp_path / 'film.it.srt').exists()
