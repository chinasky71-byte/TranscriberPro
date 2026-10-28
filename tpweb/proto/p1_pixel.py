# -*- coding: utf-8 -*-
"""P1(e): quanto e' realistico il «pixel-perfect»? Confronta lo STESSO elemento disegnato da Qt (tema vero dell'app) e da Chromium.

Il lato Qt usa i widget e il tema veri (gui/theme.qss.tpl + design token + Inter Tight caricato da assets/fonts): un titolo di
pannello, due pulsanti (primaryButton, startButton) e la barra modernProgress. Le geometrie le decide Qt; il lato web le riceve
(posizione e dimensione di ogni elemento) e le riproduce con CSS equivalente e lo stesso font. Si confrontano i pixel per regione.

Uso:   python p1_pixel.py [--scale 1.0 1.25 1.5] [--channel msedge]
Scrive results/pixel_<sistema>/<scala>/{qt.png, web.png, diff.png} e results/p1_pixel_<sistema>.json.
Soglia di differenza per pixel: 24/255 sul canale piu' diverso. Il Qt va eseguito sulla piattaforma di destinazione (Windows):
i valori ottenuti su Linux servono solo a provare lo strumento.
"""
import argparse
import base64
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / 'results'
FONT = ROOT / 'assets' / 'fonts' / 'InterTight[wght].ttf'
THRESH = 24


