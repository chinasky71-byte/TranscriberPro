# -*- coding: utf-8 -*-
"""P1(a-bis) su WINDOWS: guscio di RISERVA con Qt WebEngine (da usare SOLO se pywebview non restituisce i percorsi dei file).

Un QWebEngineView mostra la stessa pagina; il trascinamento si intercetta a livello Qt (le URL dei file arrivano dal sistema,
con percorsi assoluti) e si consegna alla pagina; i dialoghi nativi sono QFileDialog. Scrive results/p1_qtwebengine_<sistema>.json.
Richiede (in un venv usa e getta):  pip install PyQt6==6.10.2 PyQt6-WebEngine==6.10.0
NOTA: porta con se' i vincoli di importazione di PyQt6 (onnxruntime prima, ecc.): vale solo nel guscio, mai nel server.
"""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PyQt6.QtCore import QEvent, QObject, QTimer, QUrl  # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow  # noqa: E402
import psutil  # noqa: E402
from tpweb.proto.p1_server import ServerThread  # noqa: E402

RESULTS = Path(__file__).resolve().parent / 'results'


class DropFilter(QObject):
    def __init__(self, view, res):
        super().__init__(view)
        self.view, self.res = view, res

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if ev.mimeData().hasUrls():
                ev.acceptProposedAction()
                return True
        elif t == QEvent.Type.Drop and ev.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
            self.res['qt_drops'].append(paths)
            self.view.page().runJavaScript(
                f"R.drops.push({{n:{len(paths)},files:{json.dumps([{'name': Path(p).name, 'fullPath': p} for p in paths])},types:['qt']}});show();")
            ev.acceptProposedAction()
            return True
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--wait', type=int, default=90)
    ap.add_argument('--auto', action='store_true')
    a = ap.parse_args()
    srv = ServerThread().start()
    res = {'system': f'{platform.system()} {platform.release()}', 'qt_drops': [], 'dialogs': [], 'passi_umani': not a.auto}
    app = QApplication([])
    win = QMainWindow()
    view = QWebEngineView()
    win.setCentralWidget(view)
    win.resize(1000, 820)
    view.load(QUrl(srv.url))
    win.show()
    flt = DropFilter(view, res)
    QTimer.singleShot(1500, lambda: [w.installEventFilter(flt) for w in (view.focusProxy(), view) if w is not None])

    def finish():
        me = psutil.Process()
        procs = [me] + me.children(recursive=True)
        res['memoria'] = {'totale_mb': round(sum(p.memory_info().rss for p in procs if p.is_running()) / 1048576, 1),
                          'processi': sorted({p.name() for p in procs})}
        RESULTS.mkdir(exist_ok=True)
        out = RESULTS / f'p1_qtwebengine_{platform.system().lower()}.json'
        out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(res, indent=2, ensure_ascii=False), '\nscritto', out, flush=True)
        app.quit()

    if not a.auto:
        print(f'>>> Trascina 2-3 file video dalla Esplora risorse sulla finestra (attendo {a.wait} s).', flush=True)
        QTimer.singleShot(a.wait * 1000, finish)
        t0 = time.time()
        poll = QTimer()
        poll.timeout.connect(lambda: finish() if res['qt_drops'] and time.time() - t0 > 3 else None)
        poll.start(1000)
    else:
        QTimer.singleShot(4000, finish)
    app.exec()
    srv.stop()


if __name__ == '__main__':
    main()
