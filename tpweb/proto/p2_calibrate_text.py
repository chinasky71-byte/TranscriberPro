# -*- coding: utf-8 -*-
"""P2(b) v2: il testo in CSS puo' arrivare vicino a quello di Qt? Calibrazione per scansione di peso, dimensione, spaziatura e posizione.

La verita' e' la schermata di Qt gia' catturata su Windows (results/pixel_windows/<scala>/qt.png, prodotta da p1_pixel.py): il
tema vero, il font vero, il sistema vero. Per ogni elemento di testo (titolo, due pulsanti) si fa una discesa per coordinate sui
parametri CSS (peso, dimensione, letter-spacing, spostamento orizzontale) minimizzando la frazione di pixel diversi (soglia 24)
nel rettangolo dell'elemento, poi si riporta il totale prima/dopo. Risponde alla domanda: «il 3% residuo e' calibrabile verso 1%,
oppure e' il rasterizzatore (antialiasing/gamma) e allora serve un criterio diverso per il testo?».

Uso (WINDOWS, stesso venv usa e getta di P1):  python p2_calibrate_text.py [--channel msedge] [--truth-dir <cartella pixel_windows>]
Scrive results/p2_calibrazione_<sistema>.json e results/p2_calibrazione_<sistema>/<scala>_dopo.png (web calibrato e diff).
v2: la struttura HTML e' IDENTICA a quella di p1_pixel.py (il testo e' figlio diretto del contenitore; la v1 lo metteva dentro uno <span>
e la linea di partenza non era confrontabile: 4,0% invece di 2,8% sugli stessi dati). In piu' prova PROFILI di rendering del testo
(crenatura, text-rendering, posizionamento dei glifi) e segnala i pesi trovati al limite della ricerca (non credibili per il prodotto).
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
SHAPES = {'barra': (16, 104, 296, 14)}   # altezza REALE disegnata da Qt (QProgressBar { height: 14px } vince su 12 px del solo ID)
CAND = {
    'w': [300, 350, 400, 450, 500, 550, 600, 700],
    'fs': [0.97, 0.98, 0.99, 1.0, 1.01, 1.02, 1.03],
    'ls': [-0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4],
    'dx': [x / 2 for x in range(-8, 9)],
    'dy': [y / 2 for y in range(-6, 7)],      # spostamento VERTICALE (v1 non lo cercava: il titolo Qt centra il testo nel suo riquadro)
}


def html(css_extra: str = '') -> str:
    """Stessa struttura di p1_pixel.web_html: il testo e' figlio DIRETTO del contenitore (nessuno <span> intermedio)."""
    from gui.design_tokens import T
    f = base64.b64encode(FONT.read_bytes()).decode()
    return f'''<!doctype html><meta charset="utf-8"><style>
@font-face{{font-family:"Inter Tight";src:url(data:font/ttf;base64,{f}) format("truetype");font-weight:100 900}}
html,body{{margin:0;background:{T.bg_0};color:{T.fg_0};font-family:"Inter Tight","Segoe UI",sans-serif;{css_extra}}}
#w{{position:relative;width:{SIZE[0]}px;height:{SIZE[1]}px;background:{T.bg_0}}}
#w>*{{position:absolute;box-sizing:border-box}}
#titolo{{left:16px;top:12px;width:300px;height:28px;font-size:13px;font-weight:600;padding:2px 0 8px 0;line-height:normal}}
.btn{{display:flex;align-items:center;justify-content:center;border-radius:{T.rad_ctl};font-size:13.333px;border:1px solid}}
#primario{{left:16px;top:52px;width:140px;height:36px;background:{T.bg_2};color:{T.fg_0};border-color:{T.line};font-weight:500}}
#avvia{{left:172px;top:52px;width:140px;height:36px;background:{T.accent};color:{T.on_accent};border-color:{T.accent};font-weight:600}}
#barra{{left:16px;top:104px;width:296px;height:14px;background:{T.bg_3};border-radius:6px;overflow:hidden}}
#barra>i{{display:block;height:100%;width:40%;background:{T.accent};border-radius:6px}}
</style><div id="w"><div id="titolo">Coda di elaborazione</div><div class="btn" id="primario">Aggiungi file</div>
<div class="btn" id="avvia">Avvia</div><div id="barra"><i></i></div></div>'''


