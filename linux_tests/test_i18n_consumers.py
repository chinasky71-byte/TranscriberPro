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
@pytest.mark.parametrize('key', ['logm_bar_translation', 'logm_bar_transcription', 'logm_bar_gender', 'logm_progress'])
def test_log_filter_barre_in_entrambe_le_lingue(lang, key):
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


def test_marcatori_non_vuoti():
    for k in TX['en']:
        if k.startswith('logm_'):
            assert all(t.strip() for t in all_texts(k)), k


# marcatore (logm_*) -> chiavi delle righe di log che lo devono contenere, IN OGNI LINGUA
MARKER_IN_LINES = {
    'logm_audio_extracted': ['pl_audio_extracted_language'],
    'logm_embedded_found': ['pl_embedded_subtitles_found_skipping_transcription'],
    'logm_model_line': ['pl_transcription_model'],
    'logm_ocr_failed': ['pl_bitmap_ocr_failed'],
    'logm_ocr_error': ['pl_bitmap_ocr_error'],
    'logm_ocr_done': ['pl_bitmap_ocr_completed'],
    'logm_kw_skip_translation': ['pl_6_original_language_target_language'],
    'logm_kw_skipped': ['pl_6_5_gender_correction_skipped'],
    'logm_kw_translation': ['pl_1b_bitmap_subtitles_ocr_translation'],
}


def test_ogni_riga_contiene_il_marcatore_che_il_consumatore_cerca():
    for marker, lines in MARKER_IN_LINES.items():
        for lang in ('it', 'en'):
            for lk in lines:
                assert TX[lang][marker].lower() in TX[lang][lk].lower(), (marker, lk, lang)


def test_righe_senza_traduzione_non_contengono_la_parola_chiave():
    for lang in ('it', 'en'):
        assert TX[lang]['logm_kw_translation'] not in TX[lang]['pl_1b_italian_bitmap_subtitles_ocr'].lower()
        assert TX[lang]['logm_kw_skipped'] not in TX[lang]['pl_6_5_grammatical_gender_correction'].lower()
        assert TX[lang]['logm_kw_skip_translation'] not in TX[lang]['pl_6_translation'].lower()
        assert TX[lang]['logm_kw_original_lang'] not in TX[lang]['pl_6_translation'].lower()


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_passi_6_e_6_5_con_le_righe_reali(lang):
    fp = FileProgress('ita')
    fp.feed(TX[lang]['pl_6_original_language_target_language'])
    assert 'translate' not in fp.possible and 'gender' not in fp.possible
    fp = FileProgress('ita')
    fp.feed(TX[lang]['pl_6_translation'].format(src='en', dst='it'))
    assert fp.phase == 'translate'
    fp.feed(TX[lang]['pl_6_5_gender_correction_skipped'])
    assert 'gender' not in fp.possible
    fp = FileProgress('ita')
    fp.feed(TX[lang]['pl_6_5_grammatical_gender_correction'])
    assert fp.phase == 'gender'


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_righe_reali_audio_ed_embedded(lang):
    fp = FileProgress('ita')
    fp.feed(TX[lang]['pl_audio_extracted_language'].format(lang='ita'))
    assert 'translate' not in fp.possible
    fp = FileProgress('ita')
    fp.feed(TX[lang]['pl_embedded_subtitles_found_skipping_transcription'].format(lang='ita'))
    assert 'asr' not in fp.possible and 'translate' not in fp.possible
    assert LogFilter().decide(TX[lang]['pl_transcription_model'].format(model='M1')).model_name == 'M1'
