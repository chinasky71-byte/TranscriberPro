# -*- coding: utf-8 -*-
"""G4b (fase 0 della web UI): CARATTERIZZAZIONE della tabella del Library Scanner (gui/library_scanner_widget.py::LibraryScannerWidget).

Passa identica sul codice vecchio e su quello con la logica delle righe in core/services/library_rows.py: celle (nome, tooltip, colore,
tipo, giorni), badge (PGS/VOB/MIX/ASS), pulsante «gia' in coda», ordinamento numerico, filtri giorni/formato, statistiche, stato della
connessione, rilevamento della lingua dal nome. Qt offscreen, main_window finta, config temporaneo."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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
    for w in app.topLevelWidgets():
        w.deleteLater()
    app.processEvents()
    cfg.reset_config()


class FakeMain:
    def __init__(self):
        from PyQt6.QtCore import QMutex
        self.queue_mutex = QMutex()
        self.processing_queue = []
        self.is_processing = False


VIDEOS = [
    {'id': 1, 'filename': 'Film.2020.ITA.1080p.mkv', 'windows_path': r'V:\Film\Film.2020.ITA.1080p.mkv', 'media_type': 'movie',
     'days_without_subs': 40, 'bitmap_format': 'pgs', 'has_only_bitmap_subs': True},
    {'id': 2, 'filename': 'Serie.S01E01.ENG.mkv', 'windows_path': r'V:\Serie\Serie.S01E01.ENG.mkv', 'media_type': 'tvshow',
     'days_without_subs': 20, 'bitmap_format': 'vobsub', 'has_only_bitmap_subs': True},
    {'id': 3, 'filename': 'Altro.mkv', 'windows_path': r'V:\Altro.mkv', 'media_type': 'movie', 'days_without_subs': 5,
     'bitmap_format': 'mixed', 'has_only_bitmap_subs': True},
    {'id': 4, 'filename': 'Anime.S01E02.mkv', 'windows_path': r'V:\Anime.S01E02.mkv', 'media_type': 'tvshow',
     'days_without_subs': 100, 'bitmap_format': None, 'has_italian_convertible_subs': True},
    {'id': 5, 'filename': 'Gia.Convertito.mkv', 'windows_path': r'V:\Gia.Convertito.mkv', 'media_type': 'tvshow',
     'days_without_subs': 3, 'has_italian_convertible_subs': True, 'conversion_status': 'done'},
    {'id': 6, 'filename': 'Nessuna.Traccia.mkv', 'windows_path': r'V:\Nessuna.Traccia.mkv', 'media_type': 'documentary',
     'days_without_subs': 14},
    {'id': 7, 'filename': 'Pgs.Con.Testo.mkv', 'windows_path': r'V:\Pgs.Con.Testo.mkv', 'media_type': 'movie', 'days_without_subs': 9,
     'bitmap_format': 'pgs', 'has_only_bitmap_subs': False},
]


def make(main=None, videos=VIDEOS):
    from gui.library_scanner_widget import LibraryScannerWidget
    w = LibraryScannerWidget(main or FakeMain())
    if videos is not None:
        w._on_videos_loaded({'videos': [dict(v) for v in videos]})
    return w


def name_rows(w):
    return {w.video_table.item(r, 0).text(): r for r in range(w.video_table.rowCount())}


def visible(w):
    return sorted(w.video_table.item(r, 0).text() for r in range(w.video_table.rowCount()) if not w.video_table.isRowHidden(r))


def badge_text(w, row):
    from PyQt6.QtWidgets import QPushButton
    btns = w.video_table.cellWidget(row, 3).findChildren(QPushButton)
    return [(b.text(), b.isEnabled(), b.toolTip()) for b in btns]


# ------------------------------------------------------------------------------------------------------------ celle
def test_celle_di_base(qt):
    from utils.translations import tr
    w = make()
    rows = name_rows(w)
    assert w.video_table.rowCount() == 7
    r = rows['Film.2020.ITA.1080p.mkv']
    it = w.video_table.item(r, 0)
    assert it.data(0x100) == r'V:\Film\Film.2020.ITA.1080p.mkv'                       # UserRole = percorso
    assert it.data(0x101) == 'pgs' and it.data(0x102) == 1 and it.data(0x103) is False and it.data(0x104) is True
    assert it.toolTip() == tr('ls_audio_ita_tip').format(path=r'V:\Film\Film.2020.ITA.1080p.mkv')
    assert w.video_table.item(r, 1).text() == tr('film_type') and w.video_table.item(r, 2).text() == '40'
    assert w.video_table.item(rows['Serie.S01E01.ENG.mkv'], 1).text() == tr('tv_series_type')
    assert w.video_table.item(rows['Nessuna.Traccia.mkv'], 1).text() == 'documentary'
    assert w.video_table.item(rows['Altro.mkv'], 0).toolTip() == r'V:\Altro.mkv'


def test_colori_nome_e_giorni(qt):
    from PyQt6.QtGui import QColor
    from gui.design_tokens import T
    w = make()
    rows = name_rows(w)
    fg = lambda r, c: w.video_table.item(r, c).foreground().color().name()
    assert fg(rows['Film.2020.ITA.1080p.mkv'], 0) == QColor(T.legacy_blue_link).name()
    assert fg(rows['Film.2020.ITA.1080p.mkv'], 2) == QColor(T.legacy_pink).name()           # 40 > 30
    assert fg(rows['Serie.S01E01.ENG.mkv'], 2) == QColor(T.legacy_mat_amber).name()         # 20 > 14
    default = fg(rows['Altro.mkv'], 2)
    assert default not in (QColor(T.legacy_pink).name(), QColor(T.legacy_mat_amber).name())
    assert fg(rows['Nessuna.Traccia.mkv'], 2) == default                                    # 14 non e' > 14
    assert fg(rows['Serie.S01E01.ENG.mkv'], 0) != QColor(T.legacy_blue_link).name()


def test_badge(qt):
    from utils.translations import tr
    w = make()
    rows = name_rows(w)
    assert badge_text(w, rows['Film.2020.ITA.1080p.mkv']) == [('PGS', True, tr('ls_bitmap_tip'))]
    assert badge_text(w, rows['Serie.S01E01.ENG.mkv']) == [('VOB', True, tr('ls_bitmap_tip'))]
    assert badge_text(w, rows['Altro.mkv']) == [('MIX', True, tr('ls_bitmap_tip'))]
    assert badge_text(w, rows['Anime.S01E02.mkv']) == [('ASS', True, tr('ls_ass_tip'))]
    assert badge_text(w, rows['Gia.Convertito.mkv']) == [('ASS', False, tr('ls_ass_done_tip'))]
    assert badge_text(w, rows['Nessuna.Traccia.mkv']) == [] and badge_text(w, rows['Pgs.Con.Testo.mkv']) == []


@pytest.mark.parametrize('fmt,exp', [('vobsub', ('VOB', 'vobsub')), ('mixed', ('MIX', 'pgs')), ('pgs', ('PGS', 'pgs')),
                                     (None, ('PGS', 'pgs')), ('boh', ('PGS', 'pgs'))])
def test_etichetta_e_tipo_del_badge(qt, fmt, exp):
    from gui.library_scanner_widget import LibraryScannerWidget
    assert LibraryScannerWidget._badge_label_kind(fmt) == exp


def test_bottone_gia_in_coda(qt):
    from utils.translations import tr
    main = FakeMain()
    main.processing_queue.append(r'V:\Altro.mkv')
    w = make(main)
    rows = name_rows(w)
    done = w.video_table.cellWidget(rows['Altro.mkv'], 4)
    todo = w.video_table.cellWidget(rows['Film.2020.ITA.1080p.mkv'], 4)
    assert (done.text(), done.isEnabled(), done.toolTip()) == ('✓', False, tr('already_queued'))
    assert (todo.text(), todo.isEnabled()) == ('', True)


def test_gia_in_coda_con_mappa_percorsi(qt):
    from utils.config import get_config
    get_config().set('library_scanner_path_map', 'V:\\=/mnt/v/')
    main = FakeMain()
    main.processing_queue.append('/mnt/v/Altro.mkv')
    w = make(main)
    rows = name_rows(w)
    assert w.video_table.cellWidget(rows['Altro.mkv'], 4).text() == '✓'
    assert w.video_table.cellWidget(rows['Film.2020.ITA.1080p.mkv'], 4).text() == ''


# -------------------------------------------------------------------------------------------------------------- filtri
def test_filtro_giorni(qt):
    w = make()
    assert len(visible(w)) == 7
    w.days_spinbox.setValue(20)
    assert visible(w) == ['Anime.S01E02.mkv', 'Film.2020.ITA.1080p.mkv', 'Serie.S01E01.ENG.mkv']
    assert w.badge_label.text() == '3' and w.badge_label.isVisibleTo(w) is True
    w.days_spinbox.setValue(0)
    assert len(visible(w)) == 7 and w.badge_label.text() == '7'


@pytest.mark.parametrize('fmt,exp', [
    ('pgs', ['Altro.mkv', 'Film.2020.ITA.1080p.mkv']),            # mixed soddisfa pgs; il PGS con testo ITA non e' un lavoro OCR
    ('vobsub', ['Altro.mkv', 'Serie.S01E01.ENG.mkv']),
    ('assssa', ['Anime.S01E02.mkv', 'Gia.Convertito.mkv']),
    ('nosrt', ['Anime.S01E02.mkv', 'Gia.Convertito.mkv', 'Nessuna.Traccia.mkv']),
])
def test_filtro_formato(qt, fmt, exp, monkeypatch):
    w = make()
    monkeypatch.setattr(w, 'refresh_data', lambda: None)
    w.format_combo.setCurrentIndex(w.format_combo.findData(fmt))
    w._apply_days_filter()
    assert visible(w) == exp


def test_filtri_combinati_e_testo_del_pulsante(qt, monkeypatch):
    from utils.translations import tr
    w = make()
    monkeypatch.setattr(w, 'refresh_data', lambda: None)
    w.format_combo.setCurrentIndex(w.format_combo.findData('pgs'))
    w.days_spinbox.setValue(30)
    assert visible(w) == ['Film.2020.ITA.1080p.mkv'] and w.import_all_btn.isEnabled()
    assert w.import_all_btn.text() == tr('import_filtered')
    w.days_spinbox.setValue(500)
    assert visible(w) == [] and not w.import_all_btn.isEnabled() and not w.badge_label.isVisibleTo(w)
    w.format_combo.setCurrentIndex(w.format_combo.findData('assssa'))        # ASS ricarica dal server: il testo cambia a dati arrivati
    assert w.import_all_btn.text() == tr('import_filtered')
    w._apply_days_filter()
    assert w.import_all_btn.text() == tr('ls_convert_ass')


def test_cambio_formato_ricarica_solo_con_ass(qt, monkeypatch):
    w = make()
    calls = []
    monkeypatch.setattr(w, 'refresh_data', lambda: calls.append(1))
    w.is_loaded = True
    w.format_combo.setCurrentIndex(w.format_combo.findData('pgs'))
    assert calls == []
    w.format_combo.setCurrentIndex(w.format_combo.findData('assssa'))
    assert calls == [1]
    w.format_combo.setCurrentIndex(w.format_combo.findData('vobsub'))          # si torna da ASS: ricarica
    assert calls == [1, 1]
    w.format_combo.setCurrentIndex(w.format_combo.findData('pgs'))
    assert calls == [1, 1]
    w.is_loaded = False
    w.format_combo.setCurrentIndex(w.format_combo.findData('assssa'))
    assert calls == [1, 1]


def test_tipo_selezionato_e_ricarica(qt, monkeypatch):
    w = make()
    calls = []
    monkeypatch.setattr(w, 'refresh_data', lambda: calls.append(w._get_selected_type()))
    w.is_loaded = True
    w.type_combo.setCurrentIndex(1)
    w.type_combo.setCurrentIndex(2)
    w.type_combo.setCurrentIndex(0)
    assert calls == ['movie', 'tvshow', '']


def test_ordinamento_numerico_dei_giorni(qt):
    from PyQt6.QtCore import Qt
    w = make()
    w.video_table.sortItems(2, Qt.SortOrder.AscendingOrder)
    assert [w.video_table.item(r, 2).text() for r in range(7)] == ['3', '5', '9', '14', '20', '40', '100']


# ----------------------------------------------------------------------------------------------------- stato e testi
def test_statistiche_errore_e_pallino(qt):
    from gui.design_tokens import T
    from utils.translations import tr
    w = make(videos=None)
    w._on_stats_loaded({'without_subs': 12, 'total_files': 345})
    assert w.stats_label.text() == tr('files_stats').format(without=12, total=345) and w.badge_label.text() == '12'
    w._on_stats_loaded({})
    assert w.stats_label.text() == tr('files_stats').format(without=0, total=0) and not w.badge_label.isVisibleTo(w)
    w._on_error('Boom')
    assert w.stats_label.text() == tr('error_status').format(message='Boom')
    w._update_status_dot(True)
    assert T.legacy_mat_green in w.status_dot.styleSheet()
    w._update_status_dot(False)
    assert T.legacy_mat_red in w.status_dot.styleSheet()


def test_videos_vuoti(qt):
    w = make(videos=[])
    assert w.video_table.rowCount() == 0 and not w.import_all_btn.isEnabled()
    w._on_videos_loaded({})
    assert w.videos_data == [] and not w.badge_label.isVisibleTo(w)


def test_configurazione_mancante(qt):
    from utils.config import get_config
    from utils.translations import tr
    get_config().set('library_scanner_url', '')
    get_config().set('library_scanner_api_key', '')
    w = make(videos=None)
    w.refresh_data()
    assert w.stats_label.text() == tr('config_missing') and w.worker is None


@pytest.mark.parametrize('name,exp', [
    ('Film.ITA.mkv', 'ita'), ('Film.Italian.1080p.mkv', 'ita'), ('Film.[ITA].mkv', 'ita'), ('Film_nuita_x.mkv', 'ita'),
    ('Film.ENG.mkv', 'foreign'), ('Film.French.mkv', 'foreign'), ('Film.ita.eng.mkv', 'ita'), ('Film.mkv', 'unknown'),
    ('Film.nueng.mkv', 'foreign'), ('Capitan.Italia.mkv', 'unknown'), ('Spaghetti.mkv', 'unknown'), ('Rus.mkv', 'foreign'), ('GERMANY.mkv', 'unknown')])
def test_rilevamento_lingua_dal_nome(qt, name, exp):
    from gui.library_scanner_widget import _detect_italian
    assert _detect_italian(name) == exp


@pytest.mark.parametrize('days,col', [(31, 'pink'), (30, 'amber'), (15, 'amber'), (14, None), (0, None)])
def test_soglie_dei_giorni(qt, days, col):
    from PyQt6.QtGui import QColor
    from gui.design_tokens import T
    w = make(videos=[{'id': 1, 'filename': 'a.mkv', 'windows_path': 'a', 'days_without_subs': days}])
    got = w.video_table.item(0, 2).foreground().color().name()
    colors = {'pink': QColor(T.legacy_pink).name(), 'amber': QColor(T.legacy_mat_amber).name()}
    if col:
        assert got == colors[col]
    else:
        assert got not in colors.values()