# profili di rendering: (nome, argomenti del browser, CSS globale aggiuntivo)
PROFILES = [
    ('predefinito', [], ''),
    ('crenatura_off', [], 'font-kerning:none;font-feature-settings:"kern" 0;'),
    ('text_geometricPrecision', [], 'text-rendering:geometricPrecision;'),
    ('text_optimizeSpeed', [], 'text-rendering:optimizeSpeed;'),
    ('glifi_a_pixel_interi', ['--disable-font-subpixel-positioning'], ''),
    ('hinting_none', ['--font-render-hinting=none'], ''),
]
WEIGHT_EDGES = (min(CAND['w']), max(CAND['w']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--channel', default=None)
    ap.add_argument('--truth-dir', default=str(RESULTS / 'pixel_windows'))
    ap.add_argument('--scale', type=float, nargs='+', default=[1.0, 1.25, 1.5])
    ap.add_argument('--profili', nargs='+', default=[p[0] for p in PROFILES])
    a = ap.parse_args()
    import numpy as np
    from PIL import Image
    from playwright.sync_api import sync_playwright
    sysname = platform.system().lower()
    outdir = RESULTS / f'p2_calibrazione_{sysname}'
    outdir.mkdir(parents=True, exist_ok=True)
    res = {'versione': 2, 'system': f'{platform.system()} {platform.release()}', 'soglia_per_pixel': THRESH, 'profili': {}}
    with sync_playwright() as p:
        for pname, bargs, css_extra in [x for x in PROFILES if x[0] in a.profili]:
            kw = {'headless': True, 'args': ['--no-sandbox', '--force-color-profile=srgb', *bargs]}
            if a.channel:
                kw['channel'] = a.channel
            elif os.path.exists('/opt/pw-browsers/chromium'):
                kw['executable_path'] = '/opt/pw-browsers/chromium'
            br = p.chromium.launch(**kw)
            res['profili'][pname] = {'argomenti_browser': bargs, 'css': css_extra, 'scale': {}}
            for sc in a.scale:
                truth = np.asarray(Image.open(Path(a.truth_dir) / str(sc) / 'qt.png').convert('RGB')).astype(int)
                pg = br.new_page(viewport={'width': SIZE[0], 'height': SIZE[1]}, device_scale_factor=sc)
                pg.set_content(html(css_extra))
                pg.evaluate('document.fonts.ready')

                def shot():
                    png = pg.screenshot(clip={'x': 0, 'y': 0, 'width': SIZE[0], 'height': SIZE[1]})
                    return np.asarray(Image.open(io.BytesIO(png)).convert('RGB')).astype(int)

                def score(arr, rect):
                    x0, y0, x1, y1 = [int(round(v * sc)) for v in (rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3])]
                    t, c = truth[y0:y1, x0:x1], arr[y0:y1, x0:x1]
                    hh, ww = min(t.shape[0], c.shape[0]), min(t.shape[1], c.shape[1])
                    return float((np.abs(t[:hh, :ww] - c[:hh, :ww]).max(axis=2) > THRESH).mean() * 100)

                def apply(eid, prm, w0, fs0):
                    dx, dy = prm['dx'], prm['dy']
                    if eid == 'titolo':          # testo allineato in alto: dx = rientro, dy = padding superiore (2 px nel QSS)
                        pad = f"{max(2 + dy, 0)}px 0 {max(8 - dy, 0)}px 0"
                    else:                        # testo centrato dal flex: uno spostamento d = padding asimmetrico di 2d
                        pad = f"{max(2 * dy, 0)}px {max(-2 * dx, 0)}px {max(-2 * dy, 0)}px {max(2 * dx, 0)}px"
                    pg.evaluate("""([i, w, fs, ls, dx, pad]) => { const e = document.getElementById(i);
                        e.style.fontWeight = w; e.style.fontSize = fs; e.style.letterSpacing = ls;
                        e.style.padding = pad; e.style.textIndent = i === 'titolo' ? dx : '0'; }""",
                                [eid, str(prm['w']), f"{fs0 * prm['fs']:.4f}px", f"{prm['ls']}px", f"{dx}px", pad])

                for n, e in ELEMENTS.items():
                    apply(n, {'w': e[2], 'fs': 1.0, 'ls': 0.0, 'dx': 0.0, 'dy': 0.0}, e[2], e[3])
                first = shot()
                before = float((np.abs(truth - first).max(axis=2) > THRESH).mean() * 100) if truth.shape == first.shape else None
                sc_res = {'totale_prima_pct': round(before, 3) if before is not None else None, 'elementi': {}}
                best_all = {}
                for n, (rect, text, w0, fs0) in ELEMENTS.items():
                    cur = {'w': w0, 'fs': 1.0, 'ls': 0.0, 'dx': 0.0, 'dy': 0.0}
                    apply(n, cur, w0, fs0)
                    s0 = score(shot(), rect)
                    best = s0
                    for _ in range(2):
                        for k in ('w', 'fs', 'ls', 'dx', 'dy'):
                            for v in CAND[k]:
                                trial = dict(cur, **{k: v})
                                apply(n, trial, w0, fs0)
                                sc_ = score(shot(), rect)
                                if sc_ < best - 1e-9:
                                    best, cur = sc_, trial
                            apply(n, cur, w0, fs0)
                    best_all[n] = cur
                    sc_res['elementi'][n] = {
                        'prima_pct': round(s0, 2), 'dopo_pct': round(best, 2), 'peso_qss_originale': w0,
                        'migliori': {'peso': cur['w'], 'dimensione_x': cur['fs'], 'letter_spacing_px': cur['ls'], 'spostamento_px': cur['dx'], 'spostamento_verticale_px': cur['dy']},
                        'peso_al_limite_della_ricerca': cur['w'] in WEIGHT_EDGES,
                        'spostamento_anomalo': abs(cur['dx']) >= 2.0 or abs(cur['dy']) >= 2.0}
                for n, e in ELEMENTS.items():
                    apply(n, best_all[n], e[2], e[3])
                final = shot()
                if truth.shape == final.shape:
                    d = np.abs(truth - final).max(axis=2)
                    sc_res['totale_dopo_pct'] = round(float((d > THRESH).mean() * 100), 3)
                    sc_res['barra_pct'] = round(score(final, SHAPES['barra']), 3)
                    Image.fromarray(np.where(d[..., None] > THRESH, [255, 0, 80], truth // 3).astype('uint8')).save(outdir / f'{pname}_{sc}_dopo_diff.png')
                    Image.fromarray(final.astype('uint8')).save(outdir / f'{pname}_{sc}_dopo_web.png')
                res['profili'][pname]['scale'][str(sc)] = sc_res
                pg.close()
            br.close()
    tot = {pn: round(sum(v.get('totale_dopo_pct', 0) for v in pv['scale'].values()) / max(len(pv['scale']), 1), 3)
           for pn, pv in res['profili'].items()}
    res['riassunto_totale_dopo_medio_pct'] = tot
    res['profilo_migliore'] = min(tot, key=tot.get) if tot else None
    out = RESULTS / f'p2_calibrazione_{sysname}.json'
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'riassunto': tot, 'migliore': res['profilo_migliore']}, indent=2, ensure_ascii=False))
    print('scritto', out)


if __name__ == '__main__':
    main()
