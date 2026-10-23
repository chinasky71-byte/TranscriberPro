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
    e = {'PATH': str(bindir), 'STUB_BIN': str(bindir), 'STUB_LOG': str(log), 'TP_APT_LISTS': str(lists), 'HOME': str(tmp_path)}
    return e, log, lists


def run(e, *args, stdin=subprocess.DEVNULL):
    return subprocess.run(['bash', str(ROOT / 'install.sh'), '--no-gpu', *args], env=e, stdin=stdin,
                          capture_output=True, text=True, timeout=60)


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
    p = subprocess.Popen(['bash', str(ROOT / 'install.sh'), '--no-gpu'], env=e, stdin=slave, stdout=subprocess.PIPE,
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
