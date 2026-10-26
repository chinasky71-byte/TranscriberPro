# -*- coding: utf-8 -*-
"""install.sh: classificazione delle GPU AMD e decisione del backend (ADR-007).

`python3` è uno stub che risponde a `gpu_detect.py --backend` e `--amd` con i dati
della famiglia scelta dal test; `TP_KFD_PATH` punta a un file temporaneo così la
decisione non dipende dall'hardware della macchina che esegue la suite.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('bash'), reason='install.sh e solo per Linux')
TOOLS = ['bash', 'env', 'uname', 'awk', 'sed', 'grep', 'tr', 'head', 'dirname', 'cat', 'ls', 'mktemp', 'rm', 'sort',
         'basename', 'cp', 'printf']

PY3 = '''#!/bin/bash
case "$*" in
  *"--backend"*) echo "$STUB_BACKEND" ;;
  *"--amd"*) printf '%s\\n' "$STUB_AMD" ;;
  *"--vram"*) echo 16000 ;;
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
    for tag in TOOLS:
        found = shutil.which(tag)
        if found:
            (bindir / tag).symlink_to(found)
    for name, body in [('python3', PY3), ('id', ID), ('df', DF)]:
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    kfd = tmp_path / 'kfd'
    kfd.write_text('')
    kfd.chmod(0o660)

    def go(backend, amd_out, *args, kfd_available=True):
        env = {'PATH': str(bindir), 'HOME': str(tmp_path), 'STUB_BACKEND': backend, 'STUB_AMD': amd_out,
               'TP_KFD_PATH': str(kfd if kfd_available else tmp_path / 'niente-kfd')}
        result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--check', *args], env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        return result.stdout + result.stderr
    return go


@pytest.mark.parametrize('fam,gfx', [('RDNA3', 'gfx1100'), ('RDNA4', 'gfx1201'), ('CDNA', 'gfx90a')])
def test_auto_sceglie_rocm_su_famiglie_supportate(run_install, fam, gfx):
    out = run_install('rocm', amd(fam, gfx, 'official', 'rocm'))
    assert f'famiglia {fam}' in out
    assert 'rocm' in out and 'torch 2.10.0+rocm7.0' in out
    assert 'Nessun backend supportato' not in out


def test_auto_rifiuta_rdna2_spiegando_il_motivo(run_install):
    out = run_install('rocm', amd('RDNA2', 'gfx1031', 'unofficial', 'rocm_override', '10.3.0'))
    assert 'RDNA2' in out and 'non la supporta ufficialmente' in out
    assert 'Mi fermo senza toccare il venv' in out


@pytest.mark.parametrize('fam,gfx', [('RDNA1', 'gfx1010'), ('GCN', 'gfx900')])
def test_auto_rifiuta_famiglie_vecchie(run_install, fam, gfx):
    out = run_install('rocm', amd(fam, gfx, 'none', 'vulkan_cpu'))
    assert fam in out and 'troppo vecchia per ROCm 7' in out
    assert 'Mi fermo senza toccare il venv' in out


def test_auto_senza_gpu_non_propone_nulla(run_install):
    out = run_install('cpu', '')
    assert 'Nessun backend supportato' in out and 'GPU AMD' not in out


def test_rocm_senza_kfd_accessibile_rifiuta(run_install):
    out = run_install('rocm', amd('RDNA4', 'gfx1200', 'official', 'rocm'), kfd_available=False)
    assert '/dev/kfd assente' in out and 'Mi fermo senza toccare il venv' in out


def test_rocm_esplicito_su_rdna2_rifiuta(run_install):
    out = run_install('rocm', amd('RDNA2', 'gfx1030', 'unofficial', 'rocm_override', '10.3.0'), '--backend=rocm')
    assert 'non la supporta ufficialmente' in out and 'cross-build' in out


def test_force_backend_su_rdna2_procede(run_install):
    out = run_install('rocm', amd('RDNA2', 'gfx1030', 'unofficial', 'rocm_override', '10.3.0'),
                      '--backend=rocm', '--force-backend')
    assert 'force-backend' in out.lower()
    assert 'Backend' in out and 'torch 2.10.0+rocm7.0' in out
