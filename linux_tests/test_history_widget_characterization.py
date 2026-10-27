# -*- coding: utf-8 -*-
"""G1 (fase 0 della web UI): CARATTERIZZAZIONE di gui/history_widget.py::HistoryWidget.

Descrive il comportamento PRIMA dell'estrazione della logica in core/services/history_service.py: i test passano identici sul
codice vecchio e sul nuovo (stessi testi nelle celle, stesse statistiche, stessa ricerca, stesso file history.json). Qt offscreen,
file di cronologia temporaneo. Si salta se PyQt6 (o libEGL) manca."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENTRIES = [
    {'name': 'Heat (1995).mkv', 'date_iso': '2026-10-20T21:05:33', 'src_lang': 'auto', 'dst_lang': 'ita', 'duration_seconds': 125,
     'size_bytes': 2 * 1024 ** 3, 'srt_path': '/v/Heat.it.srt', 'video_path': '/v/Heat (1995).mkv'},
    {'name': 'Pilot.mp4', 'date_iso': '2026-10-21T08:00:00', 'src_lang': 'eng', 'dst_lang': '', 'duration_seconds': 3725,
     'size_bytes': 900, 'srt_path': '', 'video_path': ''},
    {'name': 'Épisode è.mkv', 'date_iso': '', 'src_lang': 'auto', 'dst_lang': 'eng', 'duration_seconds': 59.9,
     'size_bytes': 1536, 'srt_path': '/x/e.srt', 'video_path': '/x/Épisode è.mkv'},
]


@pytest.fixture
def qt(tmp_path, monkeypatch):
    pytest.importorskip('PyQt6.QtWidgets', exc_type=ImportError)
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'home'))
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from utils import config as cfg
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'home' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'home' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    yield app
    cfg.reset_config()


@pytest.fixture
def hfile(tmp_path, monkeypatch):
    from gui.history_widget import HistoryWidget
    p = tmp_path / 'h' / 'history.json'
    monkeypatch.setattr(HistoryWidget, 'HISTORY_FILE', p)
    return p


def make(entries=None, hfile=None):
    from gui.history_widget import HistoryWidget
    if entries is not None:
        hfile.parent.mkdir(parents=True, exist_ok=True)
        hfile.write_text(json.dumps(entries, ensure_ascii=False), encoding='utf-8')
    return HistoryWidget()


def cells(w):
    return [[w._table.item(r, c).text() for c in range(5)] for r in range(w._table.rowCount())]


def tiles(w):
    return (w._tile_total._value_lbl.text(), w._tile_size._value_lbl.text(), w._tile_time._value_lbl.text())


def test_caricamento_e_testi_delle_celle(qt, hfile):
    w = make(ENTRIES, hfile)
    assert w.total_count() == 3 and w._table.rowCount() == 3
    got = {tuple(r) for r in cells(w)}
    assert got == {
        ('Heat (1995).mkv', '2026-10-20 21:05', 'auto→ita', '2m 05s', '2 GB'),
        ('Pilot.mp4', '2026-10-21 08:00', 'eng', '1h 02m 05s', '900 B'),
        ('Épisode è.mkv', '', 'auto→eng', '0m 59s', '2 KB'),                 # 1536 B = 1,5 KB, arrotondato da :.0f
    }


def test_arrotondamenti_delle_dimensioni(qt):
    from gui.history_widget import HistoryWidget
    f = HistoryWidget._fmt_bytes
    assert [f(n) for n in (0, 1, 1023, 1024, 1536, 1024 ** 2, 1536 * 1024, 5 * 1024 ** 3, 1024 ** 4, 3 * 1024 ** 4)] == [
        '0 B', '1 B', '1023 B', '1 KB', '2 KB', '1 MB', '2 MB', '5 GB', '1.0 TB', '3.0 TB']


def test_statistiche(qt, hfile):
    w = make(ENTRIES, hfile)
    # totale byte = 2 GiB + 900 + 1536; tempo = 125 + 3725 + 59 (int della somma 3909,9)
    assert tiles(w) == ('3', '2.0 GB', '1h 05m')
    w2 = make([], hfile)
    assert tiles(w2) == ('0', '0.0 B', '0h 00m')


def test_append_entry_persiste_con_il_formato_della_gui(qt, hfile):
    w = make([], hfile)
    e = {'name': 'è.mkv', 'date_iso': '2026-10-26T10:00:00', 'src_lang': 'auto', 'dst_lang': 'ita', 'duration_seconds': 10,
         'size_bytes': 100, 'srt_path': '', 'video_path': ''}
    w.append_entry(e)
    w.append_entry(dict(e, name='b.mkv'))
    assert w.total_count() == 2 and w._table.rowCount() == 2 and tiles(w)[0] == '2'
    txt = hfile.read_text(encoding='utf-8')
    assert json.loads(txt) == [e, dict(e, name='b.mkv')]
    assert txt.startswith('[\n  {') and 'è.mkv' in txt                       # indent=2, ensure_ascii=False
    assert [r[0] for r in cells(make(None, hfile))] == ['è.mkv', 'b.mkv']        # riletta alla riapertura


def test_file_illeggibile_o_assente_si_considera_vuoto(qt, hfile):
    assert make(None, hfile).total_count() == 0                           # file assente
    hfile.parent.mkdir(parents=True, exist_ok=True)
    hfile.write_text('non json', encoding='utf-8')
    w = make(None, hfile)
    assert w.total_count() == 0
    w.append_entry({'name': 'a'})
    assert json.loads(hfile.read_text(encoding='utf-8')) == [{'name': 'a'}]


def test_ricerca_per_nome_e_per_lingua(qt, hfile):
    w = make(ENTRIES, hfile)
    hidden = lambda: sorted(w._table.item(r, 0).text() for r in range(w._table.rowCount()) if w._table.isRowHidden(r))  # noqa: E731
    w._apply_search('heat')
    assert hidden() == ['Pilot.mp4', 'Épisode è.mkv']
    w._apply_search('  ENG ')
    assert hidden() == ['Heat (1995).mkv']                                   # 'eng' compare in 'eng' e in 'auto→eng'
    w._apply_search('ita')
    assert hidden() == ['Pilot.mp4', 'Épisode è.mkv']
    w._apply_search('')
    assert hidden() == []
    w._apply_search('è')
    assert hidden() == ['Heat (1995).mkv', 'Pilot.mp4']


def test_pulsanti_azione(qt, hfile, monkeypatch):
    import gui.history_widget as hw
    from PyQt6.QtWidgets import QPushButton
    opened = []
    monkeypatch.setattr(hw.QDesktopServices, 'openUrl', staticmethod(lambda u: opened.append(u.toLocalFile())))
    w = make(ENTRIES, hfile)
    rows = {w._table.item(r, 0).text(): w._table.cellWidget(r, 5).findChildren(QPushButton) for r in range(3)}
    assert [b.isEnabled() for b in rows['Heat (1995).mkv']] == [True, True]
    assert [b.isEnabled() for b in rows['Pilot.mp4']] == [False, False]
    assert [b.isEnabled() for b in rows['Épisode è.mkv']] == [True, True]
    for b in rows['Heat (1995).mkv']:
        b.click()
    # Qt restituisce sempre '/': si confrontano i percorsi normalizzati (su Windows str(Path) usa '\\')
    assert [Path(o) for o in opened] == [Path('/v/Heat.it.srt'), Path('/v/Heat (1995).mkv').parent]


def test_ordine_di_inserimento_e_conteggio_nel_titolo_scheda(qt, hfile):
    w = make(ENTRIES, hfile)
    assert [r[0] for r in sorted(cells(w), key=lambda r: r[0])] == sorted(e['name'] for e in ENTRIES)
    assert w.total_count() == len(ENTRIES)
