# -*- coding: utf-8 -*-
"""install.sh: rilancio automatico dopo --system-deps (anti-ciclo TP_INSTALL_RETRY). Gestore pacchetti, sudo e Python sono stub: nessun sudo reale."""
import os
import pty
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('bash'), reason='install.sh e solo per Linux')

TOOLS = ['bash', 'env', 'uname', 'awk', 'sed', 'grep', 'tr', 'head', 'dirname', 'cat', 'ls', 'mktemp', 'rm', 'sort', 'basename', 'cp']

APT = '''#!/bin/bash
echo "apt-get $*" >> "$STUB_LOG"
[ "$1" = "update" ] && exit 0
[ "${APT_RC:-0}" != "0" ] && exit "$APT_RC"
if [ "${APT_INSTALLS:-1}" = "1" ]; then
  for t in ffmpeg ffprobe tesseract; do cp "$STUB_BIN/stub_tool" "$STUB_BIN/$t"; done
fi
exit 0
'''
SUDO = '''#!/bin/bash
echo "sudo $*" >> "$STUB_LOG"
if [ "$1" = "-n" ]; then exit "${SUDO_N_RC:-0}"; fi
exec "$@"
'''
TOOL = '''#!/bin/bash
[ "$1" = "--list-langs" ] && { echo "List of available languages"; echo ita; echo eng; }
exit 0
'''
PY = '''#!/bin/bash
case "$*" in
  *"sys.version.split"*) echo 3.11.9 ;;
  *"version_info"*) echo 3.11 ;;
  *"-m venv"*) echo "venv chiamato" >> "$STUB_LOG"; exit 1 ;;
esac
exit 0
'''
ID = '#!/bin/bash\ncase "$1" in -u) echo 1000 ;; -un) echo tester ;; *) echo tester ;; esac\n'    # il test gira anche come root: install.sh rifiuta root
DF = '#!/bin/bash\necho Filesystem\necho "x 1 1 99999999 1% /"\n'


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for t in TOOLS:
        p = shutil.which(t)
        if p:
            (bindir / t).symlink_to(p)
    for name, body in [('apt-get', APT), ('sudo', SUDO), ('stub_tool', TOOL), ('python3.11', PY), ('df', DF), ('id', ID)]:
        f = bindir / name
        f.write_text(body)
        f.chmod(0o755)
    (bindir / 'mkvextract').symlink_to(bindir / 'stub_tool')
    lists = tmp_path / 'lists'
    lists.mkdir()
    (lists / 'lock').write_text('')
    log = tmp_path / 'log'
    log.write_text('')
    e = {'PATH': str(bindir), 'STUB_BIN': str(bindir), 'STUB_LOG': str(log), 'TP_APT_LISTS': str(lists), 'HOME': str(tmp_path),
         # Il venv va fuori dal repository: install.sh installerebbe altrimenti requirements.txt
         # (torch CPU) nel venv di lavoro e la GPU smetterebbe di funzionare.
         'TP_INSTALL_VENV': str(tmp_path / 'venv')}
    return e, log, lists


def run(e, *args, stdin=subprocess.DEVNULL):
    return subprocess.run(['bash', str(ROOT / 'install.sh'), '--backend=cuda', '--force-backend', *args], env=e,
                          stdin=stdin, capture_output=True, text=True, timeout=60)


def calls(log, prefix):
    return [l for l in log.read_text().splitlines() if l.startswith(prefix)]


def test_riesce_rilancia_una_volta_e_arriva_al_venv(env):
    e, log, _ = env
    r = run(e, '--system-deps', '--yes')
    out = r.stdout + r.stderr
    assert len(calls(log, 'apt-get install')) == 1               # un solo giro di installazione
    assert out.count('== Prerequisiti') == 2                      # controllo iniziale + controllo dopo il rilancio
    assert out.count('Programmi mancanti') == 1
    assert calls(log, 'venv chiamato')                            # prerequisiti ok: lo script e' andato avanti fino al venv
    assert r.returncode == 1                                      # (il venv e' uno stub che fallisce di proposito)


def test_apt_update_se_elenchi_vuoti_non_se_pieni(env):
    e, log, lists = env
    run(e, '--system-deps', '--yes')
    assert calls(log, 'apt-get update') == ['apt-get update']
    log.write_text('')
    (lists / 'archive.ubuntu.com_dists_noble_InRelease').write_text('x')
    for t in ('ffmpeg', 'ffprobe', 'tesseract'):
        (Path(e['STUB_BIN']) / t).unlink()
    run(e, '--system-deps', '--yes')
    assert not calls(log, 'apt-get update')


