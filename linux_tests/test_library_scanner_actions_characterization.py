# -*- coding: utf-8 -*-
"""G4c+G4d (fase 0 della web UI): CARATTERIZZAZIONE delle azioni del Library Scanner (gui/library_scanner_widget.py): import in coda con
la mappa dei percorsi, conversione ASS/SSA, notifica del sottotitolo, Superpower, batch OCR, coda OCR differita e gestione degli esiti del
worker OCR.

Passa identica sul codice vecchio e su quello con la logica in core/services/library_actions.py. Qt offscreen, main_window finta
(coda, file_list, log, job OCR), OcrWorker / _ApiCallWorker / finestre di dialogo finti."""
import json
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


class FakeShutdownBox:
    def __init__(self):
        self.checked = False

    def isChecked(self):
        return self.checked


class FakeMain:
    def __init__(self):
        from PyQt6.QtCore import QMutex
        from PyQt6.QtWidgets import QListWidget
        self.queue_mutex = QMutex()
        self.processing_queue = []
        self.is_processing = False
        self.file_list = QListWidget()
        self.logs = []
        self.ocr_jobs = []
        self.ocr_status = []
        self.remaining_updates = 0
        self.shutdown_checkbox = FakeShutdownBox()
        self.shutdowns = []

    def log_message(self, m):
        self.logs.append(m)

    def add_ocr_jobs(self, jobs):
        self.ocr_jobs.extend(jobs)

    def set_ocr_job_status(self, path, status, progress):
        self.ocr_status.append((path, status, progress))

    def update_remaining_files_label(self):
        self.remaining_updates += 1

    def _make_file_item(self, path):
        from PyQt6.QtWidgets import QListWidgetItem
        return QListWidgetItem(Path(path).name)

    def shutdown_system(self):
        self.shutdowns.append(1)


@pytest.fixture
def boxes(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    class Seen(list):
        pass
    seen = Seen()
    answer = {'q': QMessageBox.StandardButton.Yes}
    for kind in ('warning', 'information', 'critical'):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda p, t, m, *a, _k=kind, **k: seen.append((_k, t, m)) or 0))
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda p, t, m, *a, **k: seen.append(('question', t, m)) or answer['q']))
    seen.answer = answer
    return seen


class FakeApiWorker:
    instances = []

    def __init__(self, method, url, api_key, json_body=None, params=None, timeout=10):
        from PyQt6.QtCore import QObject, pyqtSignal
        self.args = (method, url, api_key, json_body, params, timeout)
        self.started = False
        FakeApiWorker.instances.append(self)
        S = type('S', (QObject,), {'done': pyqtSignal(int, str), 'finished': pyqtSignal()})
        self._s = S()
        self.done, self.finished = self._s.done, self._s.finished

    def start(self):
        self.started = True


def _fake_ocr_worker_class():
    from PyQt6.QtCore import QObject, pyqtSignal

    class FakeOcrWorker(QObject):
        instances = []
        events_ready = pyqtSignal(object, str)
        auto_done = pyqtSignal(bool)
        unsupported = pyqtSignal(str)
        lang_unsupported = pyqtSignal(str)
        error = pyqtSignal(str)
        log_message = pyqtSignal(str)
        progress = pyqtSignal(int, str)
        finished = pyqtSignal()
        writeback_done = pyqtSignal(bool)

        def __init__(self, video_path, config, strategy, mode='ocr', srt_text='', language='ita', kind='pgs', parent=None):
            super().__init__()
            self.args = dict(video_path=video_path, strategy=strategy, mode=mode, srt_text=srt_text, language=language, kind=kind)
            self.started = False
            FakeOcrWorker.instances.append(self)

        def start(self):
            self.started = True
    return FakeOcrWorker


FakeOcrWorker = _fake_ocr_worker_class()


