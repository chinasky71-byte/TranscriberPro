# -*- coding: utf-8 -*-
"""Fase 2: cattura la finestra principale VERA di Qt (MainWindow, tema e font veri) in stati fissi, per misurare la web UI.

Uso (sul PC Windows, a finestra visibile, HOME isolata dal chiamante o da --home):
    python tpweb/proto/p2_qt_capture.py --out tpweb/proto/results/p2_qt_windows --scales 1.0 1.25 1.5 [--platform windows]

Per ogni scala e per ogni stato scrive <out>/<scala>/<stato>.png (grab della finestra, 1400x900 a scala 1) e <out>/<scala>/<stato>.json
(geometria di tutti i widget con objectName e di ogni riga della lista, in pixel logici). Stati:
  vuota            coda vuota, scheda Coda
  righe            tre righe: completato, in lavorazione al 45% con eccezione «ENG · mux», in coda
  filtro_attivi    come «righe» con il filtro «Attivi»
  filtro_coda      come «righe» con il filtro «Coda»
  filtro_completati come «righe» con il filtro «Completati»
  pipeline         come «righe» con la card «Pipeline in corso» attiva (anteprima dei passi fissa)
  cronologia       scheda Cronologia con due voci
Non lancia nessun elaborazione vera: le righe e i passi sono scritti direttamente. Non tocca config.json ne' history.json veri
(HOME isolata + config e cronologia puntati a una cartella temporanea)."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATES = ['vuota', 'righe', 'filtro_attivi', 'filtro_coda', 'filtro_completati', 'pipeline', 'cronologia']
SETTINGS_STATES = ['imp_general', 'imp_jobs', 'imp_transcription', 'imp_translation', 'imp_batch', 'imp_opensubtitles', 'imp_ocr']      # finestra Impostazioni, una per scheda

CHILD = r'''
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(%(root)r); sys.path.insert(0, str(ROOT))
home = Path(%(home)r); home.mkdir(parents=True, exist_ok=True)
os.environ['HOME'] = os.environ['USERPROFILE'] = str(home)
os.environ.setdefault('QT_QPA_PLATFORM', %(platform)r)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtCore import Qt, QTimer
from utils import config as cfg
cfg.Config.CONFIG_DIR = home / '.transcriberpro'
cfg.Config.CONFIG_FILE = cfg.Config.CONFIG_DIR / 'config.json'
cfg.reset_config()
c = cfg.get_config(); c.set('language', 'it', save=False); c.set('ui_scanner_card_open', False, save=False)
app = QApplication([]); app.setStyle('Fusion')
for ttf in (ROOT / 'assets' / 'fonts').glob('*.ttf'):
    QFontDatabase.addApplicationFont(str(ttf))
app.setFont(QFont('Inter Tight', 10))
from gui.theme import build_qss
app.setStyleSheet(build_qss())
from utils.translations import init_language
init_language(c)
from gui.history_widget import HistoryWidget
HistoryWidget.HISTORY_FILE = home / '.transcriberpro' / 'history.json'
(home / '.transcriberpro').mkdir(parents=True, exist_ok=True)
(home / '.transcriberpro' / 'history.json').write_text(json.dumps([
    {'name': 'Film Uno', 'date_iso': '2026-10-27T21:05:09', 'src_lang': 'eng', 'dst_lang': 'ita', 'duration_seconds': 3725, 'size_bytes': 1610612736, 'srt_path': 'C:/v/uno.srt', 'video_path': 'C:/v/uno.mkv'},
    {'name': 'Serie Due S01E02', 'date_iso': '2026-10-28T08:00:00', 'src_lang': 'auto', 'dst_lang': 'ita', 'duration_seconds': 2710, 'size_bytes': 904857600, 'srt_path': 'C:/v/due.srt', 'video_path': 'C:/v/due.mkv'}]), encoding='utf-8')
from gui.main_window import MainWindow
mw = MainWindow()
mw.resize(1400, 900)
mw.show()
def pump(n=6):
    for _ in range(n):
        app.processEvents()
pump()
out = Path(%(out)r); out.mkdir(parents=True, exist_ok=True)

def geometry():
    res = {}
    for w in mw.findChildren(__import__('PyQt6.QtWidgets', fromlist=['QWidget']).QWidget):
        n = w.objectName()
        if n and w.isVisible():
            p = w.mapTo(mw, w.rect().topLeft())
            res[n + '#' + str(len(res))] = [p.x(), p.y(), w.width(), w.height()]
    rows = []
    for i in range(mw.file_list.count()):
        it = mw.file_list.item(i)
        r = mw.file_list.visualItemRect(it)
        p = mw.file_list.viewport().mapTo(mw, r.topLeft())
        rows.append({'hidden': it.isHidden(), 'rect': [p.x(), p.y(), r.width(), r.height()], 'data': it.data(Qt.ItemDataRole.UserRole)})
    return {'widgets': res, 'rows': rows, 'window': [mw.width(), mw.height()]}

def snap(name):
    pump(8)
    img = mw.grab().toImage()
    img.save(str(out / (name + '.png')))
    g = geometry(); g['dpr'] = img.devicePixelRatio(); g['px'] = [img.width(), img.height()]
    (out / (name + '.json')).write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding='utf-8')

def seed_rows():
    paths = ['C:/Video/Film Uno.mkv', 'C:/Video/Serie Due S01E02 - Un episodio con un titolo molto lungo che deve essere accorciato.mkv', 'C:/Video/Documentario.mp4']
    mw.queue_service.enqueue(paths, sizes={paths[0]: '1.5 GB', paths[1]: '862 MB', paths[2]: '2.1 GB'})
    pump()
    from gui.services.job_model import JobRecord
    def setrow(i, status, progress, ov=''):
        it = mw.file_list.item(i); d = dict(it.data(Qt.ItemDataRole.UserRole) or {})
        d['status'] = status; d['progress'] = progress
        if ov: d['ov'] = ov
        it.setData(Qt.ItemDataRole.UserRole, d)
    setrow(0, 'completed', 100); setrow(1, 'processing', 45, 'ENG \u00b7 mux'); setrow(2, 'queued', 0)
    mw._update_filter_badges(); mw.file_list.update(); mw.file_list.clearSelection(); mw.file_list.setCurrentRow(-1)
    pump()

state = %(state)r
if state == 'vuota':
    pass
else:
    seed_rows()
if state.startswith('filtro_'):
    key = {'filtro_attivi': 'processing', 'filtro_coda': 'queued', 'filtro_completati': 'completed'}[state]
    mw.segmented_filter._on_clicked(key) if hasattr(mw.segmented_filter, '_on_clicked') else None
    mw._apply_filter(key)
    for k, b in mw.segmented_filter._btns.items():
        b.setChecked(k == key)
if state == 'pipeline':
    mw.compact_log_enabled = True
    from core.jobs.step_plan import StepTracker, PlanOptions
    t = StepTracker('C:/Video/Serie Due S01E02.mkv', PlanOptions(), clock=lambda: 1000.0)
    t.feed_event('phase', {'name': 'extract'}); t.feed_event('phase', {'name': 'asr', 'engine': 'qwen3'}); t.feed_event('bar', {'phase': 'asr', 'pct': 40})
    mw.on_file_steps('C:/Video/Serie Due S01E02.mkv', t.snapshot())
if state == 'cronologia':
    mw.main_tab_bar.setCurrentIndex(1)
    mw.history_widget.load()
if state.startswith('imp_'):
    from gui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(mw, initial_tab=state[4:])
    dlg.show()
    pump(30)
    img = dlg.grab().toImage()
    img.save(str(out / (state + '.png')))
    from PyQt6.QtWidgets import QWidget
    res = {}
    for w in dlg.findChildren(QWidget):
        n = w.objectName()
        if n and w.isVisible():
            p = w.mapTo(dlg, w.rect().topLeft())
            res[n + '#' + str(len(res))] = [p.x(), p.y(), w.width(), w.height()]
    (out / (state + '.json')).write_text(json.dumps({'widgets': res, 'rows': [], 'window': [dlg.width(), dlg.height()], 'dpr': img.devicePixelRatio()}, indent=1), encoding='utf-8')
else:
    snap(state)
'''


def run_state(scale, state, out, platform, home):
    code = CHILD % {'root': str(ROOT), 'home': str(home), 'platform': platform, 'out': str(out), 'state': state}
    env = dict(os.environ, QT_SCALE_FACTOR=str(scale), QT_ENABLE_HIGHDPI_SCALING='1')
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, cwd=str(ROOT))
    return r.returncode, (r.stderr or '')[-1500:]          # su Windows il default (cp1252) rompe la lettura dell'uscita: UTF-8 esplicito


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(Path(__file__).resolve().parent / 'results' / ('p2_qt_' + ('windows' if sys.platform == 'win32' else 'linux'))))
    ap.add_argument('--scales', nargs='+', type=float, default=[1.0, 1.25, 1.5])
    ap.add_argument('--platform', default='windows' if sys.platform == 'win32' else 'offscreen')
    ap.add_argument('--states', nargs='+', default=STATES + SETTINGS_STATES)
    a = ap.parse_args()
    report = {}
    for s in a.scales:
        d = Path(a.out) / str(s)
        for st in a.states:
            home = Path(tempfile.mkdtemp(prefix='tp_p2_home_'))
            rc, err = run_state(s, st, d, a.platform, home)
            report[f'{s}/{st}'] = 'ok' if rc == 0 else err
            print(f'{s} {st}: ' + ('ok' if rc == 0 else 'ERRORE ' + err[-300:]), flush=True)
    (Path(a.out) / 'report.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
