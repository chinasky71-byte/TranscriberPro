# -*- coding: utf-8 -*-
"""G2 (fase 0 della web UI): CARATTERIZZAZIONE di gui/sync_dialog.py (scheda "Coda" e avvio dei worker).

Passa identica sul codice vecchio e su quello con la logica della tabella in core/services/sync_batch_plan.py: celle della tabella,
stati, riepilogo, scelta manuale dell'SRT, spunte, duplicati, avvio della coda con i soli lavori eseguibili, esiti. Qt offscreen, file
veri in una cartella temporanea, worker e finestre di dialogo finti."""
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
    cfg.reset_config()


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


@pytest.fixture
def folders(tmp_path):
    v = tmp_path / 'video'
    s = tmp_path / 'srt'
    v.mkdir()
    s.mkdir()
    for n in ('Show.S01E01.mkv', 'Show.S01E02.mkv', 'Film.2020.mkv', 'Solo.Video.mkv'):
        (v / n).write_bytes(b'x')
    for n in ('Show.S01E01.it.srt', 'Show.S01E02.it.srt', 'Film.2020.srt', 'Orfano.Totale.srt', 'Film.2020.synced.it.srt'):
        (s / n).write_text('1\n', encoding='utf-8')
    return v, s


def make(folders):
    from gui.sync_dialog import SyncDialog
    d = SyncDialog()
    d.bv_dir.setText(str(folders[0]))
    d.bs_dir.setText(str(folders[1]))
    d._batch_pair()
    return d


def cells(d):
    return [[d.b_table.item(r, c).text() for c in (1, 3, 4)] + [d.b_table.item(r, 0).checkState().name,
            d.b_table.cellWidget(r, 2).currentText()] for r in range(d.b_table.rowCount())]


def test_abbinamento_e_celle(qt, folders):
    from utils.translations import tr
    d = make(folders)
    assert d.b_table.rowCount() == 4
    rows = {r[0]: r for r in cells(d)}
    s = folders[1]
    assert rows['Show.S01E01.mkv'][1:] == [str(s / 'Show.S01E01.synced.it.srt'), tr('sync_batch_state_ready'), 'Checked', 'Show.S01E01.it.srt']
    assert rows['Film.2020.mkv'][2] == tr('sync_batch_state_ready') and rows['Film.2020.mkv'][4] == 'Film.2020.srt'
    assert rows['Solo.Video.mkv'][1:] == ['', tr('sync_batch_state_nosrt'), 'Unchecked', tr('sync_batch_none')]
    assert d.b_summary.text() == tr('sync_batch_summary').format(ready=3, check=0, nosrt=1, left=1)
    combo = d.b_table.cellWidget(0, 2)
    assert combo.count() == 1 + 5                         # nessuno + i 5 SRT della cartella (anche il .synced.)


def test_cartelle_vuote_avvisano(qt, folders, boxes):
    from gui.sync_dialog import SyncDialog
    from utils.translations import tr
    d = SyncDialog()
    d._batch_pair()
    assert boxes == [('warning', tr('warning'), tr('sync_batch_nothing'))] and d.b_table.rowCount() == 0


def test_scelta_manuale_srt_e_spunta(qt, folders):
    from utils.translations import tr
    d = make(folders)
    r = next(i for i, c in enumerate(cells(d)) if c[0] == 'Solo.Video.mkv')
    combo = d.b_table.cellWidget(r, 2)
    combo.setCurrentIndex(combo.findText('Orfano.Totale.srt'))
    row = cells(d)[r]
    assert row[2] == tr('sync_batch_state_ready') and row[3] == 'Checked'
    assert row[1] == str(folders[1] / 'Orfano.Totale.synced.it.srt')
    d.b_table.item(r, 0).setCheckState(__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.CheckState.Unchecked)
    assert d.b_table.item(r, 0).checkState().name == 'Unchecked'
    assert d._pairs[r].include is False
    combo.setCurrentIndex(0)                                # torna a nessuno
    row = cells(d)[r]
    assert row[1] == '' and row[2] == tr('sync_batch_state_nosrt') and row[3] == 'Unchecked'


def test_duplicati(qt, folders):
    from utils.translations import tr
    d = make(folders)
    names = [c[0] for c in cells(d)]
    a, b = names.index('Show.S01E01.mkv'), names.index('Show.S01E02.mkv')
    d.b_table.cellWidget(b, 2).setCurrentIndex(d.b_table.cellWidget(b, 2).findText('Show.S01E01.it.srt'))
    st = {c[0]: c[2] for c in cells(d)}
    assert st['Show.S01E01.mkv'] == tr('sync_batch_state_dup') and st['Show.S01E02.mkv'] == tr('sync_batch_state_dup')
    assert d.b_summary.text() == tr('sync_batch_summary').format(ready=1, check=0, nosrt=1, left=1)       # i non abbinati si contano solo all'abbinamento