@pytest.fixture
def fakes(monkeypatch):
    import gui.library_scanner_widget as lw
    import gui.ocr_worker as ow
    FakeApiWorker.instances.clear()
    FakeOcrWorker.instances.clear()
    monkeypatch.setattr(lw, '_ApiCallWorker', FakeApiWorker)
    monkeypatch.setattr(ow, 'OcrWorker', FakeOcrWorker)


NAME_A = Path(r'V:\a.mkv').name        # dipende dal sistema (su Windows 'a.mkv', su Linux tutto il percorso)

VIDEOS = [
    {'id': 11, 'filename': 'a.mkv', 'windows_path': r'V:\a.mkv', 'days_without_subs': 3, 'bitmap_format': 'pgs', 'has_only_bitmap_subs': True},
    {'id': 12, 'filename': 'b.mkv', 'windows_path': r'V:\b.mkv', 'days_without_subs': 5},
    {'id': 13, 'filename': 'c.mkv', 'windows_path': r'V:\c.mkv', 'days_without_subs': 7, 'has_italian_convertible_subs': True},
]


def make(main=None, load=True, configured=True):
    from gui.library_scanner_widget import LibraryScannerWidget
    from utils.config import get_config
    if configured:
        get_config().set('library_scanner_url', 'http://srv:6680/')
        get_config().set('library_scanner_api_key', ' KEY ')
    w = LibraryScannerWidget(main or FakeMain())
    if load:
        w._on_videos_loaded({'videos': [dict(v) for v in VIDEOS]})
    return w


def rows(w):
    return {w.video_table.item(r, 0).text(): r for r in range(w.video_table.rowCount())}


# ------------------------------------------------------------------------------------------------------- import in coda
def test_import_paths_aggiunge_e_deduplica(qt):
    main = FakeMain()
    w = make(main, load=False)
    assert w._import_paths([]) == 0
    assert w._import_paths([r'V:\a.mkv', r'V:\b.mkv', r'V:\a.mkv', '']) == 2
    assert main.processing_queue == [r'V:\a.mkv', r'V:\b.mkv'] and main.file_list.count() == 2 and main.remaining_updates == 1
    assert main.file_list.currentRow() == 1
    assert w._import_paths([r'V:\a.mkv']) == 0 and main.remaining_updates == 1


def test_import_con_mappa_percorsi(qt):
    from utils.config import get_config
    get_config().set('library_scanner_path_map', 'V:\\=/mnt/v/')
    main = FakeMain()
    w = make(main, load=False)
    assert w._import_paths([r'V:\Film\x.mkv', '/mnt/v/Film/x.mkv']) == 1
    assert main.processing_queue == ['/mnt/v/Film/x.mkv']


def test_import_salta_i_file_in_lavorazione(qt):
    main = FakeMain()

    class QS:
        def is_active(self, p):
            return p == r'V:\b.mkv'
    main.queue_service = QS()
    w = make(main, load=False)
    assert w._import_paths([r'V:\a.mkv', r'V:\b.mkv']) == 1 and main.processing_queue == [r'V:\a.mkv']


def test_import_singolo_e_bottone(qt, fakes, boxes):
    from utils.translations import tr
    main = FakeMain()
    w = make(main)
    r = rows(w)
    btn = w.video_table.cellWidget(r['b.mkv'], 4)
    btn.click()
    assert main.processing_queue == [r'V:\b.mkv']
    assert (btn.text(), btn.isEnabled(), btn.toolTip()) == ('✓', False, tr('already_queued'))
    w._import_single(r['b.mkv'])                              # gia' in coda: nessuna aggiunta
    assert main.processing_queue == [r'V:\b.mkv']
    w._import_single(99)                                      # riga inesistente: nessun errore


def test_import_singolo_di_un_file_ass_converte_sul_server(qt, fakes, boxes):
    main = FakeMain()
    w = make(main)
    w._import_single(rows(w)['c.mkv'])
    assert main.processing_queue == [] and len(FakeApiWorker.instances) == 1
    assert FakeApiWorker.instances[0].args == ('post', 'http://srv:6680/api/subtitles/convert/start', 'KEY', {'video_ids': [13]}, None, 10)


