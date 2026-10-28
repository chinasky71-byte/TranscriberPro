# -*- coding: utf-8 -*-
"""Confronto di GEOMETRIA (non di pixel) tra le scatole dei widget Qt e quelle della pagina, dalle stesse catture (p2_qt_capture.py / p2_web_capture.py).
Indipendente dal rasterizzatore del testo: dice di quanti pixel una scatola e' fuori posto. Uso:
    python tpweb/proto/p2_geometry.py --qt <cartella Qt> --web <cartella web> [--scale 1.0] [--state righe]"""
import argparse
import json
from pathlib import Path

PAIRS = {'miniTitleBar': 'titlebar', 'mainTabBar': 'tabbar', 'leftPanel': 'leftPanel', 'centerPanel': 'centerPanel', 'rightPanel': 'rightPanel', 'fileList': 'fileList',
         'startButton': 'start', 'stopButton': 'stop', 'modernProgress': 'progress', 'titleBarMark': 'titleBarMark', 'titleBarBrand': 'titleBarBrand',
         'titleBarSep': 'titleBarSep', 'titleBarSubtitle': 'titleBarSubtitle', 'statusPill': 'statusPill', 'titleBarToolsBtn': 'titleBarToolsBtn',
         'titleBarSyncBtn': 'titleBarSyncBtn', 'titleBarSettingsBtn': 'titleBarSettingsBtn', 'settingsHeader': 'settingsHeader',
         'settingsSidebar': 'settingsSidebar', 'settingsContentWrap': 'settingsContentWrap', 'collapsibleCard': 'scannerCard',
         'defaultsSummary': 'defaultsSummary', 'modernCheckbox': 'modernCheckbox'}
MULTI = {'primaryButton': ['add-files', 'add-folder', 'clear']}      # piu' widget Qt con lo stesso nome, nell'ordine
ALIASES = {'titlebar': 'miniTitleBar', 'tabbar': 'mainTabBar'}


def compare(qt_json: dict, web_json: dict):
    qt = {}
    for k, v in qt_json.get('widgets', {}).items():
        qt.setdefault(k.split('#')[0], v)
    rows = []
    for qn, wn in PAIRS.items():
        if qn in qt and wn in web_json.get('boxes', {}):
            q, w = qt[qn], web_json['boxes'][wn]
            rows.append((qn, q, [round(x) for x in w], [round(w[i] - q[i]) for i in range(4)]))
    for qn, names in MULTI.items():
        found = [v for k, v in qt_json.get('widgets', {}).items() if k.split('#')[0] == qn]
        for q, wn in zip(found, names):
            if wn in web_json.get('boxes', {}):
                w = web_json['boxes'][wn]
                rows.append((f'{qn}:{wn}', q, [round(x) for x in w], [round(w[i] - q[i]) for i in range(4)]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--qt', required=True)
    ap.add_argument('--web', required=True)
    ap.add_argument('--scale', default='1.0')
    ap.add_argument('--state', default='righe')
    a = ap.parse_args()
    q = json.loads((Path(a.qt) / a.scale / (a.state + '.json')).read_text(encoding='utf-8'))
    w = json.loads((Path(a.web) / a.scale / (a.state + '.json')).read_text(encoding='utf-8'))
    print(f'{"widget":22} {"Qt (x,y,w,h)":26} {"web":26} differenza (x,y,w,h)')
    for name, qb, wb, d in compare(q, w):
        flag = '' if max(abs(x) for x in d) <= 1 else '  <--'
        print(f'{name:22} {str(qb):26} {str(wb):26} {d}{flag}')


if __name__ == '__main__':
    main()
