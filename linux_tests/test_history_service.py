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


# ------------------------------------------------------------------------------------------------ ordinamento e cancellazione
SORT_ENTRIES = [
    {'name': 'beta', 'date_iso': '2026-10-27T21:05:09', 'src_lang': 'eng', 'dst_lang': 'ita', 'duration_seconds': 3600, 'size_bytes': 10 * 1024},
    {'name': 'Alfa', 'date_iso': '2026-10-28T08:00:00', 'src_lang': 'fra', 'dst_lang': 'ita', 'duration_seconds': 540, 'size_bytes': 2 * 1024},
    {'name': 'Gamma', 'date_iso': '2026-01-02T00:00:00', 'src_lang': 'auto', 'dst_lang': '', 'duration_seconds': 65, 'size_bytes': 5 * 1024 ** 3},
    {'name': 'delta', 'src_lang': 'eng', 'dst_lang': 'ita'},                      # senza data, durata e dimensione
]


def _svc(tmp_path, entries=None):
    s = hs.HistoryService(tmp_path / 'history.json')
    s.entries = list(SORT_ENTRIES if entries is None else entries)
    return s


@pytest.mark.parametrize('key,expected', [
    ('name', [1, 0, 3, 2]),         # Alfa, beta, delta, Gamma: senza badare a maiuscole e minuscole
    ('date', [3, 2, 0, 1]),         # data ISO: la voce senza data prima, poi gennaio, ottobre 27, ottobre 28
    ('language', [2, 0, 3, 1]),     # 'auto' < 'eng→ita' (due voci: restano nell'ordine del file) < 'fra→ita'; la voce senza lingua vale 'eng→ita'
    ('duration', [3, 2, 1, 0]),     # 0 s, 65 s, 9 min, 1 h: sui SECONDI, non sul testo («1h 00m» verrebbe prima di «9m»)
    ('size', [3, 1, 0, 2]),         # 0, 2 KB, 10 KB, 5 GB: sui BYTE, non sul testo («10 KB» verrebbe prima di «2 KB»)
])
def test_ordinamento_crescente_sui_dati_veri(tmp_path, key, expected):
    s = _svc(tmp_path)
    assert s.sort_indices(list(range(4)), key) == expected


def test_ordinamento_decrescente_e_stabile(tmp_path):
    s = _svc(tmp_path, [{'name': 'a', 'size_bytes': 5}, {'name': 'b', 'size_bytes': 5}, {'name': 'c', 'size_bytes': 9}])
    assert s.sort_indices([0, 1, 2], 'size') == [0, 1, 2]
    assert s.sort_indices([0, 1, 2], 'size', descending=True) == [2, 0, 1]       # a parita' resta l'ordine del file
    assert s.sort_indices([2, 0], 'size') == [0, 2]                              # lavora sugli indici dati (ricerca gia' applicata)


def test_ordinamento_valori_sporchi_non_solleva(tmp_path):
    s = _svc(tmp_path, [{'name': 'x', 'size_bytes': 'tanti', 'duration_seconds': None}, {'name': 'y', 'size_bytes': 3}])
    assert s.sort_indices([0, 1], 'size') == [0, 1]
    assert s.sort_indices([0, 1], 'duration') == [0, 1]


def test_ordinamento_colonna_non_valida(tmp_path):
    with pytest.raises(ValueError):
        _svc(tmp_path).sort_indices([0], 'path')
    with pytest.raises(ValueError):
        hs.sort_key_of({}, 'srt_path')


def test_cancella_cronologia_svuota_il_file_e_conta(tmp_path):
    s = _svc(tmp_path)
    assert s.save() is True
    other = hs.HistoryService(s.path)
    assert other.clear() == 4                       # rilegge dal disco: conta le voci che c'erano davvero
    assert json.loads(s.path.read_text(encoding='utf-8')) == []
    assert other.entries == [] and hs.HistoryService(s.path).load() == []
    assert other.clear() == 0                       # gia' vuota: 0, non un errore


def test_cancella_non_riscrive_una_copia_vecchia(tmp_path):
    s = _svc(tmp_path)
    s.save()
    stale = hs.HistoryService(s.path)               # copia in memoria vecchia
    stale.load()
    fresh = hs.HistoryService(s.path)
    fresh.load()
    fresh.append({'name': 'nuova'})                  # come fa la coda: rilegge, poi aggiunge (reload_and_append)
    assert stale.clear() == 5                      # conta anche la voce arrivata dopo
    assert json.loads(s.path.read_text(encoding='utf-8')) == []


def test_cancella_su_file_non_scrivibile_restituisce_none_e_non_perde_le_voci(tmp_path, monkeypatch):
    s = _svc(tmp_path)
    s.save()
    monkeypatch.setattr(hs.HistoryService, 'save', lambda self: False)
    assert s.clear() is None
    assert len(s.entries) == 4 and len(json.loads(s.path.read_text(encoding='utf-8'))) == 4


def test_ordinamento_campi_nulli_e_nan_non_sollevano(tmp_path):
    s = _svc(tmp_path, [{'name': None, 'date_iso': None, 'src_lang': None, 'dst_lang': '', 'size_bytes': float('nan'), 'duration_seconds': float('inf')},
                        {'name': 'b', 'date_iso': '2026-01-01T00:00:00', 'src_lang': 'eng', 'dst_lang': 'ita', 'size_bytes': 7, 'duration_seconds': 3}])
    for key in hs.SORT_KEYS:
        assert sorted(s.sort_indices([0, 1], key)) == [0, 1]                 # nessuna eccezione, nessun indice perso
    assert s.sort_indices([0, 1], 'size') == [0, 1]                          # NaN vale 0
    assert s.sort_indices([0, 1], 'date') == [0, 1]                          # data nulla = data assente: in cima


def test_voci_aggiunte_da_thread_diversi_e_clear_non_rovinano_il_file(tmp_path):
    import threading, time
    s = hs.HistoryService(tmp_path / 'history.json')
    s.save()
    stop = threading.Event()
    errors = []

    def aggiungi(n):
        try:
            for i in range(40):
                s.reload_and_append({'name': f'f{n}-{i}'})
        except Exception as e:           # pragma: no cover
            errors.append(e)

    def svuota():
        try:
            while not stop.is_set():
                s.clear()
                time.sleep(0.001)
        except Exception as e:           # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=aggiungi, args=(n,)) for n in range(4)]
    cl = threading.Thread(target=svuota)
    cl.start()
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    stop.set()
    cl.join(30)
    assert not errors and not any(x.is_alive() for x in ts + [cl])
    s.reload_and_append({'name': 'finale'})
    data = json.loads(s.path.read_text(encoding='utf-8'))          # sempre un JSON valido (nessun file troncato)
    assert isinstance(data, list) and all('name' in e for e in data)
    assert not list(tmp_path.glob('*.tmp'))                          # nessun temporaneo lasciato


def test_reload_and_append_non_perde_le_voci_di_altri(tmp_path):
    a = hs.HistoryService(tmp_path / 'history.json')
    a.reload_and_append({'name': 'uno'})
    b = hs.HistoryService(tmp_path / 'history.json')                 # un altro oggetto che aggiunge dopo
    b.reload_and_append({'name': 'due'})
    assert [e['name'] for e in json.loads(a.path.read_text(encoding='utf-8'))] == ['uno', 'due']
    a.reload_and_append({'name': 'tre'})                              # `a` ha una copia vecchia: rilegge prima
    assert [e['name'] for e in json.loads(a.path.read_text(encoding='utf-8'))] == ['uno', 'due', 'tre']
