# -*- coding: utf-8 -*-
"""Attrezzi comuni ai test di caratterizzazione della coda (GUI: gui/workers.py; headless: core/queue_runner.py)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB = Path(__file__).resolve().parent / 'queue_stub_pipeline.py'
_REAL_POPEN = subprocess.Popen


class PopenSpy:
    """Sostituisce subprocess.Popen: registra ogni chiamata di `core.pipeline_cli` e al suo posto lancia il finto."""

    def __init__(self):
        self.calls = []        # {'argv': [...], 'kwargs': {...}, 'args_json': dict}
        self.procs = []

    def __call__(self, argv, *a, **kw):
        argv = list(argv)
        if argv[1:3] == ['-m', 'core.pipeline_cli']:
            args_path = Path(argv[3])
            import json
            self.calls.append({'argv': argv, 'kwargs': dict(kw),
                               'args_json': json.loads(args_path.read_text(encoding='utf-8'))})
            argv = [sys.executable, str(STUB), argv[3]]
            proc = _REAL_POPEN(argv, *a, **kw)
            self.procs.append(proc)
            return proc
        return _REAL_POPEN(argv, *a, **kw)


def make_videos(tmp_path, *names):
    out = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b'x' * 10)
        out.append(str(p))
    return out
