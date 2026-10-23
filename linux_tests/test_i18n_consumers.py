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


def test_righe_errore_del_sincronizzatore_iniziano_col_prefisso_in_ogni_lingua():
    """core/subtitle_synchronizer.py::_log imposta last_error se la riga inizia con il prefisso di errore."""
    prefixes = {lang: all_texts('logm_error_prefix') for lang in ('it', 'en')}
    for k, it_text in TX['it'].items():
        if k.startswith('sy_') and it_text.lstrip().startswith('ERRORE'):
            assert TX['en'][k].lstrip().startswith(prefixes['en']), k
    assert 'ERRORE' in prefixes['it'] and 'ERROR' in prefixes['it']


def test_nota_finestra_dell_allineatore_riconosciuta_in_ogni_lingua():
    for lang in ('it', 'en'):
        assert any(k in TX[lang]['ta_piecewise_offset_at_the_window'] for k in all_texts('logm_kw_window'))


MARKER_IN_LINES.update({
    'logm_bar_translation': ['tl_translation_batch', 'tl_translation_100', 'lt_translation_batch', 'lt_translation_100'],
    'logm_progress': ['tl_progress', 'tl_progress_100'],
    'logm_noise_recovery': ['lt_recovery_without_masking_blocks_in'],
})


@pytest.mark.parametrize('lang', ['it', 'en'])
@pytest.mark.parametrize('key,args', [
    ('tl_translation_batch', dict(bar=BAR, progress=40, i=4, total=10, bs=8, eta_txt='')),
    ('lt_translation_batch', dict(bar=BAR, pct=40, done=4, total=10, batch_size=8, tail='')),
    ('tl_progress', dict(progress=40, i=4, total=10, eta_txt='')),
])
def test_barre_traduzione_reali_muovono_log_e_avanzamento(lang, key, args):
    line = TX[lang][key].format(**args)
    d = LogFilter().decide(line)
    assert d.action == 'progress'
    fp = FileProgress('ita')
    fp.feed('1. Setup')
    fp.feed(TX[lang]['pl_6_translation'].format(src='en', dst='it'))
    before = fp.value
    fp.feed(line)
    assert fp.value > before


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_riga_recupero_senza_mascheramento_e_rumore(lang):
    line = TX[lang]['lt_recovery_without_masking_blocks_in'].format(total=3, minutes=0.5)
    assert LogFilter().decide(line).action == 'drop_noise'


MARKER_IN_LINES.update({
    'logm_noise_profile': ['fw_profile', 'fw_profile_beam', 'fw_profile_beam_workers'],
    'logm_noise_vad_available': ['fw_vad_voice_activity_detection_available'],
    'logm_noise_batched_active': ['fw_batchedinferencepipeline_active_batch_size'],
    'logm_noise_batched_single': ['fw_batchedinferencepipeline_single_file_s_batch'],
    'logm_noise_robust_chunking': ['ap_robust_chunking_chunks_of_min'],
    'logm_noise_loading_audio': ['ap_loading_audio'],
})


@pytest.mark.parametrize('lang', ['it', 'en'])
@pytest.mark.parametrize('key,args', [
    ('fw_profile', dict(profile_name='x')),
    ('fw_vad_voice_activity_detection_available', {}),
    ('fw_batchedinferencepipeline_active_batch_size', dict(batch_size_for_transcription=8)),
    ('ap_robust_chunking_chunks_of_min', dict(num_chunks=3, minutes=1.5)),
    ('ap_loading_audio', {}),
])
def test_righe_di_rumore_del_motore_restano_fuori_dallo_schermo(lang, key, args):
    assert LogFilter().decide(TX[lang][key].format(**args)).action == 'drop_noise'


MARKER_IN_LINES.update({
    'logm_bar_gender': ['gc_gender_correction_0_0', 'gc_gender_correction_eta', 'gc_gender_correction_100'],
    'logm_ocr_analysis': ['pgs_ocr_bitmap_analysis'],
    'logm_ocr_translation': ['oa_ocr_translation_it'],
    'logm_srt_written': ['oa_italian_srt_written'],
    'logm_noise_abm_started': ['ab_adaptivebatchmanager_started_initial_min_max'],
})


@pytest.mark.parametrize('lang', ['it', 'en'])
def test_barra_correzione_genere_e_ocr_reali(lang):
    line = TX[lang]['gc_gender_correction_eta'].format(bar=BAR, progress=40, chunks_processed=4,
                                                         chunks_with_gender=10, eta_str='1m')
    assert LogFilter().decide(line).action == 'progress'
    fp = FileProgress('ita')
    fp.feed('1b. ' + TX[lang]['pl_1b_bitmap_subtitles_ocr_translation'].format(kind='PGS').split('. ', 1)[-1])
    fp.feed(TX[lang]['pgs_ocr_bitmap_analysis'])
    assert fp.phase == 'ocr_read'
    fp.feed(TX[lang]['oa_ocr_translation_it'].format(content_lang='en'))
    assert fp.phase == 'ocr_translate'
    fp.feed(TX[lang]['oa_italian_srt_written'].format(name='x.srt'))
    assert fp.phase == 'final'
    assert LogFilter().decide(TX[lang]['ab_adaptivebatchmanager_started_initial_min_max'].format(
        current_batch_size=8, min_size=1, max_size=16, warmup_batches=5, device='GPU')).action == 'drop_noise'
