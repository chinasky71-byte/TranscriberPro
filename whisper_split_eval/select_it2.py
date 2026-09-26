"""
Selezione dei file ITALIANI (audio italiano + sottotitolo italiano di testo incorporato) per la prova dello
split per frasi in italiano. Seme 20260929. 11 file: i primi 3 = set di TARAGGIA (le regole italiane si
sviluppano guardando i loro dati), gli altri 8 = set di CONFERMA (mai guardati prima del congelamento della
regola). Titoli/serie gia' usati in qualsiasi banco precedente esclusi (inglese v4/v5 compresi).
Scrive work_it2/selection_it2.json.
Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe select_it.py [--dry-run]
"""
import argparse
import json
import random
import re
import sys

import select_full as SF

WORK = SF.HERE / 'work_it2'
SEED = 20260930
FILMS_FROM = ('Y:', 'W:', 'Y:', 'W:', 'Y:')
N_EPISODES = 3
SF.FILM_MAX = 110
SF.PREVIOUS_TITLES = SF.PREVIOUS_TITLES + (
    'hypnotic', 'rappaport', 'paddington in peru', 'robert the bruce', 'tempest', 'under the banner of heaven',
    'yes day', 'predators', 'nobody', 'io sono nessuno', 'resident evil degeneration', 'accident man', 'receiver',
    'andor', 'olive kitteridge', 'wristcutters',
    'casper', 'devil wears prada', 'bad guy', 'sixth sense', 'hangover', 'way way back', 'margin call',
    'requiem for a dream', 'sono qui per caos', 'grey', 'boba fett')


def usable_it(info, lo, hi):
    if not info or not (lo <= info['duration'] / 60 <= hi):
        return None
    ita = [a for a in info['audio'] if a['lang'] in ('ita', 'it')]
    subs = [s for s in info['subs'] if s['lang'] in ('ita', 'it') and s['codec'] in ('subrip', 'srt', 'ass', 'mov_text')
            and 'forced' not in s['title'].lower() and 'forzat' not in s['title'].lower()]
    if not ita or not subs:
        return None
    sub = max(subs, key=lambda s: s['frames'])
    if sub['frames'] < 600:
        return None
    return {'audio_index': ita[0]['index'], 'sub_index': sub['index'], 'sub': sub}


SF.usable = usable_it


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    sel_path = WORK / 'selection_it2.json'
    if sel_path.exists() and not a.dry_run:
        print("selection_it2.json esiste gia': campione congelato.")
        return 0
    rng = random.Random(SEED)
    words = SF.excluded_words()
    items, taken = [], set()
    order = [('film', FILMS_FROM[0]), ('film', FILMS_FROM[1]), ('serie', 'V:')]
    order += [('film', r) for r in FILMS_FROM[2:]] + [('serie', 'V:')] * (N_EPISODES - 1)
    for kind, root in order:
        print(f"\n{kind} da {root}")
        it = SF.pick(root, kind, rng, taken, words, print)
        if it:
            taken.add(it['title'])
            items.append(it)
    for k, it in enumerate(items):
        it['id'] = f"{k + 1:02d}-" + re.sub(r'[^A-Za-z0-9]+', '-', it['title']).strip('-').lower()[:50]
        it['set'] = 'conferma'
    print('\n=== CAMPIONE ===')
    for it in items:
        print(f"  {it['id']:52s} {it['set']:9s} {it['kind']:5s} {it['duration'] / 60:5.0f} min audio#{it['audio_index']} "
              f"sub#{it['sub_index']} ({it['sub']['frames']} cue)")
    if not a.dry_run:
        WORK.mkdir(parents=True, exist_ok=True)
        sel_path.write_text(json.dumps({'seed': SEED, 'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0 if len(items) >= 7 else 1


if __name__ == '__main__':
    sys.exit(main())
