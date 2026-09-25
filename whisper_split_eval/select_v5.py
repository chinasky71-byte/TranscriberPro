"""
Selezione della prova v5 (decision_rule_v5.py): 5 film (<=110 min) + 3 episodi con audio e sub inglesi
incorporati + 1 CONTROLLO con audio italiano (nessun sub necessario), seme 20260928. Titoli e serie della v4 e
dei banchi precedenti esclusi. Scrive work_full5/selection_v5.json (campione congelato).
Uso: set PYTHONIOENCODING=utf-8 & ..\venv\Scripts\python.exe select_v5.py [--dry-run]
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

import select_full as SF

WORK = SF.HERE / 'work_full5'
SEED = 20260928
FILMS_FROM = ('Y:', 'W:', 'Y:', 'W:', 'Y:')
N_EPISODES = 3
SF.FILM_MAX = 110
SF.PREVIOUS_TITLES = SF.PREVIOUS_TITLES + ('hypnotic', 'rappaport', 'paddington in peru', 'robert the bruce',
                                           'tempest', 'under the banner of heaven')


def pick_control(root, rng, taken, words):
    base = Path(root + '/')
    dirs = sorted(p for p in base.iterdir() if p.is_dir())
    rng.shuffle(dirs)
    tries = 0
    for d in dirs:
        if d.name in taken or SF.is_excluded(d.name, words):
            continue
        m = re.search(r'\((\d{4})\)', d.name)
        if not m or not (SF.YEAR_RANGE[0] <= int(m.group(1)) <= SF.YEAR_RANGE[1]):
            continue
        vids = SF.videos_in(d, 0)
        if not vids:
            continue
        v = max(vids, key=lambda p: p.stat().st_size)
        tries += 1
        info = SF.probe(v)
        ok = bool(info) and 70 <= info['duration'] / 60 <= 110 and any(a['lang'] in ('ita', 'it') for a in info['audio'])
        print(f"   {'OK ' if ok else 'no '} {d.name[:50]} | {(info or {}).get('duration', 0) / 60:.0f} min | "
              f"audio {[a['lang'] for a in (info or {}).get('audio', [])]}")
        if ok:
            aud = next(a for a in info['audio'] if a['lang'] in ('ita', 'it'))
            return {'kind': 'controllo', 'title': d.name, 'file': str(v), 'duration': info['duration'],
                    'audio_index': aud['index'], 'sub_index': None, 'sub': {'frames': 0}}
        if tries >= 80:
            break
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    sel_path = WORK / 'selection_v5.json'
    if sel_path.exists() and not a.dry_run:
        print("selection_v5.json esiste gia': campione congelato.")
        return 0
    rng = random.Random(SEED)
    words = SF.excluded_words()
    print('titoli/serie esclusi:', sorted(words))
    items, taken = [], set()
    for root in FILMS_FROM:
        print(f"\nFilm da {root}")
        it = SF.pick(root, 'film', rng, taken, words, print)
        if it:
            taken.add(it['title']); items.append(it)
    for i in range(N_EPISODES):
        print(f"\nEpisodio {i + 1} da V:")
        it = SF.pick('V:', 'serie', rng, taken, words, print)
        if it:
            taken.add(it['title']); items.append(it)
    print("\nControllo italiano da W:")
    ctl = pick_control('W:', rng, taken, words)
    if ctl:
        items.append(ctl)
    for k, it in enumerate(items):
        it['id'] = f"{k + 1:02d}-" + re.sub(r'[^A-Za-z0-9]+', '-', it['title']).strip('-').lower()[:50]
    print('\n=== CAMPIONE ===')
    for it in items:
        print(f"  {it['id']:50s} {it['kind']:9s} {it['duration'] / 60:5.0f} min audio#{it['audio_index']} sub#{it['sub_index']}")
    if not a.dry_run:
        WORK.mkdir(parents=True, exist_ok=True)
        sel_path.write_text(json.dumps({'seed': SEED, 'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
    en = [i for i in items if i['kind'] != 'controllo']
    return 0 if len(en) >= 7 and ctl else 1


if __name__ == '__main__':
    sys.exit(main())
