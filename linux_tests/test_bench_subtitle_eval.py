# -*- coding: utf-8 -*-
"""bench/subtitle_eval.py: confronto SRT generato vs reference, sulle finestre temporali."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'bench'))

import subtitle_eval as ev  # noqa: E402


def _srt(tmp_path, name, entries):
    """entries: [(inizio, fine, testo)] con timestamp già formattati."""
    blocks = []
    for index, (start, end, text) in enumerate(entries, start=1):
        blocks.append(f"{index}\n{start} --> {end}\n{text}\n")
    path = tmp_path / name
    path.write_text('\n'.join(blocks), encoding='utf-8')
    return path


def test_secondi_da_timestamp():
    assert ev._seconds('00:00:10,500') == 10.5
    assert ev._seconds('01:02:03,250') == 3723.25


def test_contenuto_identico_da_wer_zero(tmp_path):
    entries = [('00:00:05,000', '00:00:08,000', 'Ciao come stai')]
    ref = _srt(tmp_path, 'ref.srt', entries)
    hyp = _srt(tmp_path, 'hyp.srt', entries)
    result = ev.evaluate(ev.cues(ref), ev.cues(hyp))
    assert result['wer']['rate_pct'] == 0.0
    assert result['coverage']['coverage_pct'] == 100.0
    assert result['silence']['extra_words'] == 0
    assert result['chrf'] == 100.0


def test_normalizzazione_ignora_tag_e_punteggiatura(tmp_path):
    ref = _srt(tmp_path, 'ref.srt', [('00:00:05,000', '00:00:08,000', '<i>Ciao, come stai?</i>')])
    hyp = _srt(tmp_path, 'hyp.srt', [('00:00:05,000', '00:00:08,000', 'ciao come stai')])
    assert ev.evaluate(ev.cues(ref), ev.cues(hyp))['wer']['rate_pct'] == 0.0


def test_segmentazione_diversa_non_penalizza(tmp_path):
    ref = _srt(tmp_path, 'ref.srt', [('00:00:05,000', '00:00:09,000', 'Ciao come stai'),
                                     ('00:00:09,100', '00:00:12,000', 'bene grazie')])
    hyp = _srt(tmp_path, 'hyp.srt', [('00:00:05,000', '00:00:12,000', 'Ciao come stai bene grazie')])
    result = ev.evaluate(ev.cues(ref), ev.cues(hyp))
    assert result['wer']['rate_pct'] == 0.0


def test_finestra_senza_reference_conta_le_parole_extra(tmp_path):
    ref = _srt(tmp_path, 'ref.srt', [('00:00:05,000', '00:00:08,000', 'Ciao')])
    hyp = _srt(tmp_path, 'hyp.srt', [('00:00:05,000', '00:00:08,000', 'Ciao'),
                                     ('00:00:25,000', '00:00:28,000', 'musica di sottofondo')])
    result = ev.evaluate(ev.cues(ref), ev.cues(hyp))
    assert result['silence']['extra_words'] == 3
    assert result['silence']['extra_windows'] == 1
    assert result['coverage']['coverage_pct'] == 100.0


def test_reference_non_coperta_abbassa_la_copertura(tmp_path):
    ref = _srt(tmp_path, 'ref.srt', [('00:00:05,000', '00:00:08,000', 'Ciao'),
                                     ('00:00:25,000', '00:00:28,000', 'seconda battuta')])
    hyp = _srt(tmp_path, 'hyp.srt', [('00:00:05,000', '00:00:08,000', 'Ciao')])
    result = ev.evaluate(ev.cues(ref), ev.cues(hyp))
    assert result['coverage']['coverage_pct'] == 50.0
    assert result['coverage']['missing_windows'] == 1
    assert result['coverage']['missing_words'] == 2


def test_errore_nel_testo_alza_il_wer(tmp_path):
    ref = _srt(tmp_path, 'ref.srt', [('00:00:05,000', '00:00:08,000', 'uno due tre quattro')])
    hyp = _srt(tmp_path, 'hyp.srt', [('00:00:05,000', '00:00:08,000', 'uno due tre cinque')])
    result = ev.evaluate(ev.cues(ref), ev.cues(hyp))
    assert result['wer']['rate_pct'] == 25.0
    assert result['wer']['sub'] == 1


def test_timing_offset_mediano(tmp_path):
    ref = [{'start': 10.0, 'end': 12.0, 'text': 'a'}, {'start': 20.0, 'end': 22.0, 'text': 'b'}]
    hyp = [{'start': 10.5, 'end': 12.5, 'text': 'a'}, {'start': 23.0, 'end': 25.0, 'text': 'b'}]
    offsets = ev.timing_offsets(ref, hyp)
    assert offsets['count'] == 2
    assert offsets['median_s'] == 1.75          # (0.5 + 3.0) / 2


def test_bucket_usa_il_punto_medio(tmp_path):
    items = [{'start': 9.0, 'end': 12.0, 'text': 'x'}, {'start': 19.0, 'end': 21.0, 'text': 'y'}]
    buckets = ev.bucket_text(items, window_s=10.0)
    assert buckets == {1: 'x', 2: 'y'}          # 10.5 -> finestra 1, 20.0 -> finestra 2


def test_summarise_contiene_le_metriche(tmp_path):
    ref = _srt(tmp_path, 'ref.srt', [('00:00:05,000', '00:00:08,000', 'uno due')])
    hyp = _srt(tmp_path, 'hyp.srt', [('00:00:05,000', '00:00:08,000', 'uno due')])
    line = ev.summarise(ev.evaluate(ev.cues(ref), ev.cues(hyp)), label='clip-A')
    assert 'clip-A' in line and 'WER 0.0%' in line and 'coverage 100.0%' in line


def test_cli_scrive_il_json(tmp_path):
    ref = _srt(tmp_path, 'ref.srt', [('00:00:05,000', '00:00:08,000', 'uno due')])
    hyp = _srt(tmp_path, 'hyp.srt', [('00:00:05,000', '00:00:08,000', 'uno due')])
    out = tmp_path / 'score.json'
    assert ev.main(['--reference', str(ref), '--hypothesis', str(hyp), '--json', str(out)]) == 0
    assert '"wer"' in out.read_text(encoding='utf-8')


def test_nessun_percorso_personale_nel_modulo():
    text = (ROOT / 'bench' / 'subtitle_eval.py').read_text(encoding='utf-8')
    assert '/home/' not in text and 'C:\\' not in text


def test_le_varianti_di_valutazione_sono_valide():
    import json
    variants = json.loads((ROOT / 'bench' / 'asr_eval_variants.json').read_text(encoding='utf-8'))
    tags = [variant['tag'] for variant in variants]
    assert tags == ['qwen3', 'whisper']
    for variant in variants:
        config = variant['config']
        assert config['force_audio_transcription'] is True     # altrimenti legge i subs incorporati
        assert variant['target_language'] == 'eng'


def test_watermark_ignorato(tmp_path):
    ref = _srt(tmp_path, 'ref.srt', [('00:00:05,000', '00:00:08,000', 'Ciao')])
    hyp = _srt(tmp_path, 'hyp.srt', [('00:00:00,000', '00:00:09,000',
                                      'AI generated subtitles : Transcriber_pro\nQwen3-ASR'),
                                     ('00:00:05,000', '00:00:08,000', 'Ciao')])
    parsed = ev.cues(hyp)
    assert len(parsed) == 1                                   # il cue del watermark non entra
    assert ev.evaluate(ev.cues(ref), parsed)['wer']['rate_pct'] == 0.0


def test_corsivi_esclusi_e_contati(tmp_path):
    ref = _srt(tmp_path, 'ref.srt', [('00:00:05,000', '00:00:08,000', 'Ciao'),
                                     ('00:00:15,000', '00:00:18,000', '<i>la la la</i>'),
                                     ('00:00:25,000', '00:00:28,000', '<i>ritornello</i>\nparlato')])
    hyp = _srt(tmp_path, 'hyp.srt', [('00:00:05,000', '00:00:08,000', 'Ciao')])
    parsed = ev.cues(ref)
    assert [c['italic'] for c in parsed] == [False, True, False]
    result = ev.evaluate(parsed, ev.cues(hyp))
    assert result['excluded_italic']['cues'] == 1
    assert result['coverage']['coverage_pct'] == 50.0          # restano due finestre di parlato
    with_italic = ev.evaluate(parsed, ev.cues(hyp), exclude_italic_reference=False)
    assert with_italic['excluded_italic']['cues'] == 0
    assert with_italic['coverage']['coverage_pct'] < result['coverage']['coverage_pct']
