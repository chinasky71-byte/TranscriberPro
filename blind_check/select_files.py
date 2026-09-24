"""
Passo 1 — selezione dei file della libreria e degli estratti (solo CPU/rete).

Sceglie con seme fisso (decision_rule.SEED) N_FILMS film (Y:, W:) e N_SERIES
episodi di serie (V:) con audio INGLESE, durata adeguata e non gia' usati dal
banco ASR; assegna ai file in alternanza il motore di trascrizione (whisper /
qwen3) e ritaglia con ffmpeg (-c copy, senza sottotitoli) un estratto di 20
minuti a partire dal 30% della durata. Scrive work/selection.json: la lista
NON si modifica dopo (e' il campione congelato).

Uso (da Transcriber_Pro, venv principale, PYTHONIOENCODING=utf-8):
    venv\\Scripts\\python.exe blind_check\\select_files.py            # sceglie e ritaglia
    venv\\Scripts\\python.exe blind_check\\select_files.py --dry-run  # solo scelta, nessun ritaglio
"""
import argparse
import random
import re
import subprocess
import sys
from pathlib import Path

import common as C
import decision_rule as R

VIDEO_EXT = ('.mkv', '.mp4', '.avi', '.m4v')


def list_dirs(root: Path):
    try:
        return sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []


def videos_in(d: Path, depth: int = 2):
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


def year_of(name: str):
    m = re.search(r'\((\d{4})\)', name)
    return int(m.group(1)) if m else None


def pick_film(root: Path, rng: random.Random, taken: set, banned_words: set, log):
    dirs = list_dirs(root)
    rng.shuffle(dirs)
    tries = 0
    for d in dirs:
        y = year_of(d.name)
        if y is None or not (R.YEAR_RANGE[0] <= y <= R.YEAR_RANGE[1]):
            continue
        low = d.name.lower()
        if any(w in low for w in banned_words) or d.name in taken:
            continue
        vids = videos_in(d, 0)
        if not vids:
            continue
        v = max(vids, key=lambda p: p.stat().st_size)
        tries += 1
        info = C.ffprobe(v)
        dur_min = info.get('duration', 0) / 60
        ok = bool(info) and C.has_english_audio(info) and R.MIN_FILM_MIN <= dur_min <= R.MAX_DURATION_MIN
        log(f"   {'OK ' if ok else 'no '} {d.name[:60]} | {dur_min:.0f} min | audio {[a['lang'] for a in info.get('audio', [])]}")
        if ok:
            return {'kind': 'film', 'title': d.name, 'file': str(v), 'info': info}
        if tries >= 60:
            break
    return None


def pick_episode(root: Path, rng: random.Random, taken: set, log):
    dirs = list_dirs(root)
    rng.shuffle(dirs)
    tries = 0
    for d in dirs:
        if d.name in taken:
            continue
        vids = videos_in(d, 2)
        if not vids:
            continue
        v = rng.choice(vids)
        tries += 1
        info = C.ffprobe(v)
        dur_min = info.get('duration', 0) / 60
        ok = bool(info) and C.has_english_audio(info) and R.MIN_EPISODE_MIN <= dur_min <= R.MAX_DURATION_MIN
        log(f"   {'OK ' if ok else 'no '} {d.name[:40]} / {v.name[:50]} | {dur_min:.0f} min | audio {[a['lang'] for a in info.get('audio', [])]}")
        if ok:
            return {'kind': 'serie', 'title': d.name, 'file': str(v), 'info': info}
        if tries >= 60:
            break
    return None


def cut_excerpt(item: dict, out: Path, log) -> bool:
    dur = item['info']['duration']
    start = int(dur * R.EXCERPT_START_FRAC // 60) * 60
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 1_000_000:
        item['excerpt_start_s'] = start
        return True
    # SOLO la traccia audio INGLESE: con una traccia italiana presente la pipeline sceglierebbe
    # quella, trascriverebbe l'italiano e salterebbe la traduzione (verificato il 25/09).
    eng = next((a for a in item['info']['audio'] if a['lang'].lower() in ('eng', 'en')), None)
    if eng is None:
        log("   nessuna traccia audio inglese")
        return False
    cmd = ['ffmpeg', '-y', '-v', 'error', '-ss', str(start), '-i', item['file'], '-t', str(R.EXCERPT_MIN * 60),
           '-map', '0:v:0?', '-map', f"0:{eng['index']}", '-c', 'copy', '-sn', '-dn', str(out)]
    log(f"   ritaglio {R.EXCERPT_MIN} min da {start // 60} min -> {out.name}")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **C.NO_WINDOW)
    if r.returncode != 0:
        log(f"   ffmpeg errore: {r.stderr[-300:]}")
        return False
    chk = C.ffprobe(out)
    if len(chk.get('audio', [])) != 1 or not C.has_english_audio(chk):
        log(f"   ATTENZIONE: l'estratto non ha esattamente una traccia audio inglese: {chk.get('audio')}")
        return False
    item['excerpt_start_s'] = start
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help="rifa' la scelta anche se selection.json esiste")
    a = ap.parse_args()

    def log(m):
        print(m.encode('ascii', 'replace').decode() if not sys.stdout.encoding or 'utf' not in sys.stdout.encoding.lower() else m, flush=True)

    sel_path = C.WORK / 'selection.json'
    if sel_path.exists() and not a.force and not a.dry_run:
        log(f"selection.json esiste gia' ({sel_path}): campione congelato. Usa --force solo se vuoi rifarlo.")
        sel = C.read_json(sel_path)
    else:
        rng = random.Random(R.SEED)
        banned = {k.rsplit('-', 1)[0].replace('-', ' ') for k in C.bench_film_keys() if k}
        log(f"titoli del banco ASR esclusi: {sorted(banned)}")
        items, taken = [], set()
        for i, root in enumerate(R.FILMS_FROM[:R.N_FILMS]):
            log(f"\nFilm {i + 1}/{R.N_FILMS} da {root}")
            it = pick_film(Path(root + '\\'), rng, taken, banned, log)
            if it:
                taken.add(Path(it['file']).parent.name)
                items.append(it)
        for i in range(R.N_SERIES):
            log(f"\nSerie {i + 1}/{R.N_SERIES} da V:")
            it = pick_episode(Path('V:\\'), rng, taken, log)
            if it:
                taken.add(it['title'])
                items.append(it)
        for k, it in enumerate(items):
            it['id'] = f"{k + 1:02d}-{C.slug(it['title'])}"
            it['engine'] = R.ENGINES[k % len(R.ENGINES)]
        sel = {'seed': R.SEED, 'rule_sha256': C.sha256_file(C.HERE / 'decision_rule.py'), 'items': items}
        if not a.dry_run:
            C.write_json_atomic(sel_path, sel)

    log("\n=== CAMPIONE ===")
    for it in sel['items']:
        log(f"  {it['id']:45s} {it['kind']:5s} {it['engine']:8s} {it['info']['duration'] / 60:5.0f} min")
    if a.dry_run:
        return 0
    bad = 0
    for it in sel['items']:
        out = C.WORK / 'excerpts' / f"{it['id']}.mkv"
        if not cut_excerpt(it, out, log):
            bad += 1
        it['excerpt'] = str(out)
    C.write_json_atomic(sel_path, sel)
    log(f"\n{len(sel['items']) - bad}/{len(sel['items'])} estratti pronti in {C.WORK / 'excerpts'}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