def test_importa_tutti_solo_righe_visibili(qt, fakes, boxes):
    from utils.translations import tr
    main = FakeMain()
    w = make(main)
    w.days_spinbox.setValue(5)                                # nasconde a.mkv (3 giorni)
    w._import_all()
    assert main.processing_queue == [r'V:\b.mkv', r'V:\c.mkv'] and main.logs[-1] == tr('files_imported_log').format(added=2)
    r = rows(w)
    assert [w.video_table.cellWidget(r[n], 4).text() for n in ('a.mkv', 'b.mkv', 'c.mkv')] == ['', '✓', '✓']
    n_logs = len(main.logs)
    w._import_all()                                           # nulla di nuovo: nessun log
    assert len(main.logs) == n_logs


def test_importa_tutti_con_filtro_ass_converte_tutto(qt, fakes, boxes, monkeypatch):
    main = FakeMain()
    w = make(main)
    monkeypatch.setattr(w, 'refresh_data', lambda: None)
    w.format_combo.setCurrentIndex(w.format_combo.findData('assssa'))
    w._import_all()
    assert main.processing_queue == [] and FakeApiWorker.instances[0].args[3] == {}


def test_importa_tutti_senza_righe(qt):
    main = FakeMain()
    w = make(main, load=False)
    w._import_all()
    assert main.processing_queue == []


# ------------------------------------------------------------------------------------------------------------- ASS/SSA
def test_conversione_ass_senza_configurazione(qt, fakes, boxes):
    from utils.translations import tr
    w = make(configured=False)
    from utils.config import get_config
    get_config().set('library_scanner_url', '')
    w._start_ass_conversion([1])
    assert boxes == [('warning', tr('ls_ass_title'), tr('ls_not_configured'))] and FakeApiWorker.instances == []


def test_conversione_ass_richiesta_e_tracciamento(qt, fakes):
    w = make()
    w._start_ass_conversion([1, 2])
    wk = FakeApiWorker.instances[0]
    assert wk.started and wk.args == ('post', 'http://srv:6680/api/subtitles/convert/start', 'KEY', {'video_ids': [1, 2]}, None, 10)
    assert w._api_workers == [wk]
    wk.finished.emit()
    assert w._api_workers == []
    w._untrack_api_worker(wk)                                 # gia' rimosso: nessun errore


@pytest.mark.parametrize('ids,status,text,level,logkey', [
    ([5, 6], 200, '', 'information', 'ls_ass_log_started'),
    ([], 200, '', 'information', 'ls_ass_log_started_all'),
    ([5], 0, 'timeout', 'warning', 'ls_ass_log_conn_err'),
    ([5], 500, 'x' * 300, 'warning', 'ls_ass_log_srv_err'),
])
def test_risposta_conversione_ass(qt, fakes, boxes, ids, status, text, level, logkey):
    from utils.translations import tr
    main = FakeMain()
    w = make(main)
    w._on_ass_conversion_reply(status, text, ids)
    if status == 200:
        desc = tr('ls_n_files').format(n=len(ids)) if ids else tr('ls_all_pending')
        assert main.logs[-1] == (tr(logkey).format(desc=desc) if ids else tr(logkey))
        assert boxes == [('information', tr('ls_ass_title'), tr('ls_ass_started_body').format(desc=desc))]
    elif status == 0:
        assert main.logs[-1] == tr(logkey).format(text=text)
        assert boxes == [('warning', tr('ls_ass_title'), tr('ls_conn_err').format(text=text))]
    else:
        assert main.logs[-1] == tr(logkey).format(status=status)
        assert boxes == [('warning', tr('ls_ass_title'), tr('ls_srv_err').format(status=status, text=text[:200]))]


