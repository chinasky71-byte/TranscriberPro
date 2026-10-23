# -*- coding: utf-8 -*-
"""install.sh: suggerimenti per famiglia AMD con --gpu-backend=auto / rocm (solo messaggi: nessuna attivazione automatica di ROCm).
`python3` e' uno stub che risponde a `gpu_detect.py --backend` e `--amd` con i dati della famiglia scelta dal test."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('bash'), reason='install.sh e solo per Linux')
TOOLS = ['bash', 'env', 'uname', 'awk', 'sed', 'grep', 'tr', 'head', 'dirname', 'cat', 'ls', 'mktemp', 'rm', 'sort', 'basename', 'cp', 'printf']

PY3 = '''#!/bin/bash
case "$*" in
  *"--backend"*) echo "$STUB_BACKEND" ;;
  *"--amd"*) printf '%s\\n' "$STUB_AMD" ;;
esac
exit 0
'''
ID = '#!/bin/bash\ncase "$1" in -u) echo 1000 ;; -un) echo tester ;; *) echo tester ;; esac\n'
DF = '#!/bin/bash\necho Filesystem\necho "x 1 1 99999999 1% /"\n'


def amd(fam, gfx, sup, path, ovr=''):
    return f'amd_family={fam}\ngfx={gfx}\nrocm_support={sup}\npath={path}\nhsa_override_gfx_version={ovr}'


@pytest.fixture
def run_install(tmp_path):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for t in TOOLS:
        p = shutil.which(t)
        if p:
            (bindir / t).symlink_to(p)
    for name, body in [('python3', PY3), ('id', ID), ('df', DF)]:
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)

    def go(backend, amd_out, *args):
        e = {'PATH': str(bindir), 'HOME': str(tmp_path), 'STUB_BACKEND': backend, 'STUB_AMD': amd_out}
        r = subprocess.run(['bash', str(ROOT / 'install.sh'), '--check', *args], env=e, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
        return r.stdout + r.stderr
    return go


@pytest.mark.parametrize('fam,gfx', [('RDNA3', 'gfx1100'), ('RDNA4', 'gfx1201'), ('CDNA', 'gfx90a')])
def test_auto_suggerisce_rocm_senza_attivarlo(run_install, fam, gfx):
    out = run_install('rocm', amd(fam, gfx, 'official', 'rocm'), '--gpu-backend=auto')
    assert f'famiglia {fam}' in out and '--gpu-backend=rocm' in out
    assert 'Backend ROCm' not in out and 'Backend Vulkan' in out        # auto resta su vulkan: ROCm solo se richiesto
    assert 'HSA_OVERRIDE' not in out


def test_auto_rdna2_spiega_override_e_bf16(run_install):
    out = run_install('rocm', amd('RDNA2', 'gfx1031', 'unofficial', 'rocm_override', '10.3.0'), '--gpu-backend=auto')
    assert 'HSA_OVERRIDE_GFX_VERSION=10.3.0' in out and 'solo per i propri processi' in out and "mai se l'hai gia' impostata" in out
    assert 'bf16' in out and 'Qwen3-ASR' in out and 'TranslateGemma' in out
    assert '--gpu-backend=rocm' in out and 'Backend ROCm' not in out


@pytest.mark.parametrize('backend', ['vulkan', 'cpu'])
def test_auto_rdna1_propone_vulkan_o_cpu(run_install, backend):
    out = run_install(backend, amd('RDNA1', 'gfx1010', 'unsupported', 'vulkan_cpu'), '--gpu-backend=auto')
    assert 'famiglia RDNA1' in out and '--gpu-backend=vulkan' in out and '--gpu-backend=cpu' in out
    assert 'Backend ROCm' not in out


def test_auto_senza_gpu_amd_nessun_messaggio_famiglia(run_install):
    out = run_install('cpu', '', '--gpu-backend=auto')
    assert 'GPU AMD: famiglia' not in out and 'gpu_detect: backend consigliato = cpu' in out


def test_rocm_esplicito_rdna2_mostra_override(run_install):
    out = run_install('rocm', amd('RDNA2', 'gfx1030', 'unofficial', 'rocm_override', '10.3.0'), '--gpu-backend=rocm')
    assert 'Backend ROCm' in out and 'HSA_OVERRIDE_GFX_VERSION=10.3.0' in out and 'bf16' in out


def test_rocm_esplicito_rdna1_avvisa_ma_non_blocca(run_install):
    out = run_install('vulkan', amd('RDNA1', 'gfx1010', 'unsupported', 'vulkan_cpu'), '--gpu-backend=rocm')
    assert 'ROCm non e\' utilizzabile' in out and '--gpu-backend=vulkan' in out and 'Backend ROCm' in out
