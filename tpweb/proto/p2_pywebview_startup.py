# -*- coding: utf-8 -*-
"""P2(a): perche' la prima esecuzione automatica di pywebview si e' bloccata oltre 4 minuti? Misura l'avvio ripetuto.

Lancia N volte (ognuna in un processo nuovo, con un limite di tempo) una finestra pywebview che carica la pagina del prototipo,
e registra le tappe raggiunte: processo avviato, finestra creata, evento `loaded`, primo ritorno di evaluate_js. Se un avvio non
finisce entro il limite, registra a che tappa si era fermato e quali processi (python, msedgewebview2) c'erano, poi lo uccide.
Uso (WINDOWS, venv usa e getta):  python p2_pywebview_startup.py [--runs 10] [--timeout 45] [--pausa 2]
Per il caso «avvio a freddo»: lancialo una volta appena acceso il PC o dopo almeno 10 minuti senza WebView2 aperti (--runs 1).
Scrive results/p2_startup_<sistema>.json.
"""
import argparse
import json
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RESULTS = Path(__file__).resolve().parent / 'results'


def child():
    import webview
    from tpweb.proto.p1_server import ServerThread
    t0 = time.time()

    def say(stage, **kw):
        print(json.dumps({'stage': stage, 't': round(time.time() - t0, 3), **kw}), flush=True)
    say('processo')
    srv = ServerThread().start()
    say('server')
    window = webview.create_window('P2 avvio', srv.url, width=700, height=500)
    say('finestra_creata')
    loaded = threading.Event()
    window.events.loaded += lambda: (say('loaded'), loaded.set())

    def func():
        say('gui_avviata')
        if not loaded.wait(60):
            say('loaded_NON_arrivato')
            return
        r = window.evaluate_js('1+1')
        say('evaluate_js', risultato=r)
        window.destroy()
    webview.start(func)
    srv.stop()
    say('fine')


def parent(runs, timeout, pause):
    import psutil
    out = {'system': f'{platform.system()} {platform.release()}', 'runs': []}
    for i in range(runs):
        t0 = time.time()
        p = subprocess.Popen([sys.executable, __file__, '--child'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines, done = [], threading.Event()

        def reader():
            for ln in p.stdout:
                lines.append(ln.strip())
            done.set()
        threading.Thread(target=reader, daemon=True).start()
        done.wait(timeout)
        rec = {'n': i + 1, 'durata_s': round(time.time() - t0, 2)}
        stages = []
        for ln in lines:
            try:
                stages.append(json.loads(ln))
            except ValueError:
                rec.setdefault('altro', []).append(ln[:200])
        rec['tappe'] = stages
        if not done.is_set():
            rec['esito'] = 'BLOCCATO'
            try:
                root = psutil.Process(p.pid)
                rec['processi'] = sorted({q.name() for q in [root] + root.children(recursive=True)})
                for q in root.children(recursive=True) + [root]:
                    try:
                        q.kill()
                    except psutil.Error:
                        pass
            except psutil.Error:
                pass
        else:
            rec['esito'] = 'OK' if any(s.get('stage') == 'evaluate_js' for s in stages) else 'FINITO_SENZA_evaluate_js'
        out['runs'].append(rec)
        print(f"{i + 1}/{runs}: {rec['esito']} in {rec['durata_s']} s", flush=True)
        time.sleep(pause)
    ok = [r for r in out['runs'] if r['esito'] == 'OK']
    out['riassunto'] = {'ok': len(ok), 'bloccati': sum(r['esito'] == 'BLOCCATO' for r in out['runs']),
                        'durata_max_ok_s': max((r['durata_s'] for r in ok), default=None),
                        'durata_media_ok_s': round(sum(r['durata_s'] for r in ok) / len(ok), 2) if ok else None}
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f'p2_startup_{platform.system().lower()}.json'
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(out['riassunto']), '\nscritto', path)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--child', action='store_true')
    ap.add_argument('--runs', type=int, default=10)
    ap.add_argument('--timeout', type=int, default=45)
    ap.add_argument('--pausa', type=float, default=2.0)
    a = ap.parse_args()
    child() if a.child else parent(a.runs, a.timeout, a.pausa)