# ------------------------------------------------------------------------------------------------------------ notifica
def test_notifica_sottotitolo_creato(qt, monkeypatch):
    import gui.library_scanner_widget as lw
    from utils.config import get_config
    started = []

    class NW:
        def __init__(self, url, key, path):
            from PyQt6.QtCore import QObject, pyqtSignal
            self.args = (url, key, path)
            S = type('S', (QObject,), {'done': pyqtSignal(bool), 'finished': pyqtSignal()})
            self._s = S()
            self.done, self.finished = self._s.done, self._s.finished
            started.append(self)

        def start(self):
            self.args = self.args + ('started',)
    monkeypatch.setattr(lw, '_NotifyWorker', NW)
    get_config().set('library_scanner_path_map', 'V:\\=/mnt/v/')
    w = make()
    w.is_loaded = False
    w.notify_subtitle_created('/mnt/v/x.mkv')
    assert started == []                                      # non caricato: niente
    w.is_loaded = True
    w.notify_subtitle_created('/mnt/v/x.mkv')
    assert started[0].args == ('http://srv:6680/', 'KEY', 'V:\\x.mkv', 'started')       # locale -> server, URL e chiave ripuliti dagli spazi
    assert w._notify_workers == [started[0]]
    started[0].finished.emit()
    assert w._notify_workers == []
    get_config().set('library_scanner_api_key', '')
    w.notify_subtitle_created('/mnt/v/y.mkv')
    assert len(started) == 1


def test_notifica_completata_ricarica_solo_fuori_batch(qt, monkeypatch):
    w = make()
    calls = []
    monkeypatch.setattr(w, 'refresh_data', lambda: calls.append(1))
    w._on_notify_done(False)
    w._on_notify_done(True)
    w._ocr_batch_active = True
    w._on_notify_done(True)
    assert calls == [1]


# ------------------------------------------------------------------------------------------------------- OCR immediato
def test_ocr_immediato_con_pipeline_attiva_viene_differito(qt, fakes):
    from utils.translations import tr
    main = FakeMain()
    main.is_processing = True
    w = make(main)
    w._start_bitmap_ocr(r'V:\a.mkv', 'pgs')
    assert w._ocr_deferred_queue == [(r'V:\a.mkv', 'pgs', False)] and FakeOcrWorker.instances == []
    assert main.ocr_jobs == [(r'V:\a.mkv', 'PGS')] and main.ocr_status == [(r'V:\a.mkv', 'queued', 0)]
    assert main.logs[-1] == tr('ls_ocr_queued_log').format(name=NAME_A)
    assert w.is_deferred_ocr(r'V:\a.mkv') is True and w.is_deferred_ocr('altro') is False
    w.set_deferred_ocr_mode([r'V:\a.mkv'], 'auto')
    assert w._ocr_mode_override == {r'V:\a.mkv': 'auto'}
    w.set_deferred_ocr_mode([r'V:\a.mkv'], None)
    assert w._ocr_mode_override == {}


def test_ocr_immediato_parte_con_strategia_e_mappa(qt, fakes):
    from core.pgs_types import CFG_STRATEGY
    from utils.config import get_config
    from utils.translations import tr
    get_config().set('library_scanner_path_map', 'V:\\=/mnt/v/')
    get_config().set(CFG_STRATEGY, 'review')
    main = FakeMain()
    w = make(main)
    w._start_bitmap_ocr(r'V:\a.mkv', 'vobsub')
    wk = FakeOcrWorker.instances[0]
    assert wk.started and wk.args == dict(video_path='/mnt/v/a.mkv', strategy='review', mode='ocr', srt_text='', language='ita', kind='vobsub')
    assert main.ocr_jobs == [(r'V:\a.mkv', 'VOBSUB')] and main.ocr_status[-1] == (r'V:\a.mkv', 'processing', 0)
    assert main.logs[-1] == tr('ls_ocr_started_log').format(kind='vobsub', strategy='review', name=NAME_A)
    assert w._ocr_strategy_used == 'review'


