# -*- coding: utf-8 -*-
"""P1(c): prove di sicurezza del server locale (token, Host, Origin, CORS, intestazioni, indirizzo di ascolto).
Uso:   python -m pytest tpweb/proto/p1_security_tests.py -q"""
import socket
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tpweb.proto.p1_server import ServerThread  # noqa: E402


@pytest.fixture(scope='module')
def srv():
    s = ServerThread().start()
    yield s
    s.stop()


def client(srv, **kw):
    return httpx.Client(base_url=f'http://127.0.0.1:{srv.port}', follow_redirects=False, timeout=10, **kw)


def authed(srv):
    c = client(srv)
    r = c.get('/', params={'t': srv.token})
    assert r.status_code == 303
    return c


def test_senza_credenziali_nulla_si_apre(srv):
    c = client(srv)
    for path in ('/', '/api/ping', '/events'):
        assert c.get(path).status_code == 401, path
    assert c.post('/api/echo', json={'a': 1}).status_code == 401


def test_token_errato_e_giusto(srv):
    c = client(srv)
    assert c.get('/', params={'t': 'sbagliato'}).status_code == 401
    r = c.get('/', params={'t': srv.token})
    assert r.status_code == 303 and r.headers['location'] == '/'
    sc = r.headers['set-cookie'].lower()
    assert 'httponly' in sc and 'samesite=strict' in sc and 'path=/' in sc
    assert c.get('/').status_code == 200 and c.get('/api/ping').json()['ok'] is True        # cookie ricordato dal client


def test_host_non_ammesso_anche_con_credenziali_valide(srv):
    c = authed(srv)
    for host in ('evil.example.com', f'evil.example.com:{srv.port}', f'127.0.0.1:{srv.port + 1}', '10.0.0.5:80', ''):
        r = c.get('/api/ping', headers={'Host': host})
        assert r.status_code == 403, host
    assert c.get('/api/ping', headers={'Host': f'localhost:{srv.port}'}).status_code == 200


def test_origin_estranea_rifiutata_sui_metodi_non_sicuri(srv):
    c = authed(srv)
    assert c.post('/api/echo', json={'x': 1}, headers={'Origin': 'https://evil.example.com'}).status_code == 403
    assert c.post('/api/echo', json={'x': 1}, headers={'Origin': 'null'}).status_code == 403
    assert c.post('/api/echo', json={'x': 1}, headers={'Origin': f'http://127.0.0.1:{srv.port}'}).status_code == 200
    # client non browser: niente Origin ma serve l'intestazione col token
    c2 = client(srv)
    assert c2.post('/api/echo', json={'x': 1}).status_code == 401
    assert c2.post('/api/echo', json={'x': 1}, headers={'X-TP-Token': srv.token}).status_code == 200
    assert c2.post('/api/echo', json={'x': 1}, headers={'X-TP-Token': 'no'}).status_code == 401


def test_nessun_cors(srv):
    c = authed(srv)
    r = c.options('/api/ping', headers={'Origin': 'https://evil.example.com', 'Access-Control-Request-Method': 'GET'})
    assert r.status_code == 405
    for resp in (r, c.get('/api/ping', headers={'Origin': 'https://evil.example.com'}), c.get('/')):
        assert not any(h.lower().startswith('access-control-') for h in resp.headers)


def test_intestazioni_di_sicurezza(srv):
    r = authed(srv).get('/')
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h['cache-control'] == 'no-store' and h['x-content-type-options'] == 'nosniff'
    assert h['cross-origin-resource-policy'] == 'same-origin'
    assert "default-src 'self'" in h['content-security-policy']


def test_ascolta_solo_su_loopback(srv):
    socks = srv.server.servers[0].sockets
    assert socks and all(s.getsockname()[0] == '127.0.0.1' for s in socks)
    try:
        other = socket.gethostbyname(socket.gethostname())
    except OSError:
        pytest.skip('indirizzo di rete non risolvibile')
    if other.startswith('127.'):
        pytest.skip('solo loopback disponibile')
    with pytest.raises((ConnectionRefusedError, OSError)):
        socket.create_connection((other, srv.port), timeout=3).close()


def test_il_token_non_resta_nell_url_dopo_il_primo_accesso(srv):
    c = client(srv)
    r = c.get('/', params={'t': srv.token})
    assert srv.token not in r.headers['location']
