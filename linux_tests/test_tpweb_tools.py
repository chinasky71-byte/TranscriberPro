# -*- coding: utf-8 -*-
"""Fase 4b: Glossario sul server. Motore vero (`GlossaryRunEngine`) con un finto CLI (tpweb_glossary_stub.py), home e cartella di lavoro isolate
(niente file nel repository ne' nella home vera), mutua esclusione con la coda, annullamento, report che resta sul server."""
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

import _tpweb_e2e as e2e  # noqa: E402
from core.jobs.glossary_run import GlossaryRunEngine  # noqa: E402

STUB = ROOT / 'linux_tests' / 'tpweb_glossary_stub.py'


def stub_engine(payload, work, listener):
    return GlossaryRunEngine(payload, work, listener, locate=lambda: (Path(sys.executable), STUB, ROOT), available=lambda: True)


@pytest.fixture
def srv(tmp_path, monkeypatch):
    from core.services import glossary_service as GS
    monkeypatch.setattr(GS, 'PROJECT_ROOT', tmp_path / 'proj')                 # work_dir sotto tmp, mai nel repository
    from utils import config as cfg
    s, config = e2e.make_server_with_tools(tmp_path, monkeypatch, {'glossary': stub_engine})
    c = httpx.Client(base_url=f'http://127.0.0.1:{s.port}', timeout=15, headers={'X-TP-Token': s.token})
    c.srv, c.tmp, c.config = s, tmp_path, config
    c.show = tmp_path / 'show'
    c.show.mkdir()
    yield c
    c.close()
    s.stop()


