# -*- coding: utf-8 -*-
"""core/diar_progress.py: dai passi di pyannote a una frazione 0..1 monotona (modulo puro: nessun torch/PyQt6/onnxruntime)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.diar_progress import DISCRETE, EMB_END, SEG_END, DiarProgress  # noqa: E402


def _collect():
    got = []
    return got, DiarProgress(got.append)


def test_la_sequenza_di_pyannote_da_una_frazione_monotona_fino_a_uno():
    got, hook = _collect()
    for c in range(0, 101, 10):                                   # segmentazione a passi
        hook('segmentation', None, total=100, completed=c)
    hook('segmentation', object())                                # chiamata finale senza conteggi
    hook('speaker_counting', object())
    hook('embeddings', None, total=10, completed=0)
    for c in range(1, 11):
        hook('embeddings', None, total=10, completed=c)
    hook('embeddings', object())
    hook('discrete_diarization', object())
    hook.finish()
    assert got == sorted(set(got)) and got[0] == 0.0 and got[-1] == 1.0
    assert abs(SEG_END - 0.04) < 1e-9 and EMB_END == 0.94 and DISCRETE == 0.97
    assert SEG_END in got and EMB_END in got and DISCRETE in got


def test_il_peso_delle_impronte_vocali_e_la_maggior_parte_della_barra():
    got, hook = _collect()
    hook('segmentation', object())
    hook('embeddings', None, total=100, completed=50)
    assert abs(got[-1] - (SEG_END + (EMB_END - SEG_END) * 0.5)) < 1e-9          # a meta' delle impronte: ~49%


def test_mai_all_indietro_e_valori_fuori_scala_si_limitano():
    got, hook = _collect()
    hook('embeddings', None, total=10, completed=8)
    hook('embeddings', None, total=10, completed=3)               # arretrato: ignorato
    hook('embeddings', None, total=10, completed=99)              # oltre il totale: limitato
    hook('embeddings', None, total=0, completed=0)                # totale 0: passo concluso
    assert got == sorted(got) and max(got) <= 1.0


def test_un_errore_nel_callback_non_rompe_la_diarizzazione():
    def boom(_):
        raise RuntimeError('vista chiusa')
    hook = DiarProgress(boom)
    hook('segmentation', None, total=2, completed=1)              # non deve sollevare
    hook.finish()


def test_il_modulo_non_importa_librerie_pesanti():
    code = ("import sys\nimport core.diar_progress\n"
            "bad = [m for m in ('torch', 'PyQt6', 'onnxruntime', 'pyannote') if m in sys.modules]\n"
            "assert not bad, bad\nprint('OK')\n")
    p = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=str(ROOT))
    assert p.returncode == 0 and 'OK' in p.stdout, (p.stdout + p.stderr)[-400:]


def test_argomenti_nuovi_dell_hook_sono_ignorati():
    got, hook = _collect()
    hook('embeddings', None, total=4, completed=2, nome_nuovo=1, altro='x')       # firma di una versione futura di pyannote
    assert got and got[-1] > SEG_END
