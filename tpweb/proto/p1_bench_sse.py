# -*- coding: utf-8 -*-
"""P1(b): prestazioni del flusso di eventi SSE verso una pagina vera (Chromium via Playwright).

Misura: righe consegnate, numero di eventi raggruppati, latenza server->pagina (ms), attivita' lunghe del thread principale
della pagina, righe nel DOM (tetto 5.000 come il log della GUI attuale), memoria JS. Scrive results/p1_sse_<sistema>.json.

Uso:   python p1_bench_sse.py [--burst 5000] [--rate 10] [--seconds 10] [--channel msedge] [--headed]
Su Windows `--channel msedge` usa Edge (stesso motore di WebView2). Su Linux nel cloud usa il Chromium di /opt/pw-browsers.
"""
import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tpweb.proto.p1_server import ServerThread  # noqa: E402

RESULTS = Path(__file__).resolve().parent / 'results'


def run(burst=5000, rate=10.0, seconds=10.0, channel=None, headed=False) -> dict:
    from playwright.sync_api import sync_playwright
    import psutil
    srv = ServerThread().start()
    proc = psutil.Process()
    cpu0 = sum(proc.cpu_times()[:2])
    t0 = time.time()
    try:
        with sync_playwright() as p:
            kw = {'headless': not headed, 'args': ['--no-sandbox']}
            if channel:
                kw['channel'] = channel
            elif os.path.exists('/opt/pw-browsers/chromium'):
                kw['executable_path'] = '/opt/pw-browsers/chromium'
            browser = p.chromium.launch(**kw)
            page = browser.new_page()
            page.goto(srv.url)
            page.wait_for_load_state('load')
            page.evaluate("""([b, r, s]) => fetch('/api/bench/start', {method: 'POST',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({burst: b, rate: r, seconds: s})})""",
                          [burst, rate, seconds])
            # attesa a interrogazioni: wait_for_function usa eval() nella pagina, che la CSP (senza 'unsafe-eval') blocca a ragione
            res, t_limit = None, time.time() + seconds + 60
            while res is None and time.time() < t_limit:
                time.sleep(0.2)
                res = page.evaluate('window.__result')
            if res is None:
                raise RuntimeError('la pagina non ha prodotto il risultato nel tempo previsto')
            try:
                res['js_heap_mb'] = page.evaluate('performance.memory ? performance.memory.usedJSHeapSize/1048576 : null')
            except Exception:
                res['js_heap_mb'] = None
            res['browser'] = browser.version
            browser.close()
    finally:
        srv.stop()
    res['wall_s'] = round(time.time() - t0, 2)
    res['python_cpu_s'] = round(sum(proc.cpu_times()[:2]) - cpu0, 2)
    res['params'] = {'burst': burst, 'rate': rate, 'seconds': seconds, 'channel': channel}
    res['system'] = f'{platform.system()} {platform.release()} / Python {platform.python_version()}'
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--burst', type=int, default=5000)
    ap.add_argument('--rate', type=float, default=10.0)
    ap.add_argument('--seconds', type=float, default=10.0)
    ap.add_argument('--channel', default=None)
    ap.add_argument('--headed', action='store_true')
    a = ap.parse_args()
    res = run(a.burst, a.rate, a.seconds, a.channel, a.headed)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f'p1_sse_{platform.system().lower()}.json'
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(res, indent=2, ensure_ascii=False))
    print('scritto', out)


if __name__ == '__main__':
    main()
