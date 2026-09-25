"""
Selezione dei 6 file INTERI per la prova v4 (decision_rule_v4.py). Solo CPU/rete.

4 film (Y:, W:) + 2 episodi (V:), seme 20260927, con: audio INGLESE, sottotitolo
inglese di TESTO incorporato (non forced), durata adeguata, titolo non presente
nel banco ASR (asr_eval/work/audit.json) ne' nei controlli precedenti.
Scrive work_full/selection_full.json (campione congelato: non si rifa').

Uso: set PYTHONIOENCODING=utf-8 & ..\\venv\\Scripts\\python.exe select_full.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = HERE / 'work_full'
SEED = 20260927
FILMS_FROM = ('Y:', 'W:', 'Y:', 'W:')
N_EPISODES = 2
FILM_MIN, FILM_MAX = 80, 150          # minuti
EP_MIN, EP_MAX = 35, 75
YEAR_RANGE = (1995, 2025)
VIDEO_EXT = ('.mkv', '.mp4', '.m4v', '.avi')
PREVIOUS_TITLES = ('thirteenth floor', 'lost bus', 'v-h-s', 'v/h/s', 'downsizing', 'matrix reloaded', 'silo',
                   'night manager', 'the pitt')
NO_WINDOW = {'creationflags': 0x08000000} if os.name == 'nt' else {}


def norm(t: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', t.lower()).strip()


def excluded_words():
    words = {norm(w) for w in PREVIOUS_TITLES}
    audit = json.loads((ROOT / 'asr_eval' / 'work' / 'audit.json').read_text(encoding='utf-8'))
    for k in audit['films']:
        words.add(norm(re.sub(r'-\d{4}$', '', k)))
    return {w for w in words if w}


def is_excluded(name: str, words) -> bool:
    n = norm(name)
    return any(w in n for w in words)


def probe(path: Path):
    cmd = ['ffprobe', '-v', 'error', '-show_entries',
           'format=duration:stream=index,codec_type,codec_name:stream_tags=language,title,NUMBER_OF_FRAMES',
           '-of', 'json', str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=120, **NO_WINDOW)
        j = json.loads(r.stdout) if r.returncode == 0 else {}
    except Exception:
        return None
    dur = float((j.get('format') or {}).get('duration') or 0)
    audio, subs = [], []
    for s in j.get('streams', []):
        t = s.get('tags') or {}
        lang = (t.get('language') or '').lower()
        if s.get('codec_type') == 'audio':
            audio.append({'index': s['index'], 'lang': lang})
        elif s.get('codec_type') == 'subtitle':
            title = (t.get('title') or '')
            frames = int(t.get('NUMBER_OF_FRAMES') or 0)
            subs.append({'index': s['index'], 'lang': lang, 'codec': s.get('codec_name'), 'title': title,
                         'frames': frames})
    return {'duration': dur, 'audio': audio, 'subs': subs}


def usable(info, lo, hi):
    if not info:
        return None
    if not (lo <= info['duration'] / 60 <= hi):
        return None
    eng = [a for a in info['audio'] if a['lang'] in ('eng', 'en')]
    subs = [s for s in info['subs'] if s['lang'] in ('eng', 'en') and s['codec'] in ('subrip', 'srt', 'ass', 'mov_text')
            and 'forced' not in s['title'].lower()]
    if not eng or not subs:
        return None
    sub = max(subs, key=lambda s: s['frames'])
    if sub['frames'] and sub['frames'] < 600:
        return None
    return {'audio_index': eng[0]['index'], 'sub_index': sub['index'], 'sub': sub}


def videos_in(d: Path, depth: int):
    out = []
    try:
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in VIDEO_EXT and 'sample' not in p.name.lower():
                out.append(p)
            elif p.is_dir() and depth > 0:
                out += videos_in(p, depth - 1)
    except OSError:
        pass
    return out


def pick(root: str, kind: str, rng, taken, words, log):
    base = Path(root + '\\')
    try:
        dirs = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return None
    rng.shuffle(dirs)
    lo, hi = (FILM_MIN, FILM_MAX) if kind == 'film' else (EP_MIN, EP_MAX)
    tries = 0
    for d in dirs:
        if d.name in taken or is_excluded(d.name, words):
            continue
        if kind == 'film':
            m = re.search(r'\((\d{4})\)', d.name)
            if not m or not (YEAR_RANGE[0] <= int(m.group(1)) <= YEAR_RANGE[1]):
                continue
            vids = videos_in(d, 0)
            v = max(vids, key=lambda p: p.stat().st_size) if vids else None
        else:
            vids = videos_in(d, 2)
            v = rng.choice(vids) if vids else None
        if v is None:
            continue
        tries += 1
        info = probe(v)
        u = usable(info, lo, hi)
        log(f"   {'OK ' if u else 'no '} {d.name[:50]} | {v.name[:40]} | {(info or {}).get('duration', 0) / 60:.0f} min")
        if u:
            return {'kind': kind, 'title': d.name, 'file': str(v), 'duration': info['duration'], **u}
        if tries >= 80:
            break
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    sel_path = WORK / 'selection_full.json'
    if sel_path.exists() and not a.dry_run:
        print("selection_full.json esiste gia': campione congelato.")
        return 0
    rng = random.Random(SEED)
    words = excluded_words()
    print('parole/titoli esclusi:', sorted(words))
    items, taken = [], set()
    for root in FILMS_FROM:
        print(f"\nFilm da {root}")
        it = pick(root, 'film', rng, taken, words, print)
        if it:
            taken.add(it['title'])
            items.append(it)
    for i in range(N_EPISODES):
        print(f"\nEpisodio {i + 1} da V:")
        it = pick('V:', 'serie', rng, taken, words, print)
        if it:
            taken.add(it['title'])
            items.append(it)
    for k, it in enumerate(items):
        it['id'] = f"{k + 1:02d}-" + re.sub(r'[^A-Za-z0-9]+', '-', it['title']).strip('-').lower()[:50]
    print('\n=== CAMPIONE ===')
    for it in items:
        print(f"  {it['id']:50s} {it['kind']:5s} {it['duration'] / 60:5.0f} min audio#{it['audio_index']} sub#{it['sub_index']} "
              f"({it['sub']['frames']} cue)")
    if not a.dry_run:
        WORK.mkdir(parents=True, exist_ok=True)
        sel_path.write_text(json.dumps({'seed': SEED, 'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0 if len(items) >= 5 else 1


if __name__ == '__main__':
    sys.exit(main())
