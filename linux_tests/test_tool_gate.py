# -*- coding: utf-8 -*-
"""ToolGate (fase 4a): le regole di mutua esclusione tra coda e strumenti sono quelle della GUI, e l'avvio e' atomico."""
import itertools
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'linux_tests'))

from core.services.tool_gate import ToolGate, START_BLOCKED_KEYS, TOOL_BLOCKED_KEYS  # noqa: E402
from test_queue_service_characterization import qt, svc  # noqa: E402,F401  (stessa fixture della GUI)
from test_tpweb_queue import wq, web  # noqa: E402,F401


def test_verdetto_di_avvio_identico_a_queue_service_su_tutte_le_combinazioni(svc):
    """Stesse risposte di QueueService.can_start per ognuna delle 16 combinazioni (coda piena/vuota, OCR, glossario, sincronizzazione)."""
    for n, (has_items, ocr, gl, sy) in enumerate(itertools.product((False, True), repeat=4)):
        svc.clear()
        if has_items:
            assert svc.enqueue([f'/a{n}.mkv'])         # la vista ricorda i file gia' visti: un nome nuovo a ogni giro
        svc.glossary_active, svc.sync_active = gl, sy
        g = ToolGate()
        g.glossary_active, g.sync_active, g.ocr_running = gl, sy, ocr
        assert g.queue_verdict(has_items) == svc.can_start(ocr_running=ocr).value, (has_items, ocr, gl, sy)


def test_apertura_strumenti_come_la_gui():
    g = ToolGate(processing=lambda: True)
    assert g.begin_tool('glossary') == 'glossary_blocked_processing' and g.begin_tool('sync') == 'sync_blocked_processing'
    assert g.snapshot() == {'glossary': False, 'sync': False, 'ocr': False}            # un rifiuto non lascia flag
    g = ToolGate()
    assert g.begin_tool('sync') is None and g.sync_active
    assert g.begin_tool('glossary') == 'glossary_blocked_sync' and not g.glossary_active
    assert g.begin_tool('sync') == 'sync_already_running'
    g.end_tool('sync')
    assert g.begin_tool('glossary') is None
    assert g.begin_tool('sync') == 'sync_blocked_glossary'
    assert g.begin_tool('glossary') == 'running'
    g.end_tool('glossary')
    assert g.snapshot() == {'glossary': False, 'sync': False, 'ocr': False}
    with pytest.raises(ValueError):
        g.begin_tool('ocr')


def test_ogni_messaggio_di_blocco_esiste_in_italiano_e_in_inglese():
    from utils.translations import Translations
    keys = {k for pair in START_BLOCKED_KEYS.values() for k in pair} | set(TOOL_BLOCKED_KEYS.values())
    for lang in ('it', 'en'):
        assert [k for k in keys if k not in Translations.TEXTS[lang]] == []


def test_gara_tra_due_strumenti_ne_vince_uno_solo():
    for _ in range(50):
        g = ToolGate()
        out, start = [], threading.Barrier(8)

        def go(tool):
            start.wait()
            out.append((tool, g.begin_tool(tool)))
        ts = [threading.Thread(target=go, args=(('glossary', 'sync')[i % 2],)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert sum(1 for _, r in out if r is None) == 1
        assert g.glossary_active != g.sync_active


def test_http_avvio_bloccato_da_uno_strumento_con_i_messaggi_della_gui(web):
    c, q = web
    q.add(['/a.mkv'])
    q.gate.glossary_active = True
    r = c.post('/api/queue/start')
    assert r.status_code == 409 and r.json() == {'verdict': 'glossary', 'title_key': 'tools_glossary', 'text_key': 'glossary_running_blocks_processing'}
    assert not q.is_processing
    q.gate.glossary_active, q.gate.sync_active = False, True
    assert c.post('/api/queue/start').json()['text_key'] == 'sync_running_blocks_processing'
    q.gate.sync_active, q.gate.ocr_running = False, True
    j = c.post('/api/queue/start').json()
    assert (j['title_key'], j['text_key']) == ('mw_start_blocked_title', 'mw_start_blocked_ocr')
    q.gate.ocr_running = False
    assert c.get('/api/queue').json()['tools'] == {'glossary': False, 'sync': False, 'ocr': False}


def test_gli_strumenti_non_partono_a_coda_in_lavoro_e_la_coda_non_parte_con_uno_strumento_attivo(web):
    c, q = web
    q.add(['/a.mkv'])
    assert q.start() == 'ok'
    assert q.gate.begin_tool('glossary') == 'glossary_blocked_processing'
    q.stop(); q.join(20)
    q.clear(); q.add(['/b.mkv'])
    assert q.gate.begin_tool('glossary') is None
    assert q.start() == 'glossary'
    q.gate.end_tool('glossary')
    assert q.start() == 'ok'
    q.stop(); q.join(20)


def test_l_avvio_della_coda_aspetta_il_lucchetto_degli_strumenti(web):
    """Atomicita': mentre uno strumento sta decidendo (lucchetto preso) la coda non puo' partire in mezzo."""
    c, q = web
    q.add(['/a.mkv'])
    done = threading.Event()
    with q.gate.lock:
        t = threading.Thread(target=lambda: (q.start(), done.set()), daemon=True)
        t.start()
        assert not done.wait(0.4) and not q.is_processing
        q.gate.glossary_active = True                      # lo strumento ha vinto prima che la coda guardasse i flag
    assert done.wait(5)
    assert not q.is_processing and q.gate.snapshot()['glossary'] is True