def wait_status(c, want, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get('/api/tools/glossary').json()
        if st['status'] in want:
            return st
        time.sleep(0.05)
    raise AssertionError(f'stato {st["status"]} invece di {want}')


def run(c, name, **kw):
    return c.post('/api/tools/glossary/run', json={'show_dir': str(c.show), 'name': name, **kw})


def test_run_completo_stato_log_e_report_sul_server(srv):
    c = srv
    assert c.get('/api/tools/glossary').json()['status'] == 'idle'
    assert run(c, 'ok', tmdb_id=555).json() == {'started': True}
    st = wait_status(c, {'done'})
    assert st['gate']['ok'] is True and st['phase'] == 'align' and (st['done'], st['total']) == (1, 4)
    assert st['log'] == ['avvio ok_555', 'fine'] and st['error'] is None
    assert [x['term'] for x in st['report']['candidates']] == ['Winterfell', 'Raven']
    assert st['run_info'] == {'show_dir': str(c.show), 'name': 'ok_555', 'tmdb_id': 555}
    assert c.get('/api/state').json()['state']['tools']['glossary']['status'] == 'done'     # anche nello snapshot per chi si ricollega
    assert c.srv.queue.gate.snapshot()['glossary'] is False                                 # flag liberato dal thread del run


def test_salva_solo_i_termini_del_report_con_le_rese_digitate(srv):
    c = srv
    run(c, 'ok', tmdb_id=555); wait_status(c, {'done'})
    r = c.post('/api/tools/glossary/save', json={'rows': [{'term': 'Winterfell', 'approved': True, 'rendering': ' Grande Inverno '},
                                                          {'term': 'Raven', 'approved': False, 'rendering': 'Corvo'},
                                                          {'term': 'Inventato', 'approved': True, 'rendering': 'x'}]})
    assert r.status_code == 200 and r.json()["saved"] == 1, r.text
    f = c.tmp / 'home' / '.transcriberpro' / 'glossary' / 'tmdb_555.json'
    g = json.loads(f.read_text(encoding='utf-8'))
    assert 'Inventato' not in json.dumps(g) and 'Raven' not in json.dumps(g) and 'Grande Inverno' in json.dumps(g, ensure_ascii=False)
    assert (c.tmp / 'home' / '.transcriberpro' / 'glossary' / 'tmdb_555_used.json').exists() or list(f.parent.glob('*used*'))     # episodi marcati usati
    r = c.post('/api/tools/glossary/save', json={'rows': [{'term': 'Raven', 'approved': False}]})
    assert r.status_code == 200 and r.json() == {'ok': False, 'reason': 'no_terms'}


def test_salva_senza_tmdb_o_senza_report(srv):
    c = srv
    assert c.post('/api/tools/glossary/save', json={'rows': []}).json()['reason'] == 'no_report'
    run(c, 'ok'); wait_status(c, {'done'})                                                   # nessun tmdb id
    r = c.post('/api/tools/glossary/save', json={'rows': [{'term': 'Winterfell', 'approved': True, 'rendering': 'x'}]})
    assert r.status_code == 422 and r.json()['reason'] == 'no_tmdb'
    assert c.post('/api/tools/glossary/save', json={'rows': [{'term': 'Winterfell', 'approved': True, 'rendering': 'x'}], 'tmdb_id': 9}).json()['saved'] == 1


def test_gate_insufficiente_errore_e_report_illeggibile(srv):
    c = srv
    run(c, 'gateko'); st = wait_status(c, {'done'})
    assert st['gate'] == {'ok': False, 'blocks': 100, 'need_blocks': 6000} and st['report']['candidates'] == []
    c.post('/api/tools/glossary/reset')
    run(c, 'err'); st = wait_status(c, {'failed'})
    assert st['error'] == {'key': None, 'msg': 'qualcosa e andato storto'}
    c.post('/api/tools/glossary/reset')
    run(c, 'badreport'); st = wait_status(c, {'failed'})
    assert st['error']['key'] == 'glossary_report_unreadable' and st['error']['msg']


def test_cartella_assente_e_un_run_alla_volta(srv):
    c = srv
    assert c.post('/api/tools/glossary/run', json={'show_dir': str(c.tmp / 'nope')}).status_code == 422
    assert c.post('/api/tools/glossary/run', json={'show_dir': ''}).json() == {'error': 'no_folder'}
    assert run(c, 'slow').status_code == 200
    r = run(c, 'slow2')
    assert r.status_code == 409 and r.json()['blocked'] == 'running'
    assert c.post('/api/tools/glossary/reset').status_code == 409                          # col run in corso non si azzera
    assert c.post('/api/tools/glossary/cancel').json() == {'cancelling': True}
    st = wait_status(c, {'failed'})
    assert st['error']['msg'] == "Annullato dall'utente"
    assert c.post('/api/tools/glossary/cancel').json() == {'cancelling': False}


def test_mutua_esclusione_con_la_coda_e_la_sincronizzazione(srv):
    c = srv
    c.srv.queue.add(['/a.mkv'])
    run(c, 'slow')
    wait_status(c, {'running'})
    r = c.post('/api/queue/start')
    assert r.status_code == 409 and r.json()['verdict'] == 'glossary'                       # la coda non parte con il glossario attivo
    c.post('/api/tools/glossary/cancel'); wait_status(c, {'failed'})
    c.post('/api/tools/glossary/reset')
    c.srv.queue.gate.sync_active = True
    r = run(c, 'ok')
    assert r.status_code == 409 and r.json()['blocked'] == 'glossary_blocked_sync'
    assert c.srv.queue.gate.snapshot()['glossary'] is False
    c.srv.queue.gate.sync_active = False
    c.srv.queue.queue.take_next(); c.srv.queue.on_file_started('/a.mkv')                   # coda in lavoro (finto)
    c.srv.queue._thread = __import__('threading').Thread(target=time.sleep, args=(2,), daemon=True); c.srv.queue._thread.start()
    r = run(c, 'ok')
    assert r.status_code == 409 and r.json()['blocked'] == 'glossary_blocked_processing'


def test_chiusura_del_server_annulla_il_run_e_non_lascia_processi(srv):
    c = srv
    run(c, 'slow')
    st = wait_status(c, {'running'})
    t0 = time.time()
    while 'STUB_SLOW_STARTED' not in c.get('/api/tools/glossary').json()['log'] and time.time() - t0 < 15:
        time.sleep(0.05)
    pid = c.srv.app.state.tools.glossary._engine._proc.pid
    c.srv.stop()
    import os
    with pytest.raises(OSError):
        os.kill(pid, 0) if not _is_zombie(pid) else (_ for _ in ()).throw(OSError())


def _is_zombie(pid):
    try:
        return Path(f'/proc/{pid}/status').read_text().split('State:')[1].split()[0] == 'Z'
    except Exception:
        return False


def test_nomi_dalla_cartella_e_ricerca_tmdb_fuori_dal_ciclo_degli_eventi(srv, monkeypatch):
    c = srv
    season = c.tmp / 'Mio Show' / 'Season 2'
    season.mkdir(parents=True)
    (season / 'Mio.Show.S02E01.mkv').write_text('x')
    r = c.get('/api/tools/glossary/names', params={'folder': str(season)}).json()
    assert r['is_season'] is True and r['folder_name'] == 'Season 2' and r['parent_name'] == 'Mio Show' and 'Mio Show' in r['names']
    assert c.get('/api/tools/glossary/names', params={'folder': str(c.tmp / 'zz')}).status_code == 422
    from core.services import glossary_service as GS
    calls = []

    def slow(names):
        calls.append(names); time.sleep(0.6)
        return {'id': 42, 'title': 'Mio Show'}, 'Mio Show'
    monkeypatch.setattr(GS, 'resolve_tmdb', slow)
    t0 = time.time()
    import threading
    out = []
    th = threading.Thread(target=lambda: out.append(c.post('/api/tools/glossary/resolve', json={'names': ['Mio Show']}).json()))
    th.start()
    time.sleep(0.15)
    assert c.get('/api/tools/glossary').status_code == 200 and time.time() - t0 < 0.5       # il server risponde mentre la ricerca va avanti
    th.join(5)
    assert out == [{'found': True, 'tmdb_id': 42, 'title': 'Mio Show', 'used': 'Mio Show'}] and calls == [['Mio Show']]
    monkeypatch.setattr(GS, 'resolve_tmdb', lambda names: (None, None))
    assert c.post('/api/tools/glossary/resolve', json={'names': ['x']}).json() == {'found': False}
