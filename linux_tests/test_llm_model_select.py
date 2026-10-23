# -*- coding: utf-8 -*-
"""utils/llm_model_select.py + Config.resolve_llm_model: scelta Qwen 14B/7B per VRAM. Nessun modello, nessuna GPU."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from utils import llm_model_select as sel  # noqa: E402

GB = 1024


def _mk(d, which=('14b', '7b'), shards=None):
    shards = shards or {'14b': 3, '7b': 2}
    for k in which:
        n = shards[k]
        for i in range(1, n + 1):
            (d / f'qwen2.5-{k}-instruct-q4_k_m-{i:05d}-of-{n:05d}.gguf').write_bytes(b'x')


def _name(p):
    return Path(p).name if p else None


@pytest.mark.parametrize('vram,exp14', [(12288, True), (24 * GB, True), (12000, True), (11264, False), (8188, False)])
def test_auto_soglia_grande(tmp_path, vram, exp14):
    _mk(tmp_path)
    p, ngl = sel.pick_qwen_model(tmp_path, vram)
    assert ('14b' in p) == exp14
    assert ngl == -1


def test_auto_vram_4gb_7b_parziale_e_nessuna_gpu_cpu(tmp_path):
    _mk(tmp_path)
    p, ngl = sel.pick_qwen_model(tmp_path, 4 * GB)
    assert '7b' in p and 0 < ngl < 28
    for none in (None, 0):
        p, ngl = sel.pick_qwen_model(tmp_path, none)
        assert '7b' in p and ngl == 0


def test_8gb_7b_pieno(tmp_path):
    _mk(tmp_path)
    p, ngl = sel.pick_qwen_model(tmp_path, 8188)
    assert _name(p) == 'qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf' and ngl == -1


def test_un_solo_file(tmp_path):
    _mk(tmp_path, ('14b',))
    p, ngl = sel.pick_qwen_model(tmp_path, 24 * GB)
    assert '14b' in p and ngl == -1
    p, ngl = sel.pick_qwen_model(tmp_path, 8188)          # solo 14B su 8 GB: parziale
    assert '14b' in p and 0 < ngl < 48
    assert sel.pick_qwen_model(tmp_path, None) == (p, 0)
    d2 = tmp_path / 'b'
    d2.mkdir()
    _mk(d2, ('7b',))
    p, ngl = sel.pick_qwen_model(d2, 24 * GB)
    assert '7b' in p and ngl == -1


def test_nessun_file_e_cartella_inesistente(tmp_path):
    assert sel.pick_qwen_model(tmp_path, 24 * GB) == (None, 0)
    assert sel.pick_qwen_model(tmp_path / 'nope', 24 * GB) == (None, 0)


def test_shard_mancante_scarta_il_modello(tmp_path):
    _mk(tmp_path)
    (tmp_path / 'qwen2.5-14b-instruct-q4_k_m-00003-of-00003.gguf').unlink()
    p, _ = sel.pick_qwen_model(tmp_path, 24 * GB)
    assert '7b' in p


def test_fast_spento_di_default(tmp_path):
    _mk(tmp_path)
    assert sel.FAST_MODE_ENABLED is False
    assert sel.pick_qwen_model(tmp_path, 24 * GB, 'fast') == sel.pick_qwen_model(tmp_path, 24 * GB, 'auto')


def test_preferenze(tmp_path, monkeypatch):
    monkeypatch.setattr(sel, 'FAST_MODE_ENABLED', True)
    _mk(tmp_path)
    assert '7b' in sel.pick_qwen_model(tmp_path, 24 * GB, 'fast')[0]
    assert sel.pick_qwen_model(tmp_path, 24 * GB, 'fast')[1] == -1
    assert '14b' in sel.pick_qwen_model(tmp_path, 24 * GB, 'quality')[0]
    assert '14b' in sel.pick_qwen_model(tmp_path, 24 * GB, 'auto')[0]
    assert '7b' in sel.pick_qwen_model(tmp_path, 8188, 'quality')[0]      # VRAM non regge il 14B
    assert '14b' in sel.pick_qwen_model(tmp_path, 24 * GB, 'boh')[0]       # valore sconosciuto = auto
    d2 = tmp_path / 'solo14'
    d2.mkdir()
    _mk(d2, ('14b',))
    assert '14b' in sel.pick_qwen_model(d2, 24 * GB, 'fast')[0]            # 7B assente: ripiega sul 14B
    d3 = tmp_path / 'solo7'
    d3.mkdir()
    _mk(d3, ('7b',))
    assert '7b' in sel.pick_qwen_model(d3, 24 * GB, 'quality')[0]


@pytest.fixture
def _gd_pulito():
    """La cache di gpu_detect si svuota anche se il test fallisce."""
    from utils import gpu_detect as gd
    gd.clear_cache()
    yield gd
    gd.clear_cache()


def _fake_run(stdout='', rc=0, exc=None):
    """Runner di gpu_detect che risponde solo a nvidia-smi."""
    def run(cmd, timeout):
        assert 'nvidia-smi' in cmd[0] and timeout <= 6
        if exc:
            raise exc
        return rc, stdout
    return run


class _Reg:
    """Registro finto minimo: una scheda in HKLM\\HARDWARE\\DEVICEMAP\\VIDEO."""

    def __init__(self, vals):
        self.k = {'hardware\\devicemap\\video': {'\\Device\\Video0': '\\Registry\\Machine\\System\\X\\Video\\{G1}\\0000'},
                  'system\\x\\video\\{g1}\\0000': vals}

    def values(self, path):
        return self.k[path.lower()]

    def subkeys(self, path):
        raise FileNotFoundError(path)


def _use_runner(monkeypatch, run, registry=None, files=()):
    """detect_vram_mib -> gpu_detect con SOLO nvidia-smi finto: registro (salvo `registry`), NVML e Vulkan spenti (su
    questo PC sono reali e darebbero 12288 anche nei casi che devono restituire None)."""
    from utils import gpu_detect as gd
    monkeypatch.delenv('TP_GPU_FORCE_BACKEND', raising=False)
    monkeypatch.delenv('TP_GPU_DETECT', raising=False)
    real = getattr(gd.detect_gpus, 'real', gd.detect_gpus)       # gia' sostituita da una chiamata precedente?
    c = gd.DetectContext(platform='win32', env={'SystemRoot': r'C:\Windows'}, runner=run, cwd=r'C:\work',
                         which=lambda n: r'C:\NVIDIA\nvidia-smi.exe' if n == 'nvidia-smi' else None,
                         is_file=lambda p: p in set(files), registry=registry, nvml_loader=lambda c: None)
    fake = lambda force=False, ctx=None: real(force=True, ctx=c)  # noqa: E731
    fake.real = real
    monkeypatch.setattr(gd, 'detect_gpus', fake)


def test_detect_vram(monkeypatch, _gd_pulito):
    gd = _gd_pulito
    two = ('12288, 11465, 617.42, 00000000:01:00.0, 0x250410DE, 8.6, NVIDIA GeForce RTX 3060\n'
           '8188, 8000, 617.42, 00000000:02:00.0, 0x248410DE, 8.6, NVIDIA GeForce RTX 3070\n')
    _use_runner(monkeypatch, _fake_run(two))
    assert sel.detect_vram_mib() == 12288                          # massimo tra le GPU, come prima
    _use_runner(monkeypatch, _fake_run('', 9))
    assert sel.detect_vram_mib() is None
    _use_runner(monkeypatch, _fake_run('N/A\n'))
    assert sel.detect_vram_mib() is None
    _use_runner(monkeypatch, _fake_run(exc=FileNotFoundError()))
    assert sel.detect_vram_mib() is None
    _use_runner(monkeypatch, _fake_run(exc=subprocess.TimeoutExpired('nvidia-smi', 3)))
    assert sel.detect_vram_mib() is None
    monkeypatch.setattr(gd, 'detect_gpus', lambda force=False, ctx=None: 1 / 0)
    assert sel.detect_vram_mib() is None                           # qualsiasi guasto -> None, mai eccezioni


AMD_REG = {'DriverDesc': 'AMD Radeon RX 7800 XT', 'MatchingDeviceId': 'pci\\ven_1002&dev_747e',
           'HardwareInformation.qwMemorySize': 16 * 1024 ** 3}


def test_detect_vram_amd_su_windows_non_conta(monkeypatch, _gd_pulito):
    """Decisione del 22/10 (backend='cuda'): una AMD con loader Vulkan e' 'vulkan' per gpu_detect, ma per Qwen NON da'
    VRAM finche' il llama installato e' CUDA/CPU."""
    gd = _gd_pulito
    _use_runner(monkeypatch, _fake_run(exc=FileNotFoundError()), registry=_Reg(AMD_REG),
                files={r'C:\Windows\System32\vulkan-1.dll'})
    rep = gd.detect_gpus()
    assert gd.recommended_backend(rep) == 'vulkan' and gd.usable_vram_mib(rep) == 16384   # il caso e' davvero esercitato
    assert sel.detect_vram_mib() is None


def test_detect_vram_na_usa_il_registro(monkeypatch, _gd_pulito):
    na = '[N/A], [N/A], 617.42, 00000000:01:00.0, 0x250410DE, 8.6, NVIDIA GeForce RTX 3060\n'
    nv = {'DriverDesc': 'NVIDIA GeForce RTX 3060', 'MatchingDeviceId': 'pci\\ven_10de&dev_2504',
          'HardwareInformation.qwMemorySize': 12 * 1024 ** 3}
    _use_runner(monkeypatch, _fake_run(na), registry=_Reg(nv))
    assert sel.detect_vram_mib() == 12288                          # prima era None


def _cfg(tmp_path, monkeypatch, vram, **vals):
    """Config minimale senza leggere/scrivere il file reale: solo get() e resolve_llm_model."""
    from utils import config as cfgmod
    c = cfgmod.Config.__new__(cfgmod.Config)
    data = {'gender_correction_model_path': '', 'fallback_translator_model_path': '',
            'llm_model_preference': 'auto'}
    data.update(vals)
    c.get = lambda k, d=None: data.get(k, d)
    monkeypatch.setattr(sel, 'detect_vram_mib', lambda: vram)
    real = sel.pick_qwen_model
    monkeypatch.setattr(sel, 'pick_qwen_model', lambda _dir, v, pref='auto': real(tmp_path, v, pref))
    return c


def test_config_percorso_esplicito_vince_sempre(tmp_path, monkeypatch):
    _mk(tmp_path)
    mine = tmp_path / 'mio.gguf'
    mine.write_bytes(b'x')
    c = _cfg(tmp_path, monkeypatch, 8188, gender_correction_model_path=str(mine), llm_model_preference='fast')
    assert c.resolve_llm_model('gender_correction_model_path', 'fast') == (str(mine), -1)
    assert c.get_fallback_translator_model() == (str(mine), -1)


def test_config_percorso_vuoto_o_mancante_usa_vram_e_preferenza(tmp_path, monkeypatch):
    _mk(tmp_path)
    monkeypatch.setattr(sel, 'FAST_MODE_ENABLED', True)
    c = _cfg(tmp_path, monkeypatch, 24 * GB)
    assert '14b' in c.resolve_llm_model()[0]
    assert '7b' in c.resolve_llm_model(preference='fast')[0]          # override per job
    c.get = lambda k, d=None: {'llm_model_preference': 'fast'}.get(k, '' if 'path' in k else d)
    assert '7b' in c.resolve_llm_model()[0]                           # da config
    assert '14b' in c.resolve_llm_model(preference='quality')[0]      # il job batte la config
    c.get = lambda k, d=None: {'gender_correction_model_path': str(tmp_path / 'sparito.gguf')}.get(k, '')
    assert '14b' in c.resolve_llm_model()[0]                          # percorso mancante -> ripiego
    assert c.get_fallback_translator_model_path().endswith('00001-of-00003.gguf')


def test_config_senza_modelli_ne_gpu(tmp_path, monkeypatch):
    c = _cfg(tmp_path, monkeypatch, None)
    assert c.resolve_llm_model() == ('', 0)


def test_percorso_esplicito_non_invoca_nvidia_smi_e_none_non_resta_in_cache(tmp_path, monkeypatch):
    import utils.llm_model_select as m
    from utils import config as cfg
    calls = []
    monkeypatch.setattr(m, 'detect_vram_mib', lambda: calls.append(1))
    c = cfg.Config.__new__(cfg.Config)
    f = tmp_path / 'm.gguf'
    f.write_bytes(b'x')
    c.settings = {'gender_correction_model_path': str(f)}
    assert c.resolve_llm_model('gender_correction_model_path') == (str(f), -1)
    assert calls == []                                       # percorso esplicito: nessuna lettura della VRAM
    c.settings = {}
    c.resolve_llm_model('gender_correction_model_path')
    c.resolve_llm_model('gender_correction_model_path')
    assert len(calls) == 2 and not hasattr(c, '_llm_vram_mib')   # None non viene messo in cache: si riprova
