# -*- coding: utf-8 -*-
"""core.vram_settle: attesa che la VRAM liberata dagli ASR sia stabile (senza GPU: letture e orologio finti)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.vram_settle import wait_vram_settled  # noqa: E402

GIB = 1024 ** 3


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _run(reads, **kw):
    it = iter(reads)
    last = [reads[-1]]

    def read():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]
    c = Clock()
    return wait_vram_settled(read, sleep=c.sleep, clock=c.now, **kw), c


def test_no_gpu_returns_immediately():
    c = Clock()
    assert wait_vram_settled(lambda: None, sleep=c.sleep, clock=c.now) == (None, None, True)
    assert c.t == 0


def test_read_error_is_no_gpu():
    def boom():
        raise RuntimeError('x')
    assert wait_vram_settled(boom) == (None, None, True)


def test_waits_for_the_driver_to_return_pages():
    # WDDM: la memoria di Whisper torna libera a scalini nell'arco di qualche secondo
    reads = [2 * GIB, 4 * GIB, 6 * GIB, 8 * GIB, 8 * GIB, 8 * GIB, 8 * GIB]
    (first, last, settled), c = _run(reads)
    assert (first, last, settled) == (2 * GIB, 8 * GIB, True)
    assert c.t >= 1.0     # ha aspettato: non e' rientrata alla prima lettura


def test_already_stable_costs_three_polls():
    (first, last, settled), c = _run([8 * GIB] * 5)
    assert settled and c.t == 3 * 0.25


def test_timeout_returns_last_reading_unsettled():
    reads = [i * GIB for i in range(1, 100)]    # cresce sempre
    (first, last, settled), c = _run(reads, timeout_s=2.0)
    assert not settled and first == GIB and last > first and c.t <= 2.25


def test_cancel_returns_at_once():
    (first, last, settled), c = _run([GIB, 2 * GIB, 3 * GIB], cancelled=lambda: True)
    assert not settled and c.t == 0


def test_module_does_not_import_heavy_deps():
    code = ("import sys; import core.vram_settle; "
            "bad=[m for m in ('torch','PyQt6','onnxruntime') if m in sys.modules]; assert not bad, bad")
    subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True)