def test_nota_di_controllo_per_abbinamento_incerto(qt, tmp_path):
    from utils.translations import tr
    v, s = tmp_path / 'v', tmp_path / 's'
    v.mkdir()
    s.mkdir()
    (v / 'Casa Dolce Casa 2019 1080p.mkv').write_bytes(b'x')
    (s / 'Casa Dolce 2019.srt').write_text('1', encoding='utf-8')
    from gui.sync_dialog import SyncDialog
    d = SyncDialog()
    d.bv_dir.setText(str(v))
    d.bs_dir.setText(str(s))
    d._batch_pair()
    from core import sync_pairing as SP
    pairs, _ = SP.pair_files(SP.list_files(v, SP.VIDEO_EXT), SP.list_files(s, ('.srt',)))
    expect = tr('sync_batch_state_check') if pairs[0].note else tr('sync_batch_state_ready')
    assert cells(d)[0][2] == expect


def test_sottocartelle_e_etichetta_srt(qt, tmp_path):
    v, s = tmp_path / 'v', tmp_path / 's'
    (v / 'a').mkdir(parents=True)
    (s / 'b').mkdir(parents=True)
    (v / 'a' / 'Film.mkv').write_bytes(b'x')
    (s / 'b' / 'Film.srt').write_text('1', encoding='utf-8')
    from gui.sync_dialog import SyncDialog
    d = SyncDialog()
    d.bv_dir.setText(str(v))
    d.bs_dir.setText(str(s))
    d._batch_pair()
    assert d.b_table.rowCount() == 0                              # senza "sottocartelle" non vede nulla
    d.b_recursive.setChecked(True)
    d._batch_pair()
    assert d.b_table.rowCount() == 1
    assert d.b_table.cellWidget(0, 2).currentText() == str(Path('b') / 'Film.srt')       # etichetta relativa alla cartella SRT


class FakeBatch:
    instances = []

    def __init__(self, pairs, parent=None):
        from PyQt6.QtCore import QObject, pyqtSignal
        self.pairs = pairs
        self.started = False
        FakeBatch.instances.append(self)
        sigs = type('S', (QObject,), {'log_message': pyqtSignal(str), 'pair_started': pyqtSignal(int, str),
                                      'pair_progress': pyqtSignal(int, int), 'pair_finished': pyqtSignal(int, bool, str),
                                      'all_done': pyqtSignal(int, int, int)})
        self.s = sigs()
        for n in ('log_message', 'pair_started', 'pair_progress', 'pair_finished', 'all_done'):
            setattr(self, n, getattr(self.s, n))

    def start(self):
        self.started = True

    def isRunning(self):
        return self.started

    def cancel(self):
        self.cancelled = True


def test_avvio_coda_e_esiti(qt, folders, boxes, monkeypatch):
    import gui.sync_dialog as sd
    from utils.translations import tr
    FakeBatch.instances.clear()
    monkeypatch.setattr(sd, 'SyncBatchWorker', FakeBatch)
    d = make(folders)
    d.b_table.cellWidget(0, 2)       # righe presenti
    expected = [c[0] for c in cells(d) if c[2] == tr('sync_batch_state_ready')]
    d.tabs.setCurrentIndex(1)
    d._start()
    w = FakeBatch.instances[0]
    assert w.started and [Path(p.video).name for p in w.pairs] == expected
    assert boxes[0][0] == 'question' and not d.start_btn.isEnabled() and d.cancel_btn.isEnabled() and not d.tabs.isEnabled()
    assert d.parent() is None and d.progress_bar.value() == 0
    names = [c[0] for c in cells(d)]
    i0 = names.index(Path(w.pairs[0].video).name)
    w.pair_started.emit(0, str(w.pairs[0].video))
    assert cells(d)[i0][2] == tr('sync_batch_state_running')
    w.pair_progress.emit(0, 50)
    assert cells(d)[i0][2] == '50%' and d.progress_bar.value() == int((0 + 0.5) / 3 * 100)
    w.pair_finished.emit(0, True, 'o')
    assert cells(d)[i0][2] == tr('sync_batch_state_ok') and d.progress_bar.value() == int(1 / 3 * 100)
    w.pair_finished.emit(1, False, 'e')
    i1 = names.index(Path(w.pairs[1].video).name)
    assert cells(d)[i1][2] == tr('sync_batch_state_failed')
    boxes.clear()
    w.all_done.emit(1, 1, 1)
    i2 = names.index(Path(w.pairs[2].video).name)
    assert cells(d)[i2][2] == tr('sync_batch_state_skipped')
    assert d.start_btn.isEnabled() and not d.cancel_btn.isEnabled() and d.tabs.isEnabled()
    assert boxes == [('information', tr('sync_done_title'), tr('sync_batch_done').format(ok=1, fail=1, skipped=1))]
    assert tr('sync_batch_done').format(ok=1, fail=1, skipped=1) in d.log_edit.toPlainText()


def test_avvio_coda_rifiutato_o_vuoto(qt, folders, boxes, monkeypatch):
    import gui.sync_dialog as sd
    from PyQt6.QtWidgets import QMessageBox
    from utils.translations import tr
    FakeBatch.instances.clear()
    monkeypatch.setattr(sd, 'SyncBatchWorker', FakeBatch)
    d = make(folders)
    boxes.answer['q'] = QMessageBox.StandardButton.No
    d._start_batch()
    assert FakeBatch.instances == [] and d.start_btn.isEnabled()
    from gui.sync_dialog import SyncDialog
    e = SyncDialog()
    boxes.clear()
    e._start_batch()
    assert boxes == [('warning', tr('warning'), tr('sync_batch_nothing'))]
