# -*- coding: utf-8 -*-
"""Contratto di /events (SSE), /api/state e /api/i18n: numeri progressivi, raggruppamento, ripresa, stato completo."""
import json
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tpweb.events import EventBus  # noqa: E402
from tpweb.runner import ServerThread  # noqa: E402


@pytest.fixture()
def srv():
    bus = EventBus(keep=50)
    s = ServerThread(bus=bus, get_state=lambda: {'queue': ['a.mkv'], 'n': bus.last_seq}).start()
    yield s
    s.stop()


def client(srv):
    c = httpx.Client(base_url=f'http://127.0.0.1:{srv.port}', timeout=10, headers={'X-TP-Token': srv.token})
    return c


def read_sse(srv, headers=None, params=None, want=1, timeout=8):
    """Legge `want` messaggi SSE (blocchi separati da riga vuota) e ritorna [(id, event, data)]."""
    out = []
    h = {'X-TP-Token': srv.token, **(headers or {})}
    with httpx.Client(base_url=f'http://127.0.0.1:{srv.port}', timeout=timeout) as c:
        with c.stream('GET', '/events', headers=h, params=params) as r:
            assert r.status_code == 200 and r.headers['content-type'].startswith('text/event-stream')
            buf = ''
            t0 = time.time()
            for chunk in r.iter_text():
                buf += chunk
                while '\n\n' in buf:
                    block, buf = buf.split('\n\n', 1)
                    if not block.strip() or block.startswith(':'):
                        continue
                    ev = {'id': None, 'event': 'message', 'data': ''}
                    for line in block.split('\n'):
                        k, _, v = line.partition(': ')
                        if k in ev:
                            ev[k] = v
                    out.append((ev['id'], ev['event'], json.loads(ev['data'])))
                    if len(out) >= want:
                        return out
                if time.time() - t0 > timeout:
                    break
    return out


def test_bus_numeri_progressivi_e_since():
    b = EventBus(keep=3)
    assert [b.publish('x', i) for i in range(5)] == [1, 2, 3, 4, 5]
    evs, gap = b.since(3)
    assert [e['seq'] for e in evs] == [4, 5] and gap is False
    evs, gap = b.since(0)                      # 1 e 2 sono stati scartati
    assert [e['seq'] for e in evs] == [3, 4, 5] and gap is True
    evs, gap = b.since(5)
    assert evs == [] and gap is False


def test_nuova_connessione_riceve_lo_stato_completo_poi_gli_eventi(srv):
    srv.bus.publish('log', 'riga 1')
    got = []
    t = threading.Thread(target=lambda: got.extend(read_sse(srv, want=2)))
    t.start()
    time.sleep(0.5)
    srv.bus.publish('log', 'riga 2')
    t.join(10)
    (id1, ev1, d1), (id2, ev2, d2) = got
    assert ev1 == 'state' and d1['state']['queue'] == ['a.mkv'] and d1['seq'] == 1 and id1 == '1'
    assert ev2 == 'message' and [m['d'] for m in d2['msgs']] == ['riga 2'] and id2 == '2'


def test_ripresa_con_last_event_id_senza_stato_ne_duplicati(srv):
    for i in range(5):
        srv.bus.publish('log', f'r{i}')
    (id_, ev, d), = read_sse(srv, headers={'Last-Event-ID': '2'}, want=1)
    assert ev == 'message' and [m['seq'] for m in d['msgs']] == [3, 4, 5] and id_ == '5'


def test_ripresa_con_parametro_after(srv):
    for i in range(3):
        srv.bus.publish('log', f'r{i}')
    (id_, ev, d), = read_sse(srv, params={'after': 1}, want=1)
    assert [m['seq'] for m in d['msgs']] == [2, 3]


def test_eventi_persi_riportano_lo_stato_completo(srv):
    for i in range(80):                         # il bus tiene 50 eventi
        srv.bus.publish('log', i)
    (id_, ev, d), = read_sse(srv, headers={'Last-Event-ID': '3'}, want=1)
    assert ev == 'state' and d['seq'] == 80 and id_ == '80'


def test_gli_eventi_vicini_sono_raggruppati(srv):
    """30 eventi pubblicati a 2 ms l'uno (60 ms in tutto) arrivano in pochi messaggi, in ordine e senza perdite."""
    msgs = []

    def reader():
        with httpx.Client(base_url=f'http://127.0.0.1:{srv.port}', timeout=8, headers={'X-TP-Token': srv.token}) as c:
            with c.stream('GET', '/events') as r:
                buf, n = '', 0
                for chunk in r.iter_text():
                    buf += chunk
                    while '\n\n' in buf:
                        block, buf = buf.split('\n\n', 1)
                        data = [l[6:] for l in block.split('\n') if l.startswith('data: ')]
                        if data and 'msgs' in json.loads(data[0]):
                            msgs.append(json.loads(data[0])['msgs'])
                            n += len(msgs[-1])
                    if n >= 30:
                        return
    t = threading.Thread(target=reader)
    t.start()
    time.sleep(0.5)
    for i in range(30):
        srv.bus.publish('log', i)
        time.sleep(0.002)
    t.join(10)
    seen = [m['d'] for batch in msgs for m in batch]
    assert seen == list(range(30))
    assert len(msgs) <= 4


def test_stato_e_ping(srv):
    c = client(srv)
    srv.bus.publish('x')
    assert c.get('/api/state').json() == {'seq': 1, 'state': {'queue': ['a.mkv'], 'n': 1}}
    assert c.get('/api/ping').json()['ok'] is True


def test_i18n_usa_il_dizionario_unico_e_rifiuta_altre_lingue(srv):
    from utils.translations import Translations
    c = client(srv)
    for lang in ('it', 'en'):
        r = c.get(f'/api/i18n/{lang}')
        assert r.status_code == 200 and r.json()['texts'] == Translations.TEXTS[lang]
    assert c.get('/api/i18n/fr').status_code == 404
    assert c.get('/api/i18n/..%2Fx').status_code in (404, 422)