@pytest.mark.parametrize('force,override,cfg,exp', [(True, None, 'review', 'auto'), (False, 'auto', 'review', 'auto'),
                                                    (False, 'review', 'auto', 'review'), (False, 'boh', 'auto', 'auto'),
                                                    (True, 'review', 'review', 'review')])
def test_strategia_dell_ocr(qt, fakes, force, override, cfg, exp):
    from core.pgs_types import CFG_STRATEGY
    from utils.config import get_config
    get_config().set(CFG_STRATEGY, cfg)
    w = make()
    w._start_bitmap_ocr(r'V:\a.mkv', 'pgs', force_auto=force, strategy_override=override)
    assert FakeOcrWorker.instances[0].args['strategy'] == exp


def test_ocr_gia_in_corso_e_percorso_vuoto(qt, fakes, boxes):
    from utils.translations import tr
    w = make()
    w._start_bitmap_ocr('', 'pgs')
    assert FakeOcrWorker.instances == []
    w._start_bitmap_ocr(r'V:\a.mkv', 'pgs')
    w._start_bitmap_ocr(r'V:\b.mkv', 'pgs')
    assert len(FakeOcrWorker.instances) == 1 and boxes == [('information', tr('ocr_section_title'), tr('ls_ocr_other_running'))]


def test_avanzamento_ocr(qt, fakes):
    main = FakeMain()
    w = make(main)
    w._start_bitmap_ocr(r'V:\a.mkv', 'pgs')
    w._on_ocr_progress(40, 'OCR')
    assert w.ocr_progress_label.text() == f'OCR · {NAME_A} — OCR 40%' and main.ocr_status[-1] == (r'V:\a.mkv', 'processing', 40)
    w._ocr_batch_active, w._ocr_batch_ok, w._ocr_batch_fail, w._ocr_batch_total = True, 1, 0, 3
    w._on_ocr_progress(10, 'estrazione')
    assert w.ocr_progress_label.text() == f'OCR batch 2/3 · {NAME_A} — estrazione 10%'
    w._ocr_batch_ok, w._ocr_batch_fail = 2, 1
    w._on_ocr_progress(10, 'x')
    assert w.ocr_progress_label.text().startswith('OCR batch 3/3 · ')


# ------------------------------------------------------------------------------------------- esiti del worker OCR
def started(w, main=None, batch=False):
    w._start_bitmap_ocr(r'V:\a.mkv', 'pgs')
    if batch:
        w._ocr_batch_active = True
    return FakeOcrWorker.instances[-1]


def test_esito_auto_singolo(qt, fakes, boxes, monkeypatch):
    from utils.translations import tr
    main = FakeMain()
    w = make(main)
    monkeypatch.setattr(w, 'notify_subtitle_created', lambda p: main.logs.append(('notify', p)))
    monkeypatch.setattr(w, '_auto_refresh', lambda: main.logs.append('refresh'))
    started(w)
    w._on_ocr_auto_done(True)
    assert main.ocr_status[-1] == (r'V:\a.mkv', 'completed', 100) and ('notify', r'V:\a.mkv') in main.logs and main.logs[-1] == 'refresh'
    assert boxes[-1] == ('information', tr('ocr_section_title'), tr('ls_conv_done').format(name=NAME_A))
    btn = w.video_table.cellWidget(rows(w)['a.mkv'], 4)
    assert (btn.text(), btn.isEnabled()) == ('✓', False)
    w._on_ocr_auto_done(False)
    assert main.ocr_status[-1] == (r'V:\a.mkv', 'failed', 100)
    assert boxes[-1] == ('warning', tr('ocr_section_title'), tr('ls_conv_failed').format(name=NAME_A))


