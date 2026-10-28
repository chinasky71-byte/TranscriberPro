# -*- coding: utf-8 -*-
"""P1(d): memoria della GUI Qt ATTUALE a riposo (per confrontarla con la finestra del prototipo).

Uso:   python p1_qt_baseline_mem.py <python.exe del venv di produzione> <cartella del progetto di prova> [--idle 30]
Lancia main.py, aspetta --idle secondi, misura l'RSS dell'albero di processi, chiude. Scrive results/p1_qt_baseline_<sistema>.json.
NON modifica nulla: va lanciato su una COPIA di prova del progetto, con una HOME qualsiasi (usa la configurazione dell'utente)."""
import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import psutil

RESULTS = Path(__file__).resolve().parent / 'results'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('python')
    ap.add_argument('project')
    ap.add_argument('--idle', type=int, default=30)
    a = ap.parse_args()
    p = subprocess.Popen([a.python, 'main.py'], cwd=a.project)
    try:
        time.sleep(a.idle)
        root = psutil.Process(p.pid)
        procs = [root] + root.children(recursive=True)
        names, tot = {}, 0
        for q in procs:
            try:
                rss = q.memory_info().rss
            except psutil.Error:
                continue
            tot += rss
            names[q.name()] = round(names.get(q.name(), 0) + rss / 1048576, 1)
        res = {'system': f'{platform.system()} {platform.release()}', 'idle_s': a.idle,
               'totale_mb': round(tot / 1048576, 1), 'per_processo_mb': names}
    finally:
        for q in psutil.Process(p.pid).children(recursive=True) if p.poll() is None else []:
            try:
                q.kill()
            except psutil.Error:
                pass
        p.kill()
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f'p1_qt_baseline_{platform.system().lower()}.json'
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
