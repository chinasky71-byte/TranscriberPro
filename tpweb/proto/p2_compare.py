# -*- coding: utf-8 -*-
"""Fase 2: confronta le schermate Qt e web (stessi stati, stesse scale) con il criterio approvato: SSIM della schermata intera e per pannello.
Uso:  python tpweb/proto/p2_compare.py --qt results/p2_qt_windows --web results/p2_web_windows [--json out.json]
SSIM su grigio, finestra uniforme 7x7 (come la misura P2b-bis). Obiettivi: schermata >= 0,985 a 100% e 125%, >= 0,97 a 150%;
forme <= 1% di pixel diversi (soglia 24/255 per pixel, ignorando il testo: solo come dato qui)."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

THRESH = 24


def gray(path):
    return np.asarray(Image.open(path).convert('L'), dtype=np.float64)


def box_mean(a, k=7):
    c = np.cumsum(np.cumsum(np.pad(a, ((1, 0), (1, 0))), axis=0), axis=1)
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s / (k * k)


def ssim(a, b, k=7):
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ma, mb = box_mean(a, k), box_mean(b, k)
    va, vb = box_mean(a * a, k) - ma * ma, box_mean(b * b, k) - mb * mb
    cov = box_mean(a * b, k) - ma * mb
    m = ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))
    return float(m.mean())


def diff_pct(a, b):
    return float((np.abs(a - b) > THRESH).mean() * 100)


def compare(qt_png, web_png, regions):
    a, b = gray(qt_png), gray(web_png)
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    a, b = a[:h, :w], b[:h, :w]
    out = {'size_qt': list(gray(qt_png).shape[::-1]), 'size_web': list(gray(web_png).shape[::-1]), 'ssim': round(ssim(a, b), 4),
           'diff_pct': round(diff_pct(a, b), 3), 'regions': {}}
    dpr = w / 1400.0
    for name, (x, y, ww, hh) in regions.items():
        x0, y0, x1, y1 = int(x * dpr), int(y * dpr), int((x + ww) * dpr), int((y + hh) * dpr)
        ra, rb = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
        if ra.shape[0] > 8 and ra.shape[1] > 8:
            out['regions'][name] = {'ssim': round(ssim(ra, rb), 4), 'diff_pct': round(diff_pct(ra, rb), 3)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--qt', required=True)
    ap.add_argument('--web', required=True)
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    res = {}
    for sdir in sorted(Path(a.qt).iterdir()):
        if not sdir.is_dir():
            continue
        for png in sorted(sdir.glob('*.png')):
            web = Path(a.web) / sdir.name / png.name
            if not web.exists():
                continue
            g = json.loads(png.with_suffix('.json').read_text(encoding='utf-8'))
            names = {}
            for k, v in g['widgets'].items():
                n = k.split('#')[0]
                if n in ('miniTitleBar', 'mainTabBar', 'leftPanel', 'centerPanel', 'rightPanel'):
                    names[n] = [i / (g.get('dpr') or 1) if False else i for i in v]
            res[f'{sdir.name}/{png.stem}'] = compare(png, web, names)
            r = res[f'{sdir.name}/{png.stem}']
            print(f"{sdir.name:>5} {png.stem:<18} SSIM {r['ssim']:.4f}  diff {r['diff_pct']:5.2f}%  " +
                  '  '.join(f"{k}={v['ssim']:.3f}" for k, v in r['regions'].items()))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