def qt_render(scale: float, outdir: Path) -> dict:
    """In un sottoprocesso (QT_SCALE_FACTOR va fissato prima di QApplication). Scrive qt.png e layout.json."""
    code = r'''
import json, os, sys
sys.path.insert(0, %(root)r)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen" if sys.platform != "win32" else "windows")
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QProgressBar
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtCore import Qt
app = QApplication([]); app.setStyle("Fusion")
QFontDatabase.addApplicationFont(%(font)r)
app.setFont(QFont("Inter Tight", 10))
from gui.theme import build_qss
app.setStyleSheet(build_qss())
w = QWidget(); w.resize(360, 150)
t = QLabel("Coda di elaborazione", w); t.setObjectName("panelTitle"); t.setGeometry(16, 12, 300, 28)
b1 = QPushButton("Aggiungi file", w); b1.setObjectName("primaryButton"); b1.setGeometry(16, 52, 140, 36)
b2 = QPushButton("Avvia", w); b2.setObjectName("startButton"); b2.setGeometry(172, 52, 140, 36)
pb = QProgressBar(w); pb.setObjectName("modernProgress"); pb.setRange(0, 100); pb.setValue(40); pb.setTextVisible(False)
pb.setGeometry(16, 104, 296, 12)
w.show(); app.processEvents()
img = w.grab().toImage()
img.save(%(png)r)
lay = {n: [o.x(), o.y(), o.width(), o.height()] for n, o in (("titolo", t), ("primario", b1), ("avvia", b2), ("barra", pb))}
print(json.dumps({"layout": lay, "size": [w.width(), w.height()], "dpr": img.devicePixelRatio(), "px": [img.width(), img.height()]}))
''' % {'root': str(ROOT), 'font': str(FONT), 'png': str(outdir / 'qt.png')}
    env = dict(os.environ, QT_SCALE_FACTOR=str(scale), QT_ENABLE_HIGHDPI_SCALING='1')
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError('rendering Qt fallito:\n' + r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def web_html(info: dict) -> str:
    sys.path.insert(0, str(ROOT))
    from gui.design_tokens import T
    f = base64.b64encode(FONT.read_bytes()).decode()
    L = info['layout']

    def box(n):
        x, y, w, h = L[n]
        return f'left:{x}px;top:{y}px;width:{w}px;height:{h}px'
    return f'''<!doctype html><meta charset="utf-8"><style>
@font-face{{font-family:"Inter Tight";src:url(data:font/ttf;base64,{f}) format("truetype");font-weight:100 900}}
html,body{{margin:0;background:{T.bg_0};color:{T.fg_0};font-family:"Inter Tight","Segoe UI",sans-serif}}
#w{{position:relative;width:{info['size'][0]}px;height:{info['size'][1]}px;background:{T.bg_0}}}
#w>*{{position:absolute;box-sizing:border-box}}
#t{{{box('titolo')};font-size:13px;font-weight:600;padding:2px 0 8px 0;line-height:normal}}
.btn{{display:flex;align-items:center;justify-content:center;border-radius:{T.rad_ctl};font-size:13.333px;border:1px solid}}
#p{{{box('primario')};background:{T.bg_2};color:{T.fg_0};border-color:{T.line};font-weight:500}}
#a{{{box('avvia')};background:{T.accent};color:{T.on_accent};border-color:{T.accent};font-weight:600}}
#b{{{box('barra')};background:{T.bg_3};border-radius:6px;overflow:hidden}}
#b>i{{display:block;height:100%;width:40%;background:{T.accent};border-radius:6px}}
</style><div id="w"><div id="t">Coda di elaborazione</div><div class="btn" id="p">Aggiungi file</div>
<div class="btn" id="a">Avvia</div><div id="b"><i></i></div></div>'''


def web_render(info: dict, scale: float, png: Path, channel=None):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        kw = {'headless': True, 'args': ['--no-sandbox', '--force-color-profile=srgb']}
        if channel:
            kw['channel'] = channel
        elif os.path.exists('/opt/pw-browsers/chromium'):
            kw['executable_path'] = '/opt/pw-browsers/chromium'
        br = p.chromium.launch(**kw)
        pg = br.new_page(viewport={'width': info['size'][0], 'height': info['size'][1]}, device_scale_factor=scale)
        pg.set_content(web_html(info))
        pg.evaluate('document.fonts.ready')
        pg.screenshot(path=str(png), clip={'x': 0, 'y': 0, 'width': info['size'][0], 'height': info['size'][1]})
        br.close()


def compare(qt_png: Path, web_png: Path, diff_png: Path, layout: dict, scale: float) -> dict:
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(qt_png).convert('RGB')).astype(int)
    b = np.asarray(Image.open(web_png).convert('RGB')).astype(int)
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    a, b = a[:h, :w], b[:h, :w]
    d = np.abs(a - b).max(axis=2)
    Image.fromarray(np.where(d[..., None] > THRESH, [255, 0, 80], (a // 3)).astype('uint8')).save(diff_png)
    out = {'immagine': {'qt': list(a.shape[:2]), 'web': list(b.shape[:2]), 'identiche_dimensioni': a.shape == b.shape or True},
           'totale_pixel_diversi_pct': round(float((d > THRESH).mean() * 100), 3), 'regioni': {}}
    for n, (x, y, ww, hh) in layout.items():
        x0, y0, x1, y1 = [int(round(v * scale)) for v in (x, y, x + ww, y + hh)]
        reg = d[y0:y1, x0:x1]
        out['regioni'][n] = {'pixel_diversi_pct': round(float((reg > THRESH).mean() * 100), 2) if reg.size else None,
                             'diff_medio': round(float(reg.mean()), 2) if reg.size else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scale', type=float, nargs='+', default=[1.0, 1.25, 1.5])
    ap.add_argument('--channel', default=None)
    a = ap.parse_args()
    sysname = platform.system().lower()
    res = {'system': f'{platform.system()} {platform.release()}', 'soglia_per_pixel': THRESH, 'scale': {}}
    for sc in a.scale:
        d = RESULTS / f'pixel_{sysname}' / str(sc)
        d.mkdir(parents=True, exist_ok=True)
        info = qt_render(sc, d)
        web_render(info, sc, d / 'web.png', a.channel)
        res['scale'][str(sc)] = {'qt_px': info['px'], 'dpr_qt': info['dpr'],
                                 **compare(d / 'qt.png', d / 'web.png', d / 'diff.png', info['layout'], sc)}
    out = RESULTS / f'p1_pixel_{sysname}.json'
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
