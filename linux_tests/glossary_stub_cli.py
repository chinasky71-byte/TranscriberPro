# -*- coding: utf-8 -*-
"""Finto `core/glossary_builder_cli.py` per i test di caratterizzazione del worker del glossario (nessun venv, nessun modello).

`python glossary_stub_cli.py <args.json>`: stampa righe JSON come il vero CLI. Lo scenario dipende dal campo `name` dell'args.json:
  ok       gate, progress, log, riga non-JSON, riga vuota, done con report
  err      evento error ed exit code 1
  nodone   exit code 0 senza evento done
  rc1done  done con report ma exit code 1
  err2     evento error senza msg
  crash    exit code 3 senza eventi
  slow     stampa un log "STUB_SLOW_STARTED" e poi attende 60 s (si ferma solo con cancel)
"""
import json
import sys
import time
from pathlib import Path


def ev(**kw):
    sys.stdout.write(json.dumps(kw, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    args = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    name = args['name']
    sys.stderr.write('STUB_STDERR rumore\n')
    sys.stderr.flush()
    if name.startswith('crash'):
        return 3
    ev(ev='log', msg='avvio ' + name)
    import os
    ev(ev='log', msg='STUB_ENV ' + json.dumps({k: os.environ.get(k) for k in ('PYTHONUTF8', 'PYTHONIOENCODING')}, sort_keys=True))
    ev(ev='log', msg='STUB_CWD ' + os.getcwd())
    ev(ev='log', msg='STUB_RAW ' + Path(sys.argv[1]).read_text(encoding='utf-8'))
    if name.startswith('slow'):
        ev(ev='log', msg='STUB_SLOW_STARTED')
        time.sleep(60)
        return 0
    ev(ev='gate', ok=True, blocks=7000, need_blocks=6000)
    ev(ev='progress', phase='align', done=1, total=4, msg='uno')
    ev(ev='progress')
    sys.stdout.write('questa non e json\n\n')
    sys.stdout.flush()
    if name.startswith('err2'):
        ev(ev='error')
        return 1
    if name.startswith('rc1done'):
        ev(ev='done', report=str(Path(sys.argv[1]).parent / 'report.json'))
        return 1
    if name.startswith('err'):
        ev(ev='error', msg='qualcosa e andato storto')
        return 1
    if name.startswith('nodone'):
        return 0
    ev(ev='log', msg='fine')
    ev(ev='done', report=str(Path(sys.argv[1]).parent / 'report.json'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
