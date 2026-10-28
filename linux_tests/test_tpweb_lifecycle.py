# -*- coding: utf-8 -*-
"""Fetta 1f: scelta dell'interfaccia (--ui), lock di un solo server, convivenza con GUI/coda headless, /api/quit e avvio vero di
`python -m tpweb` e `python main.py --ui web` (con PyQt6 bloccato: la web UI non deve mai importarlo)."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

from tpweb import lifecycle  # noqa: E402
from tpweb.ui_choice import requested_ui, ui_from_args  # noqa: E402


# --------------------------------------------------------------------------------------------------------------- --ui
@pytest.mark.parametrize('argv,expect', [([], None), (['--ui', 'web'], 'web'), (['--ui=qt'], 'qt'), (['x', '--ui', 'qt', '--ui', 'web'], 'qt'),
                                         (['--no-browser'], None)])
def test_ui_from_args(argv, expect):
    assert ui_from_args(argv) == expect


@pytest.mark.parametrize('argv', [['--ui'], ['--ui', 'gtk'], ['--ui='], ['--ui=WEB']])
def test_ui_non_valida(argv):
    with pytest.raises(ValueError):
        ui_from_args(argv)


def test_ui_flag_vince_sul_config_e_il_predefinito_e_qt():
    assert requested_ui([]) == 'qt'
    assert requested_ui([], lambda k, d: 'web') == 'web'
    assert requested_ui(['--ui', 'qt'], lambda k, d: 'web') == 'qt'
    assert requested_ui([], lambda k, d: 'boh') == 'qt'
    assert requested_ui([], lambda k, d: (_ for _ in ()).throw(RuntimeError('config rotta'))) == 'qt'


# ---------------------------------------------------------------------------------------------------------------- lock
def test_lock_un_solo_server(tmp_path):
    other = tmp_path / 'l.lock'
    other.write_text(json.dumps({'pid': 424242, 'since': 'x'}))
    held = lifecycle.ServerLock(other, is_server=lambda pid: pid == 424242)
    assert held.holder() == 424242 and held.acquire() is False
    assert json.loads(other.read_text())['pid'] == 424242                    # non sovrascritto


def test_lock_orfano_si_sovrascrive_e_il_rilascio_e_solo_del_proprietario(tmp_path):
    p = tmp_path / 'l.lock'
    p.write_text(json.dumps({'pid': 424242}))
    orphan = lifecycle.ServerLock(p, is_server=lambda pid: False)
    assert orphan.holder() is None and orphan.acquire() is True and json.loads(p.read_text())['pid'] == os.getpid()
    orphan.release()
    assert not p.exists()
    p.write_text(json.dumps({'pid': 424242}))
    orphan.release()                                                          # il lock non e' suo: resta
    assert p.exists()
    p.write_text('non json')
    assert lifecycle.ServerLock(p, is_server=lambda pid: True).acquire() is True


def test_lock_non_tiene_conto_di_se_stesso(tmp_path):
    p = tmp_path / 'l.lock'
    p.write_text(json.dumps({'pid': os.getpid()}))
    assert lifecycle.ServerLock(p, is_server=lambda pid: True).acquire() is True


def sleeper(*tag):
    return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', *tag])


def test_conflitto_con_coda_headless_e_con_la_gui(tmp_path):
    assert lifecycle.conflicts(tmp_path) == []
    q = sleeper('queue_runner')
    try:
        (tmp_path / 'queue.lock').write_text(json.dumps({'pid': q.pid}))
        assert lifecycle.conflicts(tmp_path) == ['headless']
        (tmp_path / 'queue.lock').write_text(json.dumps({'pid': 2 ** 22 + 12345}))      # processo inesistente: lock orfano
        assert lifecycle.conflicts(tmp_path) == []
    finally:
        q.kill()
    g = sleeper('/x/Transcriber/main.py')
    web = sleeper('/x/Transcriber/main.py', '--ui', 'web')
    try:
        time.sleep(0.3)
        assert lifecycle.conflicts(tmp_path) == ['gui']
        g.kill()
        g.wait()
        assert lifecycle.conflicts(tmp_path) == []                              # un altro server web non e' «la GUI»
    finally:
        g.kill()
        web.kill()


def test_conflitti_escludono_se_stessi_altri_progetti_e_processi_che_non_sono_la_coda(tmp_path, monkeypatch):
    import types
    fake = lambda pid, cl: types.SimpleNamespace(info={'pid': pid, 'cmdline': cl})       # noqa: E731
    import psutil
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs=None: iter([fake(os.getpid(), ['python', '/x/Transcriber/main.py'])]))
    assert lifecycle.conflicts(tmp_path) == []                                           # il processo stesso non conta
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs=None: iter([fake(1, ['python', '/altro/progetto/main.py'])]))
    assert lifecycle.conflicts(tmp_path) == []                                           # un altro main.py non e' la GUI
    monkeypatch.undo()
    other = sleeper('qualcosa_altro')
    try:
        (tmp_path / 'queue.lock').write_text(json.dumps({'pid': other.pid}))
        assert lifecycle.conflicts(tmp_path) == []                                       # pid vivo ma non e' la coda headless
    finally:
        other.kill()


def test_riconosce_un_server_web_dal_processo():
    web = sleeper('/x/main.py', '--ui', 'web')
    mod = sleeper('-m', 'tpweb')
    plain = sleeper('/x/main.py')
    try:
        time.sleep(0.3)
        assert lifecycle._is_tpweb_process(web.pid) and lifecycle._is_tpweb_process(mod.pid)
        assert not lifecycle._is_tpweb_process(plain.pid) and not lifecycle._is_tpweb_process(2 ** 22 + 999)
    finally:
        for p in (web, mod, plain):
            p.kill()


# ------------------------------------------------------------------------------------------------------------ /api/quit
@pytest.fixture
def quit_env(tmp_path, monkeypatch):
    import _queue_testkit as kit
    from utils import config as cfg
    monkeypatch.setenv('HOME', str(tmp_path / 'h'))
    monkeypatch.setattr(cfg.Config, 'CONFIG_DIR', tmp_path / 'h' / '.transcriberpro', raising=False)
    monkeypatch.setattr(cfg.Config, 'CONFIG_FILE', tmp_path / 'h' / '.transcriberpro' / 'config.json', raising=False)
    cfg.reset_config()
    monkeypatch.setattr(subprocess, 'Popen', kit.PopenSpy())
    import threading
    from tpweb.launcher import build
    ev = threading.Event()
    srv = build(cfg.get_config(), history_path=tmp_path / 'h.json', project_root=ROOT, shutdown_fn=lambda: None, quit_event=ev).start()
    c = httpx.Client(base_url=f'http://127.0.0.1:{srv.port}', timeout=15, headers={'X-TP-Token': srv.token})
    yield c, srv, ev, kit, tmp_path
    srv.queue.stop()
    srv.queue.join(20)
    c.close()
    srv.stop()
    cfg.reset_config()


def test_quit_a_riposo_esce(quit_env):
    c, srv, ev, *_ = quit_env
    assert c.post('/api/quit', json={}).json() == {'quit': True} and ev.is_set()


def test_quit_con_la_coda_al_lavoro_chiede_force(quit_env):
    c, srv, ev, kit, tmp = quit_env
    c.post('/api/queue/add', json={'paths': kit.make_videos(tmp, 'slow.mkv')})
    c.post('/api/queue/start')
    t0 = time.time()
    while time.time() - t0 < 30 and srv.queue.rows()[0]['status'] != 'processing':
        time.sleep(0.05)
    r = c.post('/api/quit', json={})
    assert r.status_code == 409 and r.json() == {'quit': False, 'reason': 'processing'} and not ev.is_set()
    assert c.post('/api/quit', json={'force': True}).json() == {'quit': True} and ev.is_set()
    srv.queue.join(30)
    assert not srv.queue.is_processing and srv.queue.rows()[0]['status'] == 'failed'     # il file in corso e' stato fermato


# --------------------------------------------------------------------------------------------------- avvio vero (processi)
def env_for(tmp_path, block_qt=False):
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    e = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT))
    if block_qt:
        stub = tmp_path / 'stub'
        (stub / 'PyQt6').mkdir(parents=True, exist_ok=True)
        (stub / 'PyQt6' / '__init__.py').write_text("raise ImportError('PyQt6 bloccato: la web UI non deve importarlo')\n")
        e['PYTHONPATH'] = f'{stub}{os.pathsep}{ROOT}'
    return e


def start(argv, env):
    p = subprocess.Popen([sys.executable, *argv], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t0 = time.time()
    line = ''
    while time.time() - t0 < 30:
        line = p.stdout.readline()
        if line.startswith('http://'):
            break
        if p.poll() is not None:
            break
    return p, line.strip()


def stop(p, url):
    m = re.match(r'http://127.0.0.1:(\d+)/\?t=(.+)', url)
    if p.poll() is None and m:
        try:
            httpx.post(f'http://127.0.0.1:{m.group(1)}/api/quit', json={}, headers={'X-TP-Token': m.group(2)}, timeout=10)
        except httpx.HTTPError:
            pass
    try:
        p.wait(15)
    except subprocess.TimeoutExpired:
        p.kill()


@pytest.mark.parametrize('argv', [['-m', 'tpweb', '--no-browser'], ['main.py', '--ui', 'web', '--no-browser'], ['main.py', '--ui=web', '--no-browser']])
def test_avvio_vero_secondo_server_rifiutato_e_uscita_ordinata(tmp_path, argv):
    env = env_for(tmp_path, block_qt=True)
    p, url = start(argv, env)
    try:
        m = re.match(r'http://127\.0\.0\.1:(\d+)/\?t=(.+)', url)
        assert m, (url, p.poll(), p.stderr.read() if p.poll() is not None else '')
        port, token = m.groups()
        c = httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10, follow_redirects=True)
        assert c.get('/', params={'t': token}).status_code == 200 and c.get('/api/ping').json()['ok'] is True
        assert c.get('/api/settings').json()['general']['language'] == 'auto'
        second = subprocess.run([sys.executable, *argv], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
        assert second.returncode == 3 and 'gia' in second.stderr
        assert c.post('/api/quit', json={}, headers={'X-TP-Token': token}).json() == {'quit': True}
        assert p.wait(20) == 0
        assert not (tmp_path / 'home' / '.transcriberpro' / 'tpweb.lock').exists()          # lock rilasciato
    finally:
        stop(p, url)


def test_con_la_gui_aperta_il_server_web_non_parte(tmp_path):
    gui = sleeper('/x/Transcriber/main.py')
    try:
        time.sleep(0.3)
        r = subprocess.run([sys.executable, '-m', 'tpweb', '--no-browser'], cwd=str(ROOT), env=env_for(tmp_path, True),
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 3 and 'la GUI' in r.stderr
        assert not (tmp_path / 'home' / '.transcriberpro' / 'tpweb.lock').exists()       # nessun lock lasciato
    finally:
        gui.kill()


def test_ui_non_valida_esce_con_2_senza_aprire_nulla(tmp_path):
    r = subprocess.run([sys.executable, 'main.py', '--ui', 'gtk'], cwd=str(ROOT), env=env_for(tmp_path, True), capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 2 and "--ui: valore non valido 'gtk'" in r.stderr


def test_config_con_ui_web_avvia_la_web(tmp_path):
    env = env_for(tmp_path, block_qt=True)
    cfgdir = tmp_path / 'home' / '.transcriberpro'
    cfgdir.mkdir(parents=True)
    (cfgdir / 'config.json').write_text(json.dumps({'ui': 'web'}), encoding='utf-8')
    p, url = start(['main.py', '--no-browser'], env)
    try:
        assert url.startswith('http://127.0.0.1:')
    finally:
        stop(p, url)