def test_esiti_in_batch_contano_senza_dialoghi(qt, fakes, boxes):
    main = FakeMain()
    w = make(main)
    started(w, batch=True)
    w._ocr_batch_ok = w._ocr_batch_fail = 0
    w._on_ocr_auto_done(True)
    w._on_ocr_auto_done(False)
    w._on_ocr_unsupported('no')
    w._on_ocr_error('boom')
    w._on_ocr_lang_unsupported('lang')
    assert (w._ocr_batch_ok, w._ocr_batch_fail) == (1, 3) and boxes == []
    assert main.ocr_status[-1] == (r'V:\a.mkv', 'completed', 100)             # lingua non gestita: completato, non fallito


def test_esiti_singoli_con_dialoghi(qt, fakes, boxes):
    from utils.translations import tr
    main = FakeMain()
    w = make(main)
    started(w)
    w._on_ocr_unsupported('formato X')
    assert boxes[-1] == ('information', tr('ocr_section_title'), f'{NAME_A}\n\nformato X') and main.ocr_status[-1] == (r'V:\a.mkv', 'failed', 0)
    w._on_ocr_lang_unsupported('klingon')
    assert boxes[-1] == ('information', tr('ocr_section_title'), tr('ls_lang_skipped').format(name=NAME_A, msg='klingon'))
    assert main.ocr_status[-1] == (r'V:\a.mkv', 'completed', 100)
    w._on_ocr_error('boom')
    assert boxes[-1] == ('warning', tr('ocr_section_title'), tr('ls_ocr_error').format(name=NAME_A, msg='boom'))


def test_revisione_e_writeback(qt, fakes, boxes, monkeypatch):
    import gui.ocr_review_dialog as rd
    from PyQt6.QtWidgets import QDialog
    from utils.translations import tr
    main = FakeMain()
    w = make(main)
    monkeypatch.setattr(w, 'notify_subtitle_created', lambda p: None)
    monkeypatch.setattr(w, '_auto_refresh', lambda: None)

    class Dlg:
        accepted = True

        def __init__(self, events, parent=None):
            self.events = events

        def exec(self):
            return QDialog.DialogCode.Accepted if Dlg.accepted else QDialog.DialogCode.Rejected

        def get_srt(self):
            return '1\nSRT'
    monkeypatch.setattr(rd, 'OcrReviewDialog', Dlg)
    started(w)
    w._on_ocr_events_ready(['E'], 'it')
    wb = FakeOcrWorker.instances[-1]
    assert wb.started and wb.args == dict(video_path=r'V:\a.mkv', strategy='review' if w._ocr_strategy_used == 'review' else w._ocr_strategy_used,
                                          mode='writeback', srt_text='1\nSRT', language='it', kind='pgs')
    w._on_ocr_writeback_done(True)
    assert boxes[-1] == ('information', tr('ocr_section_title'), tr('ls_srt_written').format(name=NAME_A))
    w._on_ocr_writeback_done(False)
    assert boxes[-1] == ('warning', tr('ocr_section_title'), tr('ls_srt_write_failed').format(name=NAME_A))
    Dlg.accepted = False
    started_before = len(FakeOcrWorker.instances)
    w._ocr_worker = None
    w._on_ocr_events_ready(['E'], 'it')
    assert len(FakeOcrWorker.instances) == started_before
    assert main.logs[-1] == tr('ls_ocr_cancel_log').format(name=NAME_A) and main.ocr_status[-1] == (r'V:\a.mkv', 'failed', 0)


# ------------------------------------------------------------------------------------------------ Superpower e batch
def test_superpower_senza_configurazione_o_con_ocr_in_corso(qt, fakes, boxes):
    from utils.config import get_config
    from utils.translations import tr
    w = make()
    get_config().set('library_scanner_api_key', '')
    w._superpower_ocr()
    assert boxes[-1] == ('warning', '⚡ Superpower', tr('ls_not_configured'))
    get_config().set('library_scanner_api_key', 'K')
    w._ocr_worker = object()
    w._superpower_ocr()
    assert boxes[-1] == ('information', '⚡ Superpower', tr('ls_ocr_running'))


