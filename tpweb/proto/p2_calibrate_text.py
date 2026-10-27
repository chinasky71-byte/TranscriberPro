# -*- coding: utf-8 -*-
"""P2(b): il testo in CSS puo' arrivare vicino a quello di Qt? Calibrazione per scansione di peso, dimensione, spaziatura e posizione.

La verita' e' la schermata di Qt gia' catturata su Windows (results/pixel_windows/<scala>/qt.png, prodotta da p1_pixel.py): il
tema vero, il font vero, il sistema vero. Per ogni elemento di testo (titolo, due pulsanti) si fa una discesa per coordinate sui
parametri CSS (peso, dimensione, letter-spacing, spostamento orizzontale) minimizzando la frazione di pixel diversi (soglia 24)
nel rettangolo dell'elemento, poi si riporta il totale prima/dopo. Risponde alla domanda: «il 3% residuo e' calibrabile verso 1%,
oppure e' il rasterizzatore (antialiasing/gamma) e allora serve un criterio diverso per il testo?».

Uso (WINDOWS, stesso venv usa e getta di P1):  python p2_calibrate_text.py [--channel msedge] [--truth-dir <cartella pixel_windows>]
Scrive results/p2_calibrazione_<sistema>.json e results/p2_calibrazione_<sistema>/<scala>_dopo.png (web calibrato e diff).
Nel cloud (Linux) si puo' provare solo la meccanica: la verita' Windows contro Chromium Linux non e' una misura valida.
"""
import argparse
import base64
import io
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RESULTS = Path(__file__).resolve().parent / 'results'
FONT = ROOT / 'assets' / 'fonts' / 'InterTight[wght].ttf'
THRESH = 24
SIZE = (360, 150)        # stessi valori di p1_pixel.py
# elemento: (rettangolo x, y, w, h in px CSS, testo, peso originale del QSS, dimensione originale in px)
ELEMENTS = {
    'titolo': ((16, 12, 300, 28), 'Coda di elaborazione', 600, 13.0),
    'primario': ((16, 52, 140, 36), 'Aggiungi file', 500, 13.333),
    'avvia': ((172, 52, 140, 36), 'Avvia', 600, 13.333),
}
SHAPES = {'barra': (16, 104, 296, 12)}
CAND = {
    'w': [300, 350, 400, 450, 500, 550, 600, 700],
    'fs': [0.97, 0.98, 0.99, 1.0, 1.01, 1.02, 1.03],
    'ls': [-0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4],
    'dx': [x / 2 for x in range(-8, 9)],
}


