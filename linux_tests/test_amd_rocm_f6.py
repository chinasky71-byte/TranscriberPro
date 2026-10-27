# -*- coding: utf-8 -*-
"""F6: requirements-rocm.txt coerente con requirements.txt, ramo `--gpu-backend=rocm` di install.sh, amd_smoke_test.py."""
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _pins(path):
    d = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^([A-Za-z0-9_.\-]+)==([^\s#]+)', line.strip())
        if m:
            d[m.group(1).lower().replace('_', '-')] = m.group(2)
    return d


REQ = _pins(ROOT / 'requirements.txt')
ROCM = _pins(ROOT / 'requirements-rocm.txt')


def _load_smoke():
    spec = importlib.util.spec_from_file_location('amd_smoke_test', ROOT / 'scripts_manutenzione' / 'amd_smoke_test.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- requirements-rocm.txt ---------------------------------------------------------------------------------------------

def test_rocm_requirements_have_no_cuda_or_nvidia_pins():
    text = (ROOT / 'requirements-rocm.txt').read_text(encoding='utf-8')
    code = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith('#')]
    joined = '\n'.join(code)
    assert 'cu126' not in joined and 'cu124' not in joined
    assert 'nvidia-ml-py' not in joined
    assert 'llama_cpp_python' not in joined.lower().replace('-', '_')


def test_rocm_torch_pins():
    assert ROCM['torch'] == '2.10.0+rocm7.0'
    assert ROCM['torchaudio'] == '2.10.0+rocm7.0'
    assert ROCM['torchcodec'] == REQ['torchcodec']
    assert 'download.pytorch.org/whl/rocm7.0' in (ROOT / 'requirements-rocm.txt').read_text(encoding='utf-8')


def test_rocm_requirements_differ_only_where_declared():
    declared = {'torch', 'torchaudio', 'bitsandbytes'}
    # ADR-008: faster-whisper/ctranslate2/whisperx non sono piu' dipendenze
    removed = {'llama-cpp-python', 'nvidia-ml-py'}
    for name, ver in ROCM.items():
        if name in declared:
            continue
        assert REQ.get(name) == ver, name
    assert removed.isdisjoint(ROCM)
    assert set(REQ) - set(ROCM) == removed


def test_nvidia_requirements_untouched():
    text = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
    assert 'torch==2.8.0+cu126' in text and 'nvidia-ml-py==' in text
    assert 'ctranslate2' not in text and 'faster-whisper' not in text   # ADR-008


# --- install.sh --------------------------------------------------------------------------------------------------------

def _install(*args):
    env = dict(os.environ)
    return subprocess.run(['bash', str(ROOT / 'install.sh'), *args], capture_output=True, text=True, env=env, timeout=120)


@pytest.mark.skipif(sys.platform != 'linux' or os.geteuid() == 0, reason='install.sh rifiuta root e non-Linux')
def test_install_rocm_check_reports_kfd_and_does_not_modify():
    before = (ROOT / 'venv').exists()
    p = _install('--check', '--gpu-backend=rocm')
    out = p.stdout + p.stderr
    assert 'Backend ROCm' in out
    assert '--gpu-backend=rocm non e\' ancora disponibile' not in out
    if not os.path.exists('/dev/kfd'):
        assert '/dev/kfd assente' in out and p.returncode == 2
    assert (ROOT / 'venv').exists() == before


@pytest.mark.skipif(sys.platform != 'linux' or os.geteuid() == 0, reason='install.sh rifiuta root e non-Linux')
def test_install_ritira_cpu_e_vulkan():
    # ADR-007: restano solo cuda e rocm; i backend ritirati devono fermare lo script subito
    for backend in ('cpu', 'vulkan'):
        p = _install('--check', f'--backend={backend}')
        assert p.returncode == 2 and 'non supportato' in p.stdout, (backend, p.stdout)


def test_install_script_is_executable_and_has_rocm_branch():
    assert os.access(ROOT / 'install.sh', os.X_OK)
    text = (ROOT / 'install.sh').read_text(encoding='utf-8')
    assert 'requirements-rocm.txt' in text
    # ADR-008: il wheel ctranslate2 ROCm e whisperx non si installano piu'
    assert 'rocm-python-wheels-Linux.zip' not in text and 'whisperx==' not in text


# --- amd_smoke_test.py -------------------------------------------------------------------------------------------------

def test_smoke_anonymize_removes_home_and_user(monkeypatch):
    smoke = _load_smoke()
    monkeypatch.setenv('USER', 'mariorossi')
    home = os.path.expanduser('~')
    out = smoke.anonymize('file %s/x.gguf utente mariorossi' % home)
    assert home not in out or home == '/'
    assert 'mariorossi' not in out


def test_smoke_run_py_classifies_results():
    smoke = _load_smoke()
    assert smoke.run_py('print(\'{"a": 1}\')')[0] == 'OK'
    assert smoke.run_py('import modulo_che_non_esiste_xyz')[0] == 'SKIP'
    st, txt = smoke.run_py('import os, signal; os.kill(os.getpid(), signal.SIGABRT)')
    assert st == 'FAIL' and 'crash nativo' in txt
    assert smoke.run_py('import time; time.sleep(5)', timeout=1)[0] == 'FAIL'


def test_smoke_main_writes_report_without_gpu(tmp_path):
    smoke = _load_smoke()
    out = tmp_path / 'r.txt'
    assert smoke.main(['--out', str(out)]) == 0
    text = out.read_text(encoding='utf-8')
    assert 'RIASSUNTO:' in text and '== gpu_detect --json: OK' in text and '== Sistema: OK' in text
