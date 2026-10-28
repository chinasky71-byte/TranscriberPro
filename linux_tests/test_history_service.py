# -*- coding: utf-8 -*-
"""core/services/history_service.py (senza Qt): formati dei testi, statistiche, ricerca, persistenza. I valori attesi sono quelli
che il vecchio HistoryWidget produceva (vedi test_history_widget_characterization.py, che li verifica sulla vista)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.services import history_service as hs  # noqa: E402


@pytest.mark.parametrize('n,exp', [(0, '0 B'), (1, '1 B'), (1023, '1023 B'), (1024, '1 KB'), (1536, '2 KB'), (1024 ** 2, '1 MB'),
                                   (5 * 1024 ** 3, '5 GB'), (1024 ** 4, '1.0 TB'), (3 * 1024 ** 4, '3.0 TB')])
def test_format_bytes(n, exp):
    assert hs.format_bytes(n) == exp


@pytest.mark.parametrize('s,exp', [(0, '0m 00s'), (59, '0m 59s'), (59.9, '0m 59s'), (125, '2m 05s'), (3600, '1h 00m 00s'),
                                   (3725, '1h 02m 05s'), (None, '0m 00s'), (90061, '25h 01m 01s')])
def test_format_duration(s, exp):
    assert hs.format_duration(s) == exp


def test_data_e_lingua():
    assert hs.format_date({'date_iso': '2026-10-20T21:05:33'}) == '2026-10-20 21:05' and hs.format_date({}) == ''
    assert hs.format_language({'src_lang': 'auto', 'dst_lang': 'ita'}) == 'auto→ita'
    assert hs.format_language({'src_lang': 'eng', 'dst_lang': ''}) == 'eng' and hs.format_language({}) == 'auto'


def test_statistiche_testi():
    st = hs.HistoryStats(3, 2 * 1024 ** 3 + 900 + 1536, 125 + 3725 + 59)
    assert (st.size_text, st.time_text) == ('2.0 GB', '1h 05m')
    assert hs.HistoryStats(0, 0, 0).size_text == '0.0 B' and hs.HistoryStats(0, 0, 0).time_text == '0h 00m'
    assert hs.HistoryStats(1, 5 * 1024 ** 4, 0).size_text == '5.0 TB' 
    # stranezza del codice originale, conservata: oltre i 1024 TB l'ultimo giro del ciclo divide ancora e scrive «1.0 TB»
    assert hs.HistoryStats(1, 1024 ** 5, 0).size_text == '1.0 TB'


def test_azioni():
    assert hs.actions_of({'srt_path': '/a.srt', 'video_path': '/v/x.mkv'}) == ('/a.srt', str(Path('/v/x.mkv').parent))
    assert hs.actions_of({'srt_path': '', 'video_path': ''}) == ('', '') and hs.actions_of({}) == ('', '')


def test_ricerca():
    svc = hs.HistoryService(Path('/non/usato'))
    svc.entries = [{'name': 'Heat.mkv', 'src_lang': 'auto', 'dst_lang': 'ita'}, {'name': 'Pilot.mp4', 'src_lang': 'eng'},
                   {'name': 'Épisode è.mkv', 'src_lang': 'auto', 'dst_lang': 'eng'}]
    assert svc.search('heat') == [0] and svc.search('  ENG ') == [1, 2] and svc.search('') == [0, 1, 2] and svc.search('è') == [2]
    assert svc.search('ita') == [0] and svc.search('zzz') == []


def test_persistenza_e_formato(tmp_path):
    p = tmp_path / 'sub' / 'history.json'
    svc = hs.HistoryService(p)
    assert svc.load() == [] and svc.total_count() == 0                       # assente
    assert svc.append({'name': 'è'}) and svc.append({'name': 'b'})
    txt = p.read_text(encoding='utf-8')
    assert json.loads(txt) == [{'name': 'è'}, {'name': 'b'}] and txt.startswith('[\n  {') and 'è' in txt
    assert list(p.parent.glob('*.tmp')) == []
    assert [e['name'] for e in hs.HistoryService(p).load()] == ['è', 'b']


@pytest.mark.parametrize('content', ['non json', '{"a": 1}', '"stringa"', '123', 'null', ''])
def test_file_non_valido_vale_vuoto(tmp_path, content):
    p = tmp_path / 'h.json'
    p.write_text(content, encoding='utf-8')
    svc = hs.HistoryService(p)
    assert svc.load() == []
    svc.append({'name': 'a'})
    assert json.loads(p.read_text(encoding='utf-8')) == [{'name': 'a'}]


def test_percorso_predefinito(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    assert hs.default_path() == tmp_path / '.transcriberpro' / 'history.json'
    assert hs.HistoryService().path == hs.default_path()


def test_salvataggio_su_cartella_non_scrivibile_non_solleva(tmp_path):
    f = tmp_path / 'file'
    f.write_text('x')
    svc = hs.HistoryService(f / 'history.json')                               # il «genitore» e' un file: impossibile
    assert svc.append({'name': 'a'}) is False and svc.total_count() == 1
