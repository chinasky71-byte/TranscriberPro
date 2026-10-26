# -*- coding: utf-8 -*-
"""Finto `core.pipeline_cli` per i test di caratterizzazione della coda (nessun modello, nessuna GPU).

Lo lancia al suo posto il test (vedi _queue_testkit.py): `python queue_stub_pipeline.py <args.json>`. Legge lo stesso
args.json del vero pipeline_cli e scrive lo stesso result.json. Lo scenario dipende da parole nel NOME del video:
  (nessuna)  ok: eventi di fase e di barra, righe di testo, rumore, una riga su stderr; result success=True
  fail       come ok ma success=False ed exit code 1
  crash      exit code 3 senza result.json
  slow       stampa STUB_SLOW_STARTED e poi attende 60 s (si ferma solo con Stop / kill dell'albero)
  conv       crea <video>.converting e si comporta come slow (residuo da ripulire)
  resid      come ok ma lascia <video>.converting accanto al video
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils.events import format_line  # noqa: E402


def out(line):
    sys.stdout.write(line + '\n')
    sys.stdout.flush()


def ev(kind, **fields):
    if os.environ.get('TP_EVENTS') == '1':
        out(format_line(kind, fields))


def main():
    args = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    video = args['video_path']
    name = Path(video).name.lower()
    out('STUB_ARGS ' + json.dumps({k: args[k] for k in ('target_language', 'overrides', 'files_processed') if k in args},
                                  sort_keys=True))
    out('STUB_ENV ' + json.dumps({k: os.environ.get(k) for k in ('TP_SUBPROCESS', 'TQDM_DISABLE', 'TP_EVENTS',
                                                                'PYTHONIOENCODING', 'PYTHONUTF8')}, sort_keys=True))
    ev('phase', name='setup')
    out('STUB riga di testo uno')
    out('Downloading: modello.bin')
    out('Using cache found in /tmp/x')
    out('[DIAG-RAM] 1. Passo finto (non e\' un confine di passo)')
    sys.stderr.write('STUB_STDERR rumore di libreria\n')
    sys.stderr.flush()
    if 'conv' in name or 'resid' in name:
        Path(video + '.converting').write_text('residuo', encoding='utf-8')
    if 'slow' in name or 'conv' in name:
        out('STUB_SLOW_STARTED')
        time.sleep(60)
        return 0
    ev('phase', name='extract')
    ev('phase', name='asr', engine='qwen3')
    out('[DIAG-RAM] Trascrizione: [#####-----] 90%')     # se la barra la leggesse salterebbe avanti: va solo nel log
    ev('bar', phase='asr', pct=50)
    out('STUB riga di testo due')
    ev('bar', phase='asr', pct=100)
    ev('phase', name='final', fraction=0.5)
    if 'crash' in name:
        return 3
    ok = 'fail' not in name
    Path(args['result_path']).write_text(json.dumps(
        {'success': ok, 'last_output_path': video + '.it.srt' if ok else ''}), encoding='utf-8')
    out('STUB fine')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
