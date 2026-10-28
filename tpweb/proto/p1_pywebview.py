# -*- coding: utf-8 -*-
"""P1(a)+(d) su WINDOWS: guscio pywebview (WebView2) attorno alla pagina del prototipo.

Cosa verifica (tutto scritto in results/p1_pywebview_<sistema>.json):
  1. TRASCINAMENTO: trascinando file da Esplora risorse sulla finestra, si ottengono i PERCORSI ASSOLUTI? (lato Python tramite
     l'evento DOM `drop` di pywebview 5.x -> `pywebviewFullPath`, e lato pagina JS).
  2. DIALOGHI NATIVI: apertura di file multipli e di cartella tramite il ponte `window.pywebview.api`.
  3. FLUSSO DI EVENTI dentro WebView2: stesso banco di p1_bench_sse.py, ma nella finestra vera.
  4. MEMORIA: RSS totale dell'albero di processi (python + msedgewebview2) a riposo e dopo il banco.
Passi umani: se si lancia senza --auto, il programma ti chiede di trascinare 2-3 file e di premere i due pulsanti dei dialoghi.

Uso (in un venv usa e getta, NON in quello di produzione):  python p1_pywebview.py [--auto] [--wait 90]
"""
import argparse
import json
import platform
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import psutil  # noqa: E402
import webview  # noqa: E402
from tpweb.proto.p1_server import ServerThread  # noqa: E402

RESULTS = Path(__file__).resolve().parent / 'results'


def _dialog_const(kind: str):
    fd = getattr(webview, 'FileDialog', None)           # pywebview >= 5.? ; le costanti vecchie sono deprecate
    if fd is not None:
        return getattr(fd, kind)
    return {'OPEN': webview.OPEN_DIALOG, 'FOLDER': webview.FOLDER_DIALOG}[kind]


class Api:
    window = None

    def pick_files(self):
        r = self.window.create_file_dialog(_dialog_const('OPEN'), allow_multiple=True,
                                           file_types=('Video (*.mkv;*.mp4;*.avi;*.mov)', 'Tutti i file (*.*)'))
        return [str(x) for x in (r or [])]

    def pick_folder(self):
        r = self.window.create_file_dialog(_dialog_const('FOLDER'))
        return [str(x) for x in (r or [])]


def tree_rss_mb() -> dict:
    me = psutil.Process()
    procs = [me] + me.children(recursive=True)
    tot, names = 0, {}
    for p in procs:
        try:
            rss = p.memory_info().rss
        except psutil.Error:
            continue
        tot += rss
        names[p.name()] = round(names.get(p.name(), 0) + rss / 1048576, 1)
    return {'totale_mb': round(tot / 1048576, 1), 'per_processo_mb': names, 'n_processi': len(procs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--auto', action='store_true', help='senza passi umani (solo banco e memoria)')
    ap.add_argument('--wait', type=int, default=90, help='secondi di attesa per i passi umani')
    ap.add_argument('--burst', type=int, default=5000)
    ap.add_argument('--seconds', type=float, default=10.0)
    a = ap.parse_args()

    srv = ServerThread().start()
    api = Api()
    res = {'system': f'{platform.system()} {platform.release()} / Python {platform.python_version()}',
           'pywebview': getattr(webview, '__version__', '?'), 'python_drops': [], 'passi_umani': not a.auto}
    window = webview.create_window('P1 prototipo – Transcriber Pro', srv.url, js_api=api, width=1000, height=820)
    api.window = window

    def on_drop(e):
        try:
            files = e['dataTransfer']['files']
            res['python_drops'].append([{'name': f.get('name'), 'fullPath': f.get('pywebviewFullPath'), 'size': f.get('size')}
                                        for f in files])
        except Exception as exc:                       # noqa: BLE001
            res['python_drops'].append({'errore': repr(exc)})

    def checks():
        try:
            try:
                from webview.dom import DOMEventHandler
                window.dom.document.events.drop += DOMEventHandler(on_drop, False, False)
                res['drop_handler'] = 'registrato'
            except Exception as exc:                   # noqa: BLE001
                res['drop_handler'] = f'NON disponibile: {exc!r}'
            time.sleep(2)
            res['memoria_a_riposo'] = tree_rss_mb()
            if not a.auto:
                print('\n>>> Ora: 1) trascina 2-3 file video da Esplora risorse sulla finestra;'
                      ' 2) premi "Scegli file" e scegli 2 file; 3) premi "Scegli cartella" e scegline una.\n'
                      f'    Attendo fino a {a.wait} s (si chiude da solo appena hai fatto le tre cose).', flush=True)
                t0 = time.time()
                while time.time() - t0 < a.wait:
                    time.sleep(1)
                    try:
                        st = json.loads(window.evaluate_js('JSON.stringify({d: R.drops.length, k: R.dialogs.length})'))
                    except Exception:                  # noqa: BLE001
                        continue
                    if st['d'] >= 1 and st['k'] >= 2:
                        break
            window.evaluate_js("fetch('/api/bench/start',{method:'POST',headers:{'Content-Type':'application/json'},"
                               f"body:JSON.stringify({{burst:{a.burst},rate:10,seconds:{a.seconds}}})}})")
            t0 = time.time()
            r = None
            while time.time() - t0 < a.seconds + 60 and not r:
                time.sleep(0.5)
                r = window.evaluate_js('JSON.stringify(window.__result)')
                r = json.loads(r) if r and r != 'null' else None
            res['banco_sse'] = r
            res['memoria_dopo_banco'] = tree_rss_mb()
            res['pagina'] = json.loads(window.evaluate_js('JSON.stringify({drops: R.drops, dialogs: R.dialogs})'))
        except Exception as exc:                       # noqa: BLE001
            res['errore'] = repr(exc)
        finally:
            RESULTS.mkdir(exist_ok=True)
            out = RESULTS / f'p1_pywebview_{platform.system().lower()}.json'
            out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding='utf-8')
            print(json.dumps(res, indent=2, ensure_ascii=False))
            print('scritto', out, flush=True)
            window.destroy()

    webview.start(checks)
    srv.stop()


if __name__ == '__main__':
    main()
