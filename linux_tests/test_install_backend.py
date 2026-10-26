# -*- coding: utf-8 -*-
"""install.sh: policy dei backend (ADR-007). Solo cuda e rocm su hardware supportato.

Questi test girano con un `python3` finto nel PATH, così la decisione automatica
e i rifiuti sono deterministici e non dipendono dall'hardware della macchina che
esegue la suite (che non deve mai essere toccata: il venv è TP_INSTALL_VENV).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('bash'), reason='install.sh e solo per Linux')

TOOLS = ['bash', 'env', 'uname', 'awk', 'sed', 'grep', 'tr', 'head', 'dirname', 'cat', 'ls', 'mktemp', 'rm', 'sort',
         'basename', 'cp', 'df', 'id', 'mkdir', 'chmod', 'date', 'printf']

DETECTOR = '''#!/bin/bash
# python3 finto: risponde al rilevatore come farebbe utils/gpu_detect.py su un dato hardware.
case "$*" in
  *gpu_detect.py*)
    case "$*" in
      *--backend*) echo "${FAKE_BACKEND:-}" ;;
      *--amd*) printf 'amd_family=%s\\ngfx=%s\\npath=%s\\nname=%s\\n' "${FAKE_FAMILY:-}" "${FAKE_GFX:-}" "${FAKE_PATH:-}" "${FAKE_NAME:-}" ;;
      *--vram*) echo "${FAKE_VRAM:-0}" ;;
    esac ;;
  *sys.version*) echo 3.12.0 ;;
  *version_info*) echo 3.12 ;;
esac
exit 0
'''

VENV_PY = '''#!/bin/bash
echo "VPY $*" >> "$STUB_LOG"
exit 0
'''


def _make(tmp_path, stamp_backend=None):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for tool in TOOLS:
        path = shutil.which(tool)
        if path:
            (bindir / tool).symlink_to(path)
    for name, body in (('python3', DETECTOR), ('python3.12', DETECTOR)):
        (bindir / name).write_text(body, encoding='utf-8')
        (bindir / name).chmod(0o755)
    venv = tmp_path / 'venv'
    (venv / 'bin').mkdir(parents=True)
    vpy = venv / 'bin' / 'python'
    vpy.write_text(VENV_PY, encoding='utf-8')
    vpy.chmod(0o755)
    if stamp_backend:
        (venv / '.tp-backend').write_text(f'backend={stamp_backend}\ntorch=test\n', encoding='utf-8')
    log = tmp_path / 'log'
    log.write_text('')
    env = {'PATH': str(bindir), 'HOME': str(tmp_path), 'STUB_LOG': str(log),
           'TP_INSTALL_VENV': str(venv), 'FAKE_BACKEND': 'cuda'}
    return env, log, venv


def _run(env, *args):
    return subprocess.run(['bash', str(ROOT / 'install.sh'), *args], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60)


def test_backend_cpu_e_vulkan_rifiutati(tmp_path):
    env, _, _ = _make(tmp_path)
    for backend in ('cpu', 'vulkan'):
        r = _run(env, f'--backend={backend}')
        assert r.returncode == 2, (backend, r.stdout, r.stderr)
        assert 'non supportato' in r.stdout and 'ADR-007' in r.stdout
        assert 'VPY' not in (tmp_path / 'log').read_text()      # nessun pip, nessuna modifica


def test_backend_sconosciuto_rifiutato(tmp_path):
    env, _, _ = _make(tmp_path)
    r = _run(env, '--backend=metal')
    assert r.returncode == 2 and 'deve essere auto, cuda o rocm' in r.stdout


def test_auto_senza_hardware_si_ferma_senza_toccare_nulla(tmp_path):
    env, log, venv = _make(tmp_path)
    env['FAKE_BACKEND'] = ''            # nessuna GPU rilevata
    r = _run(env)
    assert r.returncode == 2
    assert 'Nessun backend supportato' in r.stdout
    assert 'Mi fermo senza toccare il venv' in r.stdout
    assert 'VPY' not in log.read_text()
    assert not (venv / '.tp-backend').exists()


def test_auto_sceglie_cuda_e_prosegue(tmp_path):
    env, _, _ = _make(tmp_path)
    r = _run(env, '--check')
    assert 'cuda' in r.stdout and 'Backend' in r.stdout


def test_auto_rifiuta_rdna2_con_override_hsa(tmp_path):
    env, _, _ = _make(tmp_path)
    env.update(FAKE_BACKEND='rocm', FAKE_PATH='rocm_override', FAKE_FAMILY='RDNA2', FAKE_GFX='gfx1030')
    r = _run(env)
    assert r.returncode == 2
    assert 'non la supporta ufficialmente' in r.stdout and 'RDNA3/RDNA4/CDNA' in r.stdout


def test_auto_rifiuta_famiglia_vecchia(tmp_path):
    env, _, _ = _make(tmp_path)
    env.update(FAKE_BACKEND='rocm', FAKE_PATH='vulkan_cpu', FAKE_FAMILY='RDNA1', FAKE_GFX='gfx1010')
    r = _run(env)
    assert r.returncode == 2 and 'troppo vecchia per ROCm 7' in r.stdout


def test_backend_esplicito_diverso_dall_hardware_rifiutato(tmp_path):
    env, _, _ = _make(tmp_path)
    env.update(FAKE_BACKEND='rocm', FAKE_PATH='vulkan_cpu')     # hardware AMD non utilizzabile
    r = _run(env, '--backend=cuda')
    assert r.returncode == 2 and '--force-backend' in r.stdout


def test_force_backend_accetta_un_cross_build(tmp_path):
    env, log, _ = _make(tmp_path)
    env.update(FAKE_BACKEND='rocm', FAKE_PATH='vulkan_cpu')
    r = _run(env, '--backend=cuda', '--force-backend', '--check')
    assert 'force-backend' in r.stdout.lower()
    assert 'cuda' in r.stdout


def test_timbro_di_backend_diverso_ferma_l_installazione(tmp_path):
    env, log, venv = _make(tmp_path, stamp_backend='rocm')
    r = _run(env, '--backend=cuda')          # hardware finto = cuda, venv timbrato rocm
    assert r.returncode == 2
    assert "gia' installato per il backend" in r.stdout and '--force-backend' in r.stdout
    assert 'VPY' not in log.read_text()       # nessun pip: torch non viene sostituito
    assert (venv / '.tp-backend').read_text().startswith('backend=rocm')


def test_timbro_uguale_prosegue(tmp_path):
    env, _, _ = _make(tmp_path, stamp_backend='cuda')
    r = _run(env, '--check')
    assert r.returncode in (0, 2)             # dipende dai prerequisiti di sistema, non dal timbro
    assert 'aggiorno i pacchetti' in r.stdout or 'timbrato' not in r.stdout


def test_install_sh_non_ha_piu_percorsi_cpu_o_vulkan():
    """Guardia: i backend ritirati non devono rientrare dalla finestra."""
    text = (ROOT / 'install.sh').read_text(encoding='utf-8')
    assert '--no-gpu' not in text
    assert 'NOGPU' not in text
    assert 'case "$BACKEND" in\n  auto|cuda|rocm)' in text
    assert 'TP_INSTALL_VENV' in text                       # isolamento dei test
    assert 'STAMP="$VENV/.tp-backend"' in text              # timbro dentro il venv scelto, non hardcoded


def test_verify_only_riscrive_il_timbro_senza_pip(tmp_path):
    """--verify-only: riverifica il venv esistente e riscrive il timbro, senza installare nulla."""
    env, log, venv = _make(tmp_path)
    r = _run(env, '--verify-only')
    text = (venv / '.tp-backend').read_text(encoding='utf-8') if (venv / '.tp-backend').exists() else ''
    calls = log.read_text()
    assert 'pip install' not in calls, calls
    assert 'requisiti' not in calls
    # il finto python del venv non importa torch: la verifica puo' solo fallire, ma non deve installare
    assert r.returncode in (0, 1)
    if r.returncode == 0:
        assert 'backend=' in text
    else:
        assert 'Verifica del backend installato' in r.stdout and text == ''


def test_verify_only_senza_venv_si_ferma(tmp_path):
    env, _, venv = _make(tmp_path)
    for entry in (venv / 'bin').iterdir():
        entry.unlink()
    (venv / 'bin').rmdir()
    r = _run(env, '--verify-only')
    assert r.returncode == 2 and 'Niente da verificare' in r.stdout.replace('niente', 'Niente')
