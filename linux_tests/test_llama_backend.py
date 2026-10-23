# -*- coding: utf-8 -*-
"""F5: marcatore venv/llama_backend.txt (utils.llm_model_select) e ripiego VRAM libera del canale GPU del glossario."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from utils import gpu_detect as gd  # noqa: E402
from utils import llm_model_select as sel  # noqa: E402

NVIDIA = gd.GpuInfo(vendor='nvidia', name='RTX 3060', vram_mib=12288, vram_free_mib=11000, backends=['cuda', 'vulkan'])
AMD = gd.GpuInfo(vendor='amd', name='RX 7800 XT', vram_mib=16368, vram_free_mib=15000, backends=['rocm', 'vulkan'])
INTEL_ONLY_ROCM = gd.GpuInfo(vendor='amd', name='x', vram_mib=8000, backends=['rocm'])


def _patch(monkeypatch, gpus):
    monkeypatch.setattr(gd, 'detect_gpus', lambda *a, **k: gd.GpuReport(gpus=list(gpus)))


def _marker(tmp_path, text):
    p = tmp_path / 'llama_backend.txt'
    if text is not None:
        p.write_text(text, encoding='utf-8')
    return p


@pytest.mark.parametrize('text,exp', [(None, 'cuda'), ('cuda', 'cuda'), ('cpu', 'cuda'), ('vulkan', 'vulkan'),
                                      ('  Vulkan \r\n', 'vulkan'), ('vulkan\n', 'vulkan'), ('', 'cuda'),
                                      ('rocm', 'cuda'), ('vulkan-extra', 'cuda'), ('\x00\xff garbage', 'cuda')])
def test_marker_solo_vulkan_cambia(tmp_path, text, exp):
    assert sel.llama_backend_marker(_marker(tmp_path, text)) == exp


def test_marker_illeggibile_e_cartella(tmp_path):
    assert sel.llama_backend_marker(tmp_path) == 'cuda'          # e' una cartella: errore di lettura -> default


def test_percorso_marker_dentro_il_venv_principale():
    assert sel.LLAMA_BACKEND_MARKER == ROOT / 'venv' / 'llama_backend.txt'


@pytest.mark.parametrize('text', [None, 'cuda', 'cpu', 'garbage'])
def test_nvidia_valore_identico_a_oggi(monkeypatch, tmp_path, text):
    _patch(monkeypatch, [NVIDIA])
    assert sel.detect_vram_mib(_marker(tmp_path, text)) == 12288


@pytest.mark.parametrize('text', [None, 'cuda', 'cpu'])
def test_amd_senza_marker_vulkan_non_conta(monkeypatch, tmp_path, text):
    _patch(monkeypatch, [AMD])
    assert sel.detect_vram_mib(_marker(tmp_path, text)) is None


def test_amd_con_marker_vulkan_conta(monkeypatch, tmp_path):
    _patch(monkeypatch, [AMD])
    assert sel.detect_vram_mib(_marker(tmp_path, 'vulkan')) == 16368


def test_vulkan_ignora_gpu_senza_vulkan_e_prende_la_piu_grande(monkeypatch, tmp_path):
    _patch(monkeypatch, [NVIDIA, AMD, INTEL_ONLY_ROCM])
    assert sel.detect_vram_mib(_marker(tmp_path, 'vulkan')) == 16368
    assert sel.detect_vram_mib(_marker(tmp_path, 'cuda')) == 12288


def test_vulkan_senza_gpu_o_solo_software_e_none(monkeypatch, tmp_path):
    _patch(monkeypatch, [])
    assert sel.detect_vram_mib(_marker(tmp_path, 'vulkan')) is None


def test_errore_di_rilevamento_e_none(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError('x')
    monkeypatch.setattr(gd, 'detect_gpus', boom)
    assert sel.detect_vram_mib(_marker(tmp_path, 'vulkan')) is None


def test_vulkan_sceglie_il_modello_con_la_vram_della_gpu(monkeypatch, tmp_path):
    _patch(monkeypatch, [AMD])
    d = tmp_path / 'models'
    d.mkdir()
    for i in range(1, 3):
        (d / f'qwen2.5-7b-instruct-q4_k_m-{i:05d}-of-00002.gguf').write_bytes(b'x')
    p, ngl = sel.pick_qwen_model(d, sel.detect_vram_mib(_marker(tmp_path, 'vulkan')))
    assert '7b' in p and ngl == -1


# ---- canale GPU del glossario: ripiego sulla VRAM libera di gpu_detect

def _load_cli():
    spec = importlib.util.spec_from_file_location('tp_gq_cli', ROOT / 'glossary_engine' / 'glossary_qwen_gpu_cli.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_nvidia_smi_resta_la_prima_fonte(monkeypatch):
    cli = _load_cli()
    monkeypatch.setattr(cli.subprocess, 'check_output', lambda *a, **k: '11000\n9000\n')
    monkeypatch.setattr(cli, '_free_vram_from_gpu_detect', lambda: pytest.fail('non va chiamato'))
    assert cli._free_vram_mb() == 11000


def test_cli_senza_nvidia_smi_usa_gpu_detect(monkeypatch):
    cli = _load_cli()

    def no_smi(*a, **k):
        raise FileNotFoundError('nvidia-smi')
    monkeypatch.setattr(cli.subprocess, 'check_output', no_smi)
    monkeypatch.setattr(cli, '_free_vram_from_gpu_detect', lambda: 15000)
    assert cli._free_vram_mb() == 15000


def test_cli_nessuna_fonte_e_none(monkeypatch):
    cli = _load_cli()

    def boom(*a, **k):
        raise OSError('x')
    monkeypatch.setattr(cli.subprocess, 'check_output', boom)
    monkeypatch.setattr(cli, '_free_vram_from_gpu_detect', boom)
    assert cli._free_vram_mb() is None


def test_cli_gpu_detect_caricato_da_file_senza_gpu():
    cli = _load_cli()
    assert cli._free_vram_from_gpu_detect() is None or isinstance(cli._free_vram_from_gpu_detect(), int)
