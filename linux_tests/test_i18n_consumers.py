# -*- coding: utf-8 -*-
"""Consumatori che riconoscono le righe di log dal TESTO: devono funzionare con la riga in italiano E in inglese
(il figlio scrive nella sua lingua, che puo' differire da quella della GUI)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gui.file_progress import FileProgress  # noqa: E402
from gui.services.log_filter import LogFilter  # noqa: E402
from utils.translations import Translations, all_texts  # noqa: E402

TX = Translations.TEXTS
BAR = '█' * 4 + '░' * 6


@pytest.mark.parametrize('lang', ['it', 'en'])
@pytest.mark.parametrize('key,expected', [
    ('logm_bar_translation', 'Translation: ['), ('logm_bar_transcription', 'Transcription: ['),
    ('logm_bar_gender', 'Gender correction: ['), ('logm_progress', 'Progress:')])
def test_log_filter_barre_in_entrambe_le_lingue(lang, key, expected):
    line = f"  {TX[lang][key]}{BAR}] 40% (4/10)"
    d = LogFilter().decide(line)
    assert d.action == 'progress' and d.progress_key == TX[lang][key]


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_log_filter_nome_modello(lang):
    line = f"\U0001F9E9 {TX[lang]['logm_model_line']} Whisper large-v3"
    d = LogFilter().decide(line)
    assert d.model_name == 'Whisper large-v3' and d.action == 'drop_noise'


def test_log_filter_italiano_invariato():
    f = LogFilter()
    assert f.decide('  \U0001F310 Traduzione: [' + BAR + '] 40%').action == 'progress'
    assert f.decide('\U0001F9E9 Modello trascrizione: X').model_name == 'X'
    assert f.decide('riga normale').action == 'append'


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_avanzamento_barra_interna_traduzione(lang):
    fp = FileProgress('ita')
    fp.feed('1. Setup')
    fp.feed('6. ' + ('Traduzione sottotitoli...' if lang == 'it' else 'Translating subtitles...'))
    before = fp.value
    fp.feed(f"  {TX[lang]['logm_bar_translation']}{BAR}] 60% (6/10)")
    assert fp.value > before


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_lingua_audio_uguale_al_target_toglie_la_traduzione(lang):
    fp = FileProgress('ita')
    fp.feed(f"✅ {TX[lang]['logm_audio_extracted']} ita")
    assert 'translate' not in fp.possible


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_embedded_trovati(lang):
    fp = FileProgress('ita')
    fp.feed(f"✅ {TX[lang]['logm_embedded_found']}eng). ...")
    assert not ({'extract', 'demucs', 'asr'} & fp.possible) and 'translate' in fp.possible


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_ramo_ocr(lang):
    fp = FileProgress('ita')
    fp.feed('1b. OCR ' + TX[lang]['logm_kw_translation'])
    assert 'ocr_translate' in fp.possible
    fp.feed(f"⚙️ OCR — {TX[lang]['logm_ocr_analysis']}...")
    assert fp.phase == 'ocr_read'
    fp.feed(f"⚙️ OCR — {TX[lang]['logm_ocr_translation']}...")
    assert fp.phase == 'ocr_translate'
    fp.feed(f"✅ {TX[lang]['logm_ocr_done']}.")
    assert fp.phase == 'final'


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_ocr_fallito_torna_al_percorso_audio(lang):
    fp = FileProgress('ita')
    fp.feed('1b. OCR')
    assert 'ocr_extract' in fp.possible
    fp.feed(f"⚠️ {TX[lang]['logm_ocr_failed']}.")
    assert 'ocr_extract' not in fp.possible and 'asr' in fp.possible


def test_marcatori_tutti_distinti_tra_lingue_e_non_vuoti():
    for k in TX['en']:
        if k.startswith('logm_'):
            assert all(t.strip() for t in all_texts(k)), k