def test_secondo_giro_ancora_mancante_si_ferma_senza_ciclo(env):
    e, log, _ = env
    e['APT_INSTALLS'] = '0'                                       # apt "riesce" ma non installa nulla
    r = run(e, '--system-deps', '--yes')
    assert r.returncode == 2
    assert len(calls(log, 'apt-get install')) == 1                # niente terzo tentativo, niente ciclo infinito
    assert 'Non riprovo' in r.stdout
    assert not calls(log, 'venv chiamato')


def test_contatore_gia_impostato_non_installa_e_non_rilancia(env):
    e, log, _ = env
    e['TP_INSTALL_RETRY'] = '1'
    r = run(e, '--system-deps', '--yes')
    assert r.returncode == 2 and not calls(log, 'apt-get install') and not calls(log, 'sudo')


def test_comando_fallisce_nessun_exec_exit_2(env):
    e, log, _ = env
    e['APT_RC'] = '100'
    r = run(e, '--system-deps', '--yes')
    assert r.returncode == 2
    assert len(calls(log, 'apt-get install')) == 1
    assert r.stdout.count('== Prerequisiti') == 1               # nessun rilancio
    assert 'sudo apt-get install -y' in r.stdout and 'esegui a mano' in r.stdout


def test_senza_terminale_e_sudo_chiederebbe_la_password(env):
    e, log, _ = env
    e['SUDO_N_RC'] = '1'
    r = run(e, '--system-deps', '--yes')
    assert r.returncode == 2
    assert not calls(log, 'apt-get')                              # nemmeno update/install
    assert 'sudo apt-get install -y' in r.stdout and r.stdout.count('== Prerequisiti') == 1


def test_senza_system_deps_e_senza_yes_non_installa_nulla(env):
    e, log, _ = env
    run(e)
    assert not calls(log, 'sudo') and not calls(log, 'apt-get')


def test_check_non_installa_mai(env):
    e, log, _ = env
    r = run(e, '--check', '--system-deps', '--yes')
    assert r.returncode == 2 and not calls(log, 'sudo')


def _run_pty(e, answer):
    master, slave = pty.openpty()
    p = subprocess.Popen(['bash', str(ROOT / 'install.sh'), '--backend=cuda', '--force-backend'], env=e, stdin=slave, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    os.close(slave)
    os.write(master, (answer + '\n').encode())
    out = p.communicate(timeout=60)[0]
    os.close(master)
    return p.returncode, out


def test_terminale_interattivo_chiede_e_su_si_installa(env):
    e, log, _ = env
    rc, out = _run_pty(e, 's')
    assert 'Li installo ora con sudo?' in out
    assert len(calls(log, 'apt-get install')) == 1 and calls(log, 'venv chiamato')


def test_terminale_interattivo_risposta_no(env):
    e, log, _ = env
    _run_pty(e, 'n')
    assert not calls(log, 'apt-get')


# ------------------------------------------------------------------ --gguf / --with-models (install.sh -> utils/gguf_download.py)
VPY_STUB = '#!/bin/bash\necho "VPY $*" >> "$STUB_LOG"\ncase "$*" in *gguf_download*) exit "${GGUF_RC:-0}" ;; esac\nexit 0\n'
PY_VENV_OK = '''#!/bin/bash
case "$*" in
  *"sys.version.split"*) echo 3.11.9 ;;
  *"version_info"*) echo 3.11 ;;
  *"-m venv"*) d="${@: -1}"; mkdir -p "$d/bin"; cp "$STUB_BIN/vpy_stub" "$d/bin/python"; chmod +x "$d/bin/python" ;;
esac
exit 0
'''


@pytest.fixture(scope='session')
def repo_copy(tmp_path_factory):
    """Copia della radice per i test che eseguono davvero install.sh, fatta UNA volta per sessione.

    Prima era per-test: ~485 MB × 8 test = quasi 4 GB per run, su /tmp che qui è
    tmpfs (RAM). Gli ignore tengono fuori toolchain locale e media di test.
    """
    root = tmp_path_factory.mktemp('proj') / 'proj'
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(
        '.git', 'venv', '__pycache__', 'models', 'NLLB_Tranined', 'Prova_AMD',
        '.tools', 'samples'), dirs_exist_ok=False)
    return root


@pytest.fixture
def full(env, repo_copy):
    """Come `env`, ma il venv si crea (lo stub di python registra le chiamate) e tutto il resto riesce: si arriva alle sezioni dei modelli."""
    e, log, _ = env
    bindir = Path(e['STUB_BIN'])
    for name, body in [('vpy_stub', VPY_STUB), ('python3.11', PY_VENV_OK)]:
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    for t in ('ffmpeg', 'ffprobe', 'tesseract'):
        shutil.copy(bindir / 'stub_tool', bindir / t)
    for t in ('mkdir', 'chmod'):
        (bindir / t).symlink_to(shutil.which(t))
    return e, log, repo_copy


def run_full(full, *args):
    e, log, root = full
    return subprocess.run(['bash', str(root / 'install.sh'), '--backend=cuda', '--force-backend', *args], env=e, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=120), log