def test_superpower_conferma_e_richiesta(qt, fakes, boxes):
    from PyQt6.QtWidgets import QMessageBox
    from utils.translations import tr
    main = FakeMain()
    w = make(main)
    boxes.answer['q'] = QMessageBox.StandardButton.No
    w._superpower_ocr()
    assert FakeApiWorker.instances == [] and boxes[-1] == ('question', '⚡ Superpower OCR', tr('ls_sp_confirm'))
    boxes.answer['q'] = QMessageBox.StandardButton.Yes
    w._superpower_ocr()
    wk = FakeApiWorker.instances[0]
    assert wk.started and wk.args == ('get', 'http://srv:6680/api/subtitles/list', 'KEY', None, {'issue_type': 'bitmap', 'limit': 500}, 15)
    assert main.logs[-1] == tr('ls_sp_list_log')


def test_risposta_superpower(qt, fakes, boxes):
    from utils.translations import tr
    main = FakeMain()
    w = make(main)
    w._on_superpower_list_reply(0, 'rete giu')
    assert boxes[-1] == ('warning', '⚡ Superpower', tr('ls_sp_list_err').format(err='rete giu'))
    w._on_superpower_list_reply(503, 'y' * 300)
    assert boxes[-1][2] == tr('ls_sp_list_err').format(err='HTTP 503: ' + 'y' * 200)
    w._on_superpower_list_reply(200, 'non json')
    assert boxes[-1][0] == 'warning' and boxes[-1][2].startswith(tr('ls_sp_bad_reply').format(err='')[:10])
    w._on_superpower_list_reply(200, json.dumps({'videos': [{'bitmap_format': None, 'windows_path': 'x'}, {'bitmap_format': 'pgs', 'windows_path': ''}]}))
    assert boxes[-1] == ('information', '⚡ Superpower', tr('ls_sp_none'))
    assert FakeOcrWorker.instances == []
    w._ocr_worker = object()
    w._on_superpower_list_reply(200, '{}')
    assert boxes[-1] == ('information', '⚡ Superpower', tr('ls_ocr_running'))


def test_superpower_avvia_il_batch_in_auto_e_in_sequenza(qt, fakes, boxes, monkeypatch):
    from utils.translations import tr
    main = FakeMain()
    w = make(main)
    monkeypatch.setattr(w, 'notify_subtitle_created', lambda p: None)
    monkeypatch.setattr(w, '_auto_refresh', lambda: main.logs.append('refresh'))
    body = {'videos': [{'bitmap_format': 'pgs', 'windows_path': r'V:\a.mkv'}, {'bitmap_format': 'vobsub', 'windows_path': r'V:\b.mkv'},
                       {'bitmap_format': 'mixed', 'windows_path': r'V:\c.mkv'}]}
    w._on_superpower_list_reply(200, json.dumps(body))
    assert w._ocr_superpower_active is True and w._ocr_batch_active is True and w._ocr_batch_total == 3
    assert main.ocr_jobs == [(r'V:\a.mkv', 'PGS'), (r'V:\b.mkv', 'VOBSUB'), (r'V:\c.mkv', 'PGS'), (r'V:\a.mkv', 'PGS')]       # il primo e' registrato due volte
    assert tr('ls_sp_acquired_log').format(n=3) in main.logs and tr('ls_batch_started_log').format(n=3) in main.logs
    wk = FakeOcrWorker.instances[0]
    assert wk.args['video_path'] == r'V:\a.mkv' and wk.args['strategy'] == 'auto'
    # il primo finisce: esito + fine fase -> avanza al secondo
    w._on_ocr_auto_done(True)
    wk.finished.emit()
    qt.processEvents()
    assert len(FakeOcrWorker.instances) == 2 and FakeOcrWorker.instances[1].args['kind'] == 'vobsub'
    w._on_ocr_error('boom')
    FakeOcrWorker.instances[1].finished.emit()
    qt.processEvents()
    w._on_ocr_auto_done(True)
    assert FakeOcrWorker.instances[2].args['kind'] == 'pgs'                 # un misto parte come PGS
    main.shutdown_checkbox.checked = True
    FakeOcrWorker.instances[2].finished.emit()
    qt.processEvents()
    assert (w._ocr_batch_ok, w._ocr_batch_fail, w._ocr_batch_active, w._ocr_superpower_active) == (2, 1, False, False)
    assert boxes[-1] == ('information', tr('ocr_section_title'), tr('ls_batch_done').format(ok=2, fail=1, total=3))
    assert tr('ls_sp_done_log') in main.logs and 'refresh' in main.logs and w.ocr_progress_label.text() == ''


