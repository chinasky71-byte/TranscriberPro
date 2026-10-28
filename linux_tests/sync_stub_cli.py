# -*- coding: utf-8 -*-
"""Finto `core.sync_cli` per i test di caratterizzazione della coda di sincronizzazione (nessun modello, nessuna GPU).

Lo lancia al suo posto il test (`SyncBatchWorker.CLI_MODULE = 'linux_tests.sync_stub_cli'`): legge lo stesso args.json del vero
sync_cli e scrive lo stesso result.json. Lo scenario dipende da parole nel NOME del video:
  (nessuna)  ok: righe di passo ("1. ..."), [SYNC-PCT], testo, riga su stderr; success=True con output_path
  fail       success=False con error "boom", exit code 1
  failnomsg  success=False senza motivo, exit code 1 (nessun result.json)
  crash      exit code 3 senza result.json
  badpct     riga [SYNC-PCT] non numerica, poi ok
  late       [SYNC-PCT] 90 e poi una riga di passo "2. ..." (la barra non deve tornare indietro)
  rc0fail    exit code 0 ma result.json con success=False ed error "x"
  rc1ok      exit code 1 ma result.json con success=True e output_path
  both       success=True con output_path "O" ed error "E" (vince l'output)
  slow       stampa STUB_SLOW_STARTED e poi attende 60 s (si ferma solo con cancel / kill dell'albero)
"""
import json
import os
import sys
import time
from pathlib import Path


def out(line):
    sys.stdout.write(line + '\n')
    sys.stdout.flush()


def main():
    args = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    video = args['video_path']
    name = Path(video).name.lower()
    result_path = args.get('result_path')
    out('STUB_ARGS ' + json.dumps({k: args[k] for k in ('video_path', 'external_srt_path', 'output_path')}, sort_keys=True))
    out('STUB_ENV ' + json.dumps({k: os.environ.get(k) for k in ('TP_SUBPROCESS', 'TQDM_DISABLE', 'PYTHONIOENCODING',
                                                                'PYTHONUTF8')}, sort_keys=True))
    out('\n1. Estrazione audio')
    out('[SYNC-PCT] 30')
    out('[SYNC-PCT] 20')                      # non fa retrocedere la barra
    out('testo con 3. numero nel mezzo')
    sys.stderr.write('STUB_STDERR rumore\n')
    sys.stderr.flush()
    if 'badpct' in name:
        out('[SYNC-PCT] xx')
    if 'slow' in name:
        out('STUB_SLOW_STARTED')
        time.sleep(60)
        return 0
    if 'late' in name:
        out('[SYNC-PCT] 90')
        out('2. Passo tardivo')
    result_ok = {'success': True, 'output_path': args['output_path'] or video + '.synced.it.srt', 'error': None}
    if 'rc0fail' in name:
        Path(result_path).write_text(json.dumps({'success': False, 'output_path': None, 'error': 'x'}), encoding='utf-8')
        return 0
    if 'rc1ok' in name:
        Path(result_path).write_text(json.dumps(result_ok), encoding='utf-8')
        return 1
    if 'both' in name:
        Path(result_path).write_text(json.dumps({'success': True, 'output_path': 'O', 'error': 'E'}), encoding='utf-8')
        return 0
    if 'crash' in name:
        return 3
    if 'failnomsg' in name:
        return 1
    if 'fail' in name:
        Path(result_path).write_text(json.dumps({'success': False, 'output_path': None, 'error': 'boom'}), encoding='utf-8')
        return 1
    out('3. Allineamento')
    out('[SYNC-PCT] 90')
    Path(result_path).write_text(json.dumps({'success': True, 'output_path': args['output_path'] or video + '.synced.it.srt',
                                             'error': None}), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
