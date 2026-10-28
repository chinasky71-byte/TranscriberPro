"""Regola di Franz (v1.34.30): importare `utils` o i moduli GGUF a livello di modulo NON deve caricare PyQt6, torch,
onnxruntime. Su Windows PyQt6 prima di onnxruntime rompe `import onnxruntime`; llama_cpp deve essere il primo import
nei processi che lo usano."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HEAVY = ('PyQt6', 'torch', 'onnxruntime', 'llama_cpp')


@pytest.mark.parametrize('modules', [
    ['utils', 'utils.translations', 'utils.config', 'utils.gguf_quant'],
    ['core.llm_subtitle_translator.gguf_subprocess', 'core.llm_subtitle_translator.gguf_engine'],
])
def test_import_non_carica_moduli_pesanti(modules):
    code = ("import sys\n" + "".join(f"import {m}\n" for m in modules) +
            f"bad=[h for h in {HEAVY!r} if h in sys.modules]\nprint('BAD', bad)\n")
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.strip().splitlines()[-1] == 'BAD []'
