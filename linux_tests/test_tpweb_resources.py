# -*- coding: utf-8 -*-
"""ResourceSampler (core/services/resource_sampler.py) e /api/resources (fetta 1e), con psutil e NVML finti."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

from core.services.resource_sampler import ResourceSampler, format_speed  # noqa: E402
from test_resource_monitor_characterization import FakeNvml, FakePsutil  # noqa: E402
from tpweb.runner import ServerThread  # noqa: E402


def make(gpu=True):
    ps, nv, clock = FakePsutil(), FakeNvml(), [100.0]
    s = ResourceSampler(ps, nv if gpu else None, 'H' if gpu else None, lambda: clock[0])
    s.start()
    return s, ps, nv, clock


@pytest.mark.parametrize('kbs,out', [(0, ('0.0 KB/s', False)), (0.1, ('0.0 KB/s', False)), (0.11, ('0.1 KB/s', True)),
                                     (1023.9, ('1023.9 KB/s', True)), (1024, ('1.00 MB/s', True)), (3072, ('3.00 MB/s', True))])
def test_format_speed(kbs, out):
    assert format_speed(kbs) == out


def test_campione_completo():
    s, ps, nv, clock = make()
    clock[0] += 2
    ps.net = NS(bytes_sent=2048, bytes_recv=1024 * 1024 * 4)
    r = s.sample()
    assert (r.cpu, r.ram, r.gpu) == (12.34, 56.78, 37) and r.vram_percent == 25 and r.vram_used_gb == 3
    assert r.down == ('2.00 MB/s', True) and r.up == ('1.0 KB/s', True)


def test_senza_gpu_non_ci_sono_valori_gpu():
    s, *_ = make(gpu=False)
    r = s.sample()
    assert r.gpu is None and r.vram_percent is None and r.cpu == 12.34


def test_errori_come_nella_gui():
    s, ps, nv, clock = make()
    nv.fail_mem = True
    clock[0] += 1
    r = s.sample()
    assert r.gpu == 37 and r.vram_percent is None and r.down is not None
    ps.fail_cpu = True
    clock[0] += 1
    r = s.sample()
    assert r.cpu is None and r.ram is None and r.gpu is None and r.down is None       # tutto il resto saltato, rete compresa


def test_primo_campione_senza_riferimento_e_tempo_fermo():
    s = ResourceSampler(FakePsutil(), None, None, lambda: 5.0)
    assert s.sample().down is None                    # nessun riferimento precedente
    assert s.sample().down is None                    # tempo fermo: niente divisione per zero


@pytest.fixture
def web():
    s, ps, nv, clock = make()
    srv = ServerThread(sampler=s).start()
    c = httpx.Client(base_url=f'http://127.0.0.1:{srv.port}', timeout=10, headers={'X-TP-Token': srv.token})
    yield c, ps, clock
    c.close()
    srv.stop()


def test_endpoint_risorse(web):
    c, ps, clock = web
    clock[0] += 1
    ps.net = NS(bytes_sent=0, bytes_recv=1024 * 512)
    r = c.get('/api/resources').json()
    assert r == {'cpu': 12.34, 'ram': 56.78, 'gpu_available': True, 'gpu': 37, 'vram_percent': 25.0, 'vram_used_gb': 3.0,
                 'down': {'text': '512.0 KB/s', 'active': True}, 'up': {'text': '0.0 KB/s', 'active': False}}


def test_endpoint_senza_token_rifiutato(web):
    c, *_ = web
    assert httpx.get(str(c.base_url) + '/api/resources').status_code == 401


def test_endpoint_senza_gpu():
    s, *_ = make(gpu=False)
    srv = ServerThread(sampler=s).start()
    try:
        r = httpx.get(f'http://127.0.0.1:{srv.port}/api/resources', headers={'X-TP-Token': srv.token}).json()
    finally:
        srv.stop()
    assert r['gpu_available'] is False and r['gpu'] is None and r['vram_percent'] is None and r['cpu'] == 12.34