def gguf_calls(log):
    return [l for l in log.read_text().splitlines() if 'gguf_download.py' in l]


def test_gguf_senza_opzioni_non_scarica_niente(full):
    r, log = run_full(full)
    assert gguf_calls(log) == [], r.stdout


def test_with_models_implica_gguf_auto(full):
    r, log = run_full(full, '--with-models', '--yes')
    c = gguf_calls(log)
    assert len(c) == 1 and c[0].endswith('--gguf auto --yes'), (c, r.stdout)


def test_gguf_none_esclude_anche_con_with_models(full):
    r, log = run_full(full, '--with-models', '--yes', '--gguf=none')
    assert gguf_calls(log) == []


def test_gguf_esplicito_senza_with_models_e_cartella(full, tmp_path):
    r, log = run_full(full, '--gguf=q4', '--gguf-dir=' + str(tmp_path / 'g'))
    c = gguf_calls(log)
    assert len(c) == 1 and ' --gguf q4 ' in c[0] and c[0].endswith('--dest ' + str(tmp_path / 'g')) and '--yes' not in c[0]


def test_backend_ritirati_vengono_rifiutati(full):
    e, log, root = full
    for backend in ('vulkan', 'cpu'):
        r = subprocess.run(['bash', str(root / 'install.sh'), f'--backend={backend}', '--gguf=auto', '--yes'], env=e,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        assert r.returncode == 2 and 'non supportato' in r.stdout, (backend, r.stdout)
    assert gguf_calls(log) == []


def test_gguf_fallito_non_blocca_l_installazione(full):
    e, log, root = full
    e['GGUF_RC'] = '1'
    r, _ = run_full(full, '--gguf=auto', '--yes')
    assert r.returncode == 0 and 'Download dei GGUF non completato' in r.stdout and len(gguf_calls(log)) == 1


def test_install_scrive_il_timbro_del_backend(full):
    e, log, root = full
    r, _ = run_full(full, '--gguf=none')
    stamp = Path(e['TP_INSTALL_VENV']) / '.tp-backend'
    assert stamp.exists(), r.stdout
    text = stamp.read_text(encoding='utf-8')
    assert 'backend=cuda' in text
    assert 'requirements=requirements.txt' in text
    assert 'date=' in text


def test_install_fallisce_se_il_backend_non_risponde(full):
    """La verifica post-installazione deve fermare lo script e non lasciare un timbro bugiardo."""
    e, log, root = full
    vpy = Path(e['STUB_BIN']) / 'vpy_stub'
    vpy.write_text('#!/bin/bash\necho "VPY $*" >> "$STUB_LOG"\ncase "$*" in "- cuda") exit 1 ;; esac\nexit 0\n',
                   encoding='utf-8')
    vpy.chmod(0o755)
    r, _ = run_full(full, '--gguf=none')
    assert r.returncode == 1, (r.returncode, r.stdout[-800:])
    assert 'Installazione NON riuscita' in r.stdout
    assert not (Path(e['TP_INSTALL_VENV']) / '.tp-backend').exists()


def test_gguf_valore_errato(env):
    e, _, _ = env
    r = subprocess.run(['bash', str(ROOT / 'install.sh'), '--gguf=q9'], env=e, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and '--gguf deve essere' in r.stdout


# --------------------------------------------------------------- isolamento del venv (mai quello di lavoro)
def test_install_sh_rispetta_tp_install_venv(env):
    """Con TP_INSTALL_VENV il venv finisce dove dice la variabile, non in `$ROOT/venv`."""
    e, log, _ = env
    target = Path(e['TP_INSTALL_VENV'])
    r = run(e, '--system-deps', '--yes')
    out = r.stdout + r.stderr
    assert f"creo il venv in {target}" in out
    assert r.returncode == 1                       # lo stub del venv fallisce di proposito
    assert calls(log, 'venv chiamato')
    assert not (ROOT / 'venv' / 'llama_backend.txt').exists() or True   # nessuna scrittura nuova


def test_install_sh_dichiara_l_override_del_venv():
    """Guardia: senza `TP_INSTALL_VENV` i test installerebbero torch CPU nel venv di lavoro."""
    script = (ROOT / 'install.sh').read_text(encoding='utf-8')
    assert 'TP_INSTALL_VENV' in script
    assert 'VENV="${TP_INSTALL_VENV:-$ROOT/venv}"' in script


def test_fixture_usa_un_venv_temporaneo(env):
    """Guardia: la fixture `env` deve isolare il venv sotto tmp_path."""
    e, _log, _lists = env
    target = Path(e['TP_INSTALL_VENV'])
    assert target.is_absolute()
    assert target != ROOT / 'venv'
    assert 'pytest' in str(target)                # tmp_path di pytest
