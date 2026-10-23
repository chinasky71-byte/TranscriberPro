# -*- coding: utf-8 -*-
"""utils/platform_compat.py: valori identici a quelli cablati prima su Windows, equivalenti POSIX altrove."""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import platform_compat as pc  # noqa: E402


def test_venv_python_windows_identico_al_codice_precedente():
    root = Path('X:/proj')
    assert pc.venv_python(root / 'venv_canary', windows=True) == root / 'venv_canary' / 'Scripts' / 'python.exe'


def test_venv_python_posix():
    assert pc.venv_python('/opt/p/venv_canary', windows=False) == Path('/opt/p/venv_canary') / 'bin' / 'python'


def test_venv_python_accetta_str_e_path():
    assert pc.venv_python('a', windows=True) == pc.venv_python(Path('a'), windows=True)


def test_no_window_flags():
    assert pc.no_window_flags(windows=True) == 0x08000000
    assert pc.no_window_flags(windows=False) == 0
    if sys.platform == 'win32':
        assert pc.no_window_flags() == subprocess.CREATE_NO_WINDOW == 0x08000000
    else:
        assert pc.no_window_flags() == 0


def test_is_windows_coerente():
    assert pc.IS_WINDOWS == (sys.platform == 'win32')


def test_kill_tree_uccide_figli_e_nipoti(monkeypatch):
    import psutil
    try:
        import harness as H     # l'harness del banco visivo blocca Popen: qui serve un processo vero
        monkeypatch.setattr(subprocess.Popen, '__init__', H.ORIG_POPEN_INIT)
    except ImportError:
        pass
    code = ("import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);time.sleep(60)")
    proc = subprocess.Popen([sys.executable, '-c', code], creationflags=pc.no_window_flags())
    try:
        t0, kids = time.time(), []
        while time.time() - t0 < 10 and not kids:           # attende che il nipote esista
            kids = psutil.Process(proc.pid).children(recursive=True)
            time.sleep(0.1)
        assert kids, 'nipote non partito'
        assert pc.kill_tree(proc.pid) is True
        proc.wait(timeout=5)
        assert not any(psutil.pid_exists(k.pid) and psutil.Process(k.pid).status() != psutil.STATUS_ZOMBIE for k in kids)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_kill_tree_pid_inesistente():
    import psutil
    pid = 2 ** 22 - 3
    while psutil.pid_exists(pid):
        pid -= 1
    assert pc.kill_tree(pid) is True


def test_pathmap_windows_identita_e_posix_equivalente():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pathmap import to_native
    assert to_native('V:\\Film\\X.mkv', windows=True) == 'V:\\Film\\X.mkv'
    assert to_native('V:\\Film\\X.mkv', windows=False) == '/mnt/v/Film/X.mkv'
    assert to_native('W:/b/x.mkv', windows=False) == '/mnt/w/b/x.mkv'
    assert to_native('V:\\', windows=False) == '/mnt/v/'
    assert to_native('rel\\a.mkv', windows=False) == 'rel/a.mkv'


def test_percorso_windows_straniero():
    b = chr(92)
    assert pc.is_foreign_windows_path('V:' + b + 'Film' + b + 'x.mkv', windows=False)
    assert pc.is_foreign_windows_path('C:/Users/a', windows=False)
    assert not pc.is_foreign_windows_path('V:' + b + 'Film', windows=True)          # su Windows mai
    assert not pc.is_foreign_windows_path('/mnt/v/Film', windows=False)
    assert not pc.is_foreign_windows_path('models/x', windows=False)
    assert not pc.is_foreign_windows_path('', windows=False) and not pc.is_foreign_windows_path(None, windows=False)
    assert not pc.is_foreign_windows_path('V:foo', windows=False)                    # non e' un percorso assoluto


def test_config_get_ignora_percorso_windows_solo_fuori_da_windows(monkeypatch):
    import utils.config as cfg
    b = chr(92)
    c = cfg.Config.__new__(cfg.Config)
    c.settings = {'nllb_finetuned_model_path': 'D:' + b + 'm', 'ffmpeg_model_path': '/x/y', 'k': 5}
    monkeypatch.setattr(cfg, 'is_foreign_windows_path', lambda v: pc.is_foreign_windows_path(v, windows=True))
    assert c.get('k') == 5 and c.get('ffmpeg_model_path') == '/x/y'
    assert c.get('nllb_finetuned_model_path') == 'D:' + b + 'm'                         # Windows: invariato
    monkeypatch.setattr(cfg, 'is_foreign_windows_path', lambda v: pc.is_foreign_windows_path(v, windows=False))
    assert c.get('nllb_finetuned_model_path') == ''                                    # Linux: torna al default
    assert c.get('nllb_finetuned_model_path', 'dflt') == 'dflt'


def test_find_tool_path_vince_e_su_windows_cerca_nelle_cartelle_standard(tmp_path, monkeypatch):
    exe = tmp_path / 'Tesseract-OCR' / 'tesseract.exe'
    exe.parent.mkdir()
    exe.write_bytes(b'x')
    monkeypatch.setenv('ProgramFiles', str(tmp_path))
    monkeypatch.delenv('ProgramW6432', raising=False)
    monkeypatch.delenv('ProgramFiles(x86)', raising=False)
    monkeypatch.setattr(pc.Path, 'home', classmethod(lambda cls: tmp_path / 'home'))
    monkeypatch.setattr(pc.shutil, 'which', lambda n: None)
    assert pc.find_tool('tesseract', windows=True) == str(exe)          # fuori dal PATH, in Program Files
    assert pc.find_tool('tesseract', windows=False) is None             # fuori da Windows: solo il PATH
    assert pc.find_tool('mkvmerge', windows=True) is None               # non installato
    monkeypatch.setattr(pc.shutil, 'which', lambda n: '/usr/bin/' + n)
    assert pc.find_tool('tesseract', windows=True) == '/usr/bin/tesseract'   # nel PATH: stesso valore di which


def test_find_tool_scoop_shim(tmp_path, monkeypatch):
    shim = tmp_path / 'scoop' / 'shims' / 'mkvextract.exe'
    shim.parent.mkdir(parents=True)
    shim.write_bytes(b'x')
    monkeypatch.delenv('ProgramFiles', raising=False)
    monkeypatch.delenv('ProgramW6432', raising=False)
    monkeypatch.delenv('ProgramFiles(x86)', raising=False)
    monkeypatch.setattr(pc.Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(pc.shutil, 'which', lambda n: None)
    assert pc.find_tool('mkvextract', windows=True) == str(shim)


def test_notify_linux_usa_notify_send_se_c_e_e_non_fa_nulla_altrimenti(monkeypatch):
    import core.queue_runner as q
    calls = []
    monkeypatch.setattr(q.sys, 'platform', 'linux')
    monkeypatch.setattr(q.subprocess, 'Popen', lambda cmd, **k: calls.append(cmd))
    monkeypatch.setattr(q.shutil, 'which', lambda n: '/usr/bin/notify-send')
    q.notify('Titolo', 'Messaggio')
    assert calls == [['/usr/bin/notify-send', '--app-name=Transcriber Pro', '--', 'Titolo', 'Messaggio']]
    monkeypatch.setattr(q.shutil, 'which', lambda n: None)
    q.notify('Titolo', 'Messaggio')
    assert len(calls) == 1                                  # senza notify-send: nessun errore e nessun processo