def test_batch_con_spegnimento_programmato(qt, fakes, boxes, monkeypatch):
    from PyQt6.QtCore import QTimer
    main = FakeMain()
    main.shutdown_checkbox.checked = True
    w = make(main)
    monkeypatch.setattr(w, '_auto_refresh', lambda: None)
    singles = []
    monkeypatch.setattr(QTimer, 'singleShot', staticmethod(lambda ms, fn: singles.append((ms, fn))))
    w._ocr_batch_queue = []
    w._ocr_batch_active = True
    w._ocr_batch_ok = w._ocr_batch_fail = w._ocr_batch_total = 0
    w._ocr_batch_advance()
    assert singles == [(5000, main.shutdown_system)]


def test_batch_rifiutato_se_ocr_in_corso_o_vuoto(qt, fakes, boxes):
    from utils.translations import tr
    w = make()
    w._start_ocr_batch([])
    assert boxes == [] and getattr(w, '_ocr_batch_active', False) is False
    w._ocr_worker = object()
    w._start_ocr_batch([(r'V:\a.mkv', 'pgs')])
    assert boxes[-1] == ('information', tr('ocr_section_title'), tr('ls_ocr_other_running'))


# --------------------------------------------------------------------------------------------------- coda differita
def test_svuotamento_della_coda_differita(qt, fakes):
    main = FakeMain()
    w = make(main)
    w._drain_deferred_ocr()
    assert FakeOcrWorker.instances == []
    w._ocr_deferred_queue = [(r'V:\a.mkv', 'pgs', False), (r'V:\b.mkv', 'vobsub', True)]
    w._ocr_mode_override = {r'V:\a.mkv': 'auto'}
    main.is_processing = True
    w._drain_deferred_ocr()
    assert FakeOcrWorker.instances == []                     # la pipeline e' ripartita: aspetta
    main.is_processing = False
    w._ocr_worker = object()
    w._drain_deferred_ocr()
    assert FakeOcrWorker.instances == []                     # OCR gia' in corso
    w._ocr_worker = None
    w._drain_deferred_ocr()
    assert FakeOcrWorker.instances[0].args['video_path'] == r'V:\a.mkv' and FakeOcrWorker.instances[0].args['strategy'] == 'auto'
    assert w._ocr_mode_override == {} and len(w._ocr_deferred_queue) == 1


def test_fine_fase_azzera_il_worker_e_riparte_la_coda(qt, fakes):
    main = FakeMain()
    w = make(main)
    w._ocr_deferred_queue = [(r'V:\b.mkv', 'pgs', False)]
    started(w)
    wk = FakeOcrWorker.instances[0]
    wk.finished.emit()
    qt.processEvents()
    assert w._ocr_worker is not None and w._ocr_worker is FakeOcrWorker.instances[1]       # il differito e' partito
    assert FakeOcrWorker.instances[1].args['video_path'] == r'V:\b.mkv'
