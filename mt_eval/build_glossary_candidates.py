"""
Scoperta candidati di glossario per uno show — Fase 1, piano "Glossario per-show"
==================================================================================
Un glossario (core/glossary.py) fissa la resa italiana di un termine ricorrente
così NLLB non lo traduce in modo diverso episodio per episodio (misurato su
Knight's & Magic: "Knight Runner" a volte lasciato letterale, una volta reso
"Cavalieri Corridori"). Questo script trova i candidati per QUALUNQUE show
della libreria, riusando gli stessi mattoni di mt_eval/build_film_bench.py.

Logica per episodio:
  1. Traccia IT NOSTRA: un .srt nella cartella dell'episodio con l'header
     "AI generated subtitles" — i sub scaricati non ce l'hanno. Episodi senza
     bozza nostra vengono saltati (nessuna base per misurare l'incoerenza).
  2. Traccia EN: un .srt esterno con "en"/"eng" nel nome se esiste, altrimenti
     la traccia subrip inglese incorporata nel video (stesso file, associato
     per numero di stagione/episodio — i nomi di release spesso NON
     condividono lo stesso "stem" del video, matchare sullo stem è fragile).
  3. parse_srt()/align() (riuso senza modifiche da build_film_bench.py) EN↔IT,
     poi tutti gli episodi dello show confluiscono in un unico banco.
  4. Candidati: sequenze di 1-3 parole capitalizzate consecutive nell'EN,
     frequenza minima configurabile, esclusi le maiuscole di inizio-blocco e
     una stopword-list minima.
  5. Segnale di incoerenza: quante occorrenze del candidato compaiono
     verbatim (case-insensitive) nel blocco IT allineato, quante no. Un
     candidato assente in ALCUNE occorrenze e presente in ALTRE è la prova
     diretta che NLLB lo rende in modo diverso a seconda del contesto.

Uso:
    venv\\Scripts\\python mt_eval\\build_glossary_candidates.py --show-dir "V:\\The Ark" --name the_ark
    venv\\Scripts\\python mt_eval\\build_glossary_candidates.py --show-dir "V:\\PONIES" --name ponies --min-freq 2
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from build_film_bench import parse_srt, align, probe_subtitles, extract_srt  # noqa: E402

OUR_HEADER = "AI generated subtitles"

# Stagione/episodio: "S01E02", "1x02", tollera separatori vari nel nome release.
_SXXEXX_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})|(\d{1,2})x(\d{1,3})')

_STOPWORDS = {
    "The", "A", "An", "I", "You", "He", "She", "It", "We", "They",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
    "Mr", "Mrs", "Ms", "Dr", "Oh", "Yeah", "Okay", "Ok", "Hey", "Well",
    # "I" resta maiuscolo per grammatica inglese a QUALSIASI posizione nella
    # frase, non solo a inizio — il filtro sentence-start non lo intercetta.
    # Stesso discorso per le interiezioni/contrazioni molto comuni che
    # restano capitalizzate anche a metà dialogo per enfasi.
    "I'm", "I'll", "I've", "I'd", "It's", "It'll", "You're", "You'll",
    "You've", "You'd", "We're", "We'll", "We've", "They're", "They'll",
    "That's", "There's", "Here's", "Let's", "Don't", "Can't", "Won't",
    "Didn't", "Isn't", "Wasn't", "Aren't", "Doesn't", "What's", "Who's",
    "How's", "Why's", "Where's", "Come", "Look", "Wait", "Stop", "Go",
    "Yes", "No", "Sir", "Ma'am",
}
# Sequenze di 1-3 parole capitalizzate consecutive.
_CANDIDATE_RE = re.compile(
    r"\b([A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+){0,2})\b")


def episode_key(filename: str):
    m = _SXXEXX_RE.search(filename)
    if not m:
        return None
    if m.group(1):
        return (int(m.group(1)), int(m.group(2)))
    return (int(m.group(3)), int(m.group(4)))


def is_ours(srt_path: str) -> bool:
    try:
        with open(srt_path, encoding="utf-8", errors="replace") as f:
            return OUR_HEADER in f.read(300)
    except Exception:
        return False


def find_episodes(show_dir: str):
    """Un elemento per episodio: {key, video, it_ours, en_external}."""
    by_key = {}
    for root, _dirs, files in os.walk(show_dir):
        for name in files:
            key = episode_key(name)
            if key is None:
                continue
            path = os.path.join(root, name)
            entry = by_key.setdefault(key, {"key": key, "video": None,
                                             "it_ours": None, "en_external": None})
            low = name.lower()
            if low.endswith((".mkv", ".mp4")):
                entry["video"] = path
            elif low.endswith(".srt"):
                if ("en" in low or "eng" in low) and "it" not in low.split(".en")[0][-3:]:
                    entry.setdefault("en_candidates", []).append(path)
                if ".it." in low or low.endswith(".it.srt"):
                    if is_ours(path):
                        entry["it_ours"] = path
    for entry in by_key.values():
        cands = entry.pop("en_candidates", [])
        entry["en_external"] = cands[0] if cands else None
    return sorted(by_key.values(), key=lambda e: e["key"])


def get_english_track_index(video: str):
    """Indice della migliore traccia subrip inglese incorporata, o None."""
    streams = probe_subtitles(video)
    eng = [s for s in streams if s["language"].startswith("en")
           and s["codec_name"] == "subrip"
           and "forced" not in s["title"].lower()]
    if not eng:
        return None
    # Preferisci la traccia SENZA "SDH"/"CC" nel titolo (più pulita).
    plain = [s for s in eng if "sdh" not in s["title"].lower()
             and "cc" not in s["title"].lower()]
    return (plain[0] if plain else eng[0])["index"]


def collect_show_pairs(show_dir: str, work_dir: str):
    """[(source_text, reference_text, start, end), ...] su tutti gli episodi."""
    episodes = find_episodes(show_dir)
    all_pairs = []
    skipped_no_draft = 0
    for ep in episodes:
        if not ep["it_ours"]:
            skipped_no_draft += 1
            continue
        en_path = ep["en_external"]
        if not en_path and ep["video"]:
            idx = get_english_track_index(ep["video"])
            if idx is not None:
                out_path = os.path.join(
                    work_dir, f"en_{ep['key'][0]:02d}x{ep['key'][1]:02d}.srt")
                if extract_srt(ep["video"], idx, out_path):
                    en_path = out_path
        if not en_path:
            continue
        en_blocks = parse_srt(en_path)
        it_blocks = parse_srt(ep["it_ours"])
        pairs = align(en_blocks, it_blocks)
        all_pairs.extend(pairs)
        print(f"  S{ep['key'][0]:02d}E{ep['key'][1]:02d}: "
              f"{len(pairs)}/{len(en_blocks)} blocchi allineati")
    if skipped_no_draft:
        print(f"  ({skipped_no_draft} episodi senza bozza nostra, saltati)")
    return all_pairs


def _is_sentence_start(prefix: str) -> bool:
    """Vero se ciò che precede il match, sulla stessa riga, è vuoto, un
    trattino di dialogo, o finisce con punteggiatura di fine frase (anche
    seguita da virgolette di chiusura) — non solo l'inizio riga: una riga
    può contenere più frasi ("Come on, baby. Come on.")."""
    prefix = prefix.rstrip()
    if not prefix or prefix in "-–—":
        return True
    return prefix[-1] in '.!?' or (
        len(prefix) >= 2 and prefix[-1] in '"”\'' and prefix[-2] in '.!?')


def find_candidates(pairs, min_freq: int):
    """{candidato: {'total': n, 'verbatim': n, 'missing': n, 'examples': [...]}}

    Conta solo le occorrenze NON a inizio riga (l'inglese capitalizza ogni
    frase, quindi una parola comune capitalizzata solo a inizio riga —
    "What", "But", "So"...— non è un termine ricorrente da fissare). Per
    ogni riga del blocco, se tutto ciò che precede il match è vuoto o un
    solo trattino di dialogo ("- "), quell'occorrenza viene scartata dal
    conteggio: un vero nome proprio ricorrente compare comunque a
    sufficienza a metà frase per superare la soglia di frequenza.
    """
    stats = {}
    for p in pairs:
        src, ref = p["source"], p["reference"]
        ref_low = ref.lower()
        for line in src.split("\n"):
            for m in _CANDIDATE_RE.finditer(line):
                term = m.group(1)
                if term in _STOPWORDS:
                    continue
                if _is_sentence_start(line[:m.start()]):
                    continue
                entry = stats.setdefault(term, {"total": 0, "verbatim": 0,
                                                 "missing": 0, "examples": []})
                entry["total"] += 1
                present = term.lower() in ref_low
                if present:
                    entry["verbatim"] += 1
                else:
                    entry["missing"] += 1
                if len(entry["examples"]) < 4:
                    entry["examples"].append({"source": src, "reference": ref,
                                              "start": p["start"], "verbatim": present})
    return {t: s for t, s in stats.items() if s["total"] >= min_freq}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-dir", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--min-freq", type=int, default=3)
    args = ap.parse_args()

    work_dir = os.path.join(SCRIPT_DIR, "glossary_work", args.name)
    os.makedirs(work_dir, exist_ok=True)

    print(f"Show: {args.show_dir}\n")
    pairs = collect_show_pairs(args.show_dir, work_dir)
    print(f"\nTotale blocchi allineati (tutti gli episodi con bozza nostra): {len(pairs)}")

    candidates = find_candidates(pairs, args.min_freq)
    ranked = sorted(candidates.items(), key=lambda kv: -kv[1]["missing"])

    out_path = os.path.join(SCRIPT_DIR, f"glossary_candidates_{args.name}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for term, s in ranked:
            f.write(json.dumps({"term": term, **s}, ensure_ascii=False) + "\n")

    print(f"\n{len(ranked)} candidati (frequenza >= {args.min_freq}), "
          f"i primi 15 per incoerenza (occorrenze 'assenti'):\n")
    for term, s in ranked[:15]:
        print(f"  {term!r}: {s['total']} tot, {s['verbatim']} verbatim, "
              f"{s['missing']} assenti")
        for ex in s["examples"][:2]:
            flag = "OK " if ex["verbatim"] else "MISS"
            print(f"    [{flag}] EN: {ex['source'][:60]!r}")
            print(f"          IT: {ex['reference'][:60]!r}")

    print(f"\nScritto: {out_path}")


if __name__ == "__main__":
    main()
