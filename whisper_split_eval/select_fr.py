"""
Selezione dei film FRANCESI (lingua originale francese in Radarr, audio francese + sottotitolo francese di testo non
forzato) per la prova dello split per frasi in francese (piano_split_frasi_fr_de, 28/09/2026).
Set di TARATURA = 3 film gia' usati nel banco ASR francese (mt_eval/asr_fr): Intouchables, Les Misérables, Les
Orphelins. Set di CONFERMA = i primi 9 degli altri francesi originali utilizzabili, in ordine casuale (seme 20261001).
Scrive work_fr/selection_fr.json.
Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe select_fr.py [--dry-run]
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

import select_full as SF

WORK = SF.HERE / 'work_fr'
SEED = 20261001
RADARR = Path(r"C:\Users\fran_\AppData\Local\Temp\claude\C--Users-fran--Desktop-Transcriber-Pro"
              r"\c325e2fc-38ef-4a64-831a-e3dea60ac106\scratchpad\radarr_movies.json")
MAPS = (('/srv/dev-disk-by-uuid-9fbd521b-2449-4c25-ad0e-dd7d6ff2503f/FILM_2', 'Y:'),
        ('/srv/dev-disk-by-uuid-28545a9f-6ad6-4923-aefd-4981efe1d441/FILM', 'W:'))
TUNING = ('intouchables', 'misérables', 'orphans')      # nomi di cartella (inglesi) dei 3 film di taratura


def usable_fr(info):
    if not info or not (60 <= info['duration'] / 60 <= 150):
        return None
    fre = [a for a in info['audio'] if a['lang'] in ('fre', 'fra', 'fr')]
    subs = [s for s in info['subs'] if s['lang'] in ('fre', 'fra', 'fr')
            and s['codec'] in ('subrip', 'srt', 'ass', 'mov_text')
            and not any(k in s['title'].lower() for k in ('forced', 'forcé', 'force', 'forzat'))]
    if not fre or not subs:
        return None
    sub = max(subs, key=lambda s: s['frames'])
    if sub['frames'] and sub['frames'] < 600:
        return None
    return {'audio_index': fre[0]['index'], 'sub_index': sub['index'], 'sub': sub}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    sel_path = WORK / 'selection_fr.json'
    if sel_path.exists() and not a.dry_run:
        print("selection_fr.json esiste gia': campione congelato.")
        return 0
    movies = json.loads(RADARR.read_text(encoding='utf-8'))
    tuning, conf = [], []
    for m in sorted(movies, key=lambda x: x['title']):
        if (m.get('originalLanguage') or {}).get('name') != 'French' or not m.get('hasFile'):
            continue
        p = (m.get('movieFile') or {}).get('path') or ''
        for src, dst in MAPS:
            p = p.replace(src, dst)
        p = Path(p.replace('/', '\\'))
        info = SF.probe(p)
        u = usable_fr(info)
        print(f"  {'OK ' if u else 'no '} {m['title'][:45]:45s} {p.parent.name[:45]}")
        if not u:
            continue
        it = {'kind': 'film', 'title': m['title'], 'file': str(p), 'duration': info['duration'], **u}
        (tuning if any(k in p.parent.name.lower() for k in TUNING) else conf).append(it)
    random.Random(SEED).shuffle(conf)
    conf = conf[:9]          # 8 di conferma come per l'italiano + 1 di riserva (file con sottotitolo non valido)
    items = tuning + conf
    for k, it in enumerate(items):
        it['id'] = f"{k + 1:02d}-" + re.sub(r'[^A-Za-z0-9]+', '-', it['title']).strip('-').lower()[:50]
        it['set'] = 'taratura' if k < len(tuning) else 'conferma'
    print('\n=== CAMPIONE ===')
    for it in items:
        print(f"  {it['id']:45s} {it['set']:9s} {it['duration'] / 60:5.0f} min audio#{it['audio_index']} "
              f"sub#{it['sub_index']} {it['sub']['title'][:20]!r} ({it['sub']['frames']} cue)")
    if not a.dry_run:
        WORK.mkdir(parents=True, exist_ok=True)
        sel_path.write_text(json.dumps({'seed': SEED, 'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0 if len(tuning) == 3 and len(conf) >= 6 else 1


if __name__ == '__main__':
    sys.exit(main())