def html() -> str:
    from gui.design_tokens import T
    f = base64.b64encode(FONT.read_bytes()).decode()
    return f'''<!doctype html><meta charset="utf-8"><style>
@font-face{{font-family:"Inter Tight";src:url(data:font/ttf;base64,{f}) format("truetype");font-weight:100 900}}
html,body{{margin:0;background:{T.bg_0};color:{T.fg_0};font-family:"Inter Tight","Segoe UI",sans-serif}}
#w{{position:relative;width:{SIZE[0]}px;height:{SIZE[1]}px;background:{T.bg_0}}}
#w>*{{position:absolute;box-sizing:border-box}}
.t{{position:relative;left:var(--dx,0px);font-weight:var(--w);letter-spacing:var(--ls,0px);font-size:var(--fs);white-space:nowrap}}
#titolo{{left:16px;top:12px;width:300px;height:28px;padding:2px 0 8px 0;line-height:normal}}
.btn{{display:flex;align-items:center;justify-content:center;border-radius:{T.rad_ctl};border:1px solid}}
#primario{{left:16px;top:52px;width:140px;height:36px;background:{T.bg_2};color:{T.fg_0};border-color:{T.line}}}
#avvia{{left:172px;top:52px;width:140px;height:36px;background:{T.accent};color:{T.on_accent};border-color:{T.accent}}}
#barra{{left:16px;top:104px;width:296px;height:12px;background:{T.bg_3};border-radius:6px;overflow:hidden}}
#barra>i{{display:block;height:100%;width:40%;background:{T.accent};border-radius:6px}}
</style><div id="w"><div id="titolo"><span class="t">Coda di elaborazione</span></div>
<div class="btn" id="primario"><span class="t">Aggiungi file</span></div>
<div class="btn" id="avvia"><span class="t">Avvia</span></div><div id="barra"><i></i></div></div>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--channel', default=None)
    ap.add_argument('--truth-dir', default=str(RESULTS / 'pixel_windows'))
    ap.add_argument('--scale', type=float, nargs='+', default=[1.0, 1.25, 1.5])
    a = ap.parse_args()
    import numpy as np
    from PIL import Image
    from playwright.sync_api import sync_playwright
    sysname = platform.system().lower()
    outdir = RESULTS / f'p2_calibrazione_{sysname}'
    outdir.mkdir(parents=True, exist_ok=True)
    res = {'system': f'{platform.system()} {platform.release()}', 'soglia_per_pixel': THRESH, 'scale': {}}
    with sync_playwright() as p:
        kw = {'headless': True, 'args': ['--no-sandbox', '--force-color-profile=srgb']}
        if a.channel:
            kw['channel'] = a.channel
        elif os.path.exists('/opt/pw-browsers/chromium'):
            kw['executable_path'] = '/opt/pw-browsers/chromium'
        br = p.chromium.launch(**kw)
        for sc in a.scale:
            truth_path = Path(a.truth_dir) / str(sc) / 'qt.png'
            truth = np.asarray(Image.open(truth_path).convert('RGB')).astype(int)
            pg = br.new_page(viewport={'width': SIZE[0], 'height': SIZE[1]}, device_scale_factor=sc)
            pg.set_content(html())
            pg.evaluate('document.fonts.ready')

            def shot():
                png = pg.screenshot(clip={'x': 0, 'y': 0, 'width': SIZE[0], 'height': SIZE[1]})
                return np.asarray(Image.open(io.BytesIO(png)).convert('RGB')).astype(int)

            def region(arr, rect):
                x, y, w, h = [int(round(v * sc)) for v in (rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3])]
                return arr[y:h, x:w]

            def score(arr, rect):
                t, c = region(truth, rect), region(arr, rect)
                hh, ww = min(t.shape[0], c.shape[0]), min(t.shape[1], c.shape[1])
                return float((np.abs(t[:hh, :ww] - c[:hh, :ww]).max(axis=2) > THRESH).mean() * 100)

            def setp(eid, k, v):
                pg.evaluate("([i,k,v]) => document.querySelector('#'+i+' .t').style.setProperty(k, v)", [eid, k, v])

            def apply(eid, params, base_fs):
                setp(eid, '--w', str(params['w']))
                setp(eid, '--fs', f"{base_fs * params['fs']:.4f}px")
                setp(eid, '--ls', f"{params['ls']}px")
                setp(eid, '--dx', f"{params['dx']}px")

            # stato iniziale = CSS originale del prototipo P1
            base_params = {n: {'w': e[2], 'fs': 1.0, 'ls': 0.0, 'dx': 0.0} for n, e in ELEMENTS.items()}
            for n, e in ELEMENTS.items():
                apply(n, base_params[n], e[3])
            first = shot()
            before_total = float((np.abs(truth - first).max(axis=2) > THRESH).mean() * 100) if truth.shape == first.shape else None
            sc_res = {'totale_prima_pct': round(before_total, 3) if before_total is not None else None, 'elementi': {}}
            best_all = {}
            for n, (rect, text, w0, fs0) in ELEMENTS.items():
                cur = dict(base_params[n])
                apply(n, cur, fs0)
                s0 = score(shot(), rect)
                best = s0
                for _ in range(2):                                   # due giri: i parametri si influenzano
                    for k in ('w', 'fs', 'ls', 'dx'):
                        for v in CAND[k]:
                            trial = dict(cur, **{k: v})
                            apply(n, trial, fs0)
                            s = score(shot(), rect)
                            if s < best - 1e-9:
                                best, cur = s, trial
                        apply(n, cur, fs0)
                best_all[n] = cur
                sc_res['elementi'][n] = {'prima_pct': round(s0, 2), 'dopo_pct': round(best, 2),
                                         'migliori': {'peso': cur['w'], 'dimensione_x': cur['fs'], 'letter_spacing_px': cur['ls'],
                                                      'spostamento_px': cur['dx']}, 'peso_qss_originale': w0}
            for n, e in ELEMENTS.items():
                apply(n, best_all[n], e[3])
            final = shot()
            if truth.shape == final.shape:
                d = np.abs(truth - final).max(axis=2)
                sc_res['totale_dopo_pct'] = round(float((d > THRESH).mean() * 100), 3)
                sc_res['barra_pct'] = round(score(final, SHAPES['barra']), 3)
                Image.fromarray(np.where(d[..., None] > THRESH, [255, 0, 80], truth // 3).astype('uint8')).save(outdir / f'{sc}_dopo_diff.png')
                Image.fromarray(final.astype('uint8')).save(outdir / f'{sc}_dopo_web.png')
            res['scale'][str(sc)] = sc_res
            pg.close()
        br.close()
    out = RESULTS / f'p2_calibrazione_{sysname}.json'
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
