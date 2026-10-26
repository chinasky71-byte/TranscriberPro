# -*- coding: utf-8 -*-
"""bench/asr_ab.py: harness di misura per le impostazioni ASR (nessuna GPU qui)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'bench'))

import asr_ab  # noqa: E402


def test_build_config_part_dai_default():
    config = asr_ab.build_config({})
    assert config['transcription_engine_mode'] == 'qwen3'
    assert config['transcription_profile_locked'] is False      # altrimenti il profilo viene ignorato
    assert config['asr_chunk_target_duration'] == 20
    assert 'transcription_profile' not in config


def test_build_config_applica_profilo_e_override():
    config = asr_ab.build_config({
        'tag': 'x', 'profile': 'balanced',
        'config': {'asr_chunk_target_duration': 45, 'asr_chunk_max_duration': 60}})
    assert config['transcription_profile'] == 'balanced'
    assert config['asr_chunk_target_duration'] == 45
    assert config['asr_chunk_max_duration'] == 60
    assert config['asr_chunk_min_duration'] == 10          # non toccato dall'override
    assert asr_ab.BASE_CONFIG['asr_chunk_target_duration'] == 20   # il base non viene mutato


def test_le_varianti_del_repository_sono_valide():
    variants = json.loads((ROOT / 'bench' / 'asr_ab_variants.json').read_text(encoding='utf-8'))
    tags = [variant['tag'] for variant in variants]
    assert tags[0] == 'max-b2'                             # la prima è il riferimento
    assert len(set(tags)) == len(tags)
    for variant in variants:
        config = asr_ab.build_config(variant)
        assert config['transcription_profile'] in ('fast', 'balanced', 'quality', 'maximum', 'batch')
        assert 0 < config['asr_chunk_min_duration'] < config['asr_chunk_target_duration'] <= config['asr_chunk_max_duration']


def test_parse_events_legge_fasi_e_batch():
    lines = [
        'rumore\n',
        '@@TPEV@@ {"k":"status","status":"running"}\n',
        '@@TPEV@@ {"k":"phase","name":"extract"}\n',
        '@@TPEV@@ non-json\n',
        '  📊 Transcribing 26 audio chunks (batch=8)...\n',
        '@@TPEV@@ {"k":"phase","name":"asr"}\n',
        '✅ Processing completed! Total time: 115.8 seconds.\n',
    ]
    parsed = asr_ab.parse_events(lines, started=0.0)
    assert [item['phase'] for item in parsed['phases']] == ['extract', 'asr']
    assert parsed['batch_line'].endswith('(batch=8)...')
    assert 'Total time' in parsed['total_line']


def test_phase_timeline_usa_la_fine_per_lultima_fase():
    phases = [{'at': 10.0, 'phase': 'extract'}, {'at': 13.0, 'phase': 'asr'}]
    timeline = asr_ab.phase_timeline(phases, finished=73.4)
    assert timeline == [{'phase': 'extract', 'seconds': 3.0},
                        {'phase': 'asr', 'seconds': 60.4}]


def test_summarise_mostra_batch_e_fasi():
    results = [
        {'tag': 'a', 'wall_seconds': 115.8, 'batch_line': '📊 Transcribing 26 audio chunks (batch=2)...',
         'phases': [{'phase': 'demucs', 'seconds': 43.5}, {'phase': 'asr', 'seconds': 64.3}]},
        {'tag': 'b', 'wall_seconds': 115.6, 'batch_line': '', 'phases': [{'phase': 'asr', 'seconds': 63.6}]},
    ]
    text = asr_ab.summarise(results)
    assert 'demucs' in text and 'a ' in text and '64.3' in text
    assert 'batch' in text and '?' in text          # riga senza batch: nessun crash


def test_cli_rifiuta_un_clip_inesistente(tmp_path, capsys):
    code = asr_ab.main(['--video', str(tmp_path / 'nope.mkv'),
                        '--variants', str(ROOT / 'bench' / 'asr_ab_variants.json'),
                        '--work-dir', str(tmp_path / 'work')])
    assert code == 2
    assert 'clip not found' in capsys.readouterr().err


@pytest.mark.parametrize('python_path', ['sys.executable'])
def test_nessun_percorso_assoluto_personale_nel_harness(python_path):
    text = (ROOT / 'bench' / 'asr_ab.py').read_text(encoding='utf-8')
    assert '/home/' not in text and 'C:\\' not in text
    assert 'ROOT = Path(__file__).resolve().parents[1]' in text
