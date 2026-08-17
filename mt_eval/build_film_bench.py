"""
Banco di valutazione su film reale
===================================
Costruisce un set EN→IT da un film che porta dentro sia i sottotitoli inglesi
(bitmap PGS, da riconoscere con l'OCR) sia una traduzione italiana
professionale, da usare come termine di paragone.

Perché serve, rispetto al set sintetico:

1. **Timing reali.** Sul set sintetico le durate erano derivate dalla lunghezza
   del testo inglese, e con quelle qualunque resa italiana più lunga risulta
   fuori norma — anche la traduzione umana, che "sforava" nel 66% dei blocchi.
   Con i tempi veri il reading speed torna una metrica onesta.

2. **Un bersaglio di stile.** La traccia italiana professionale dice a quanti
   caratteri per blocco si attesta chi fa questo mestiere, quanto condensa,
   quanto rispetta i 42 caratteri, se censura il turpiloquio. NON è invece una
   verità di traduzione: premiare la somiglianza a una singola resa umana è lo
   stesso errore del chrF, che penalizza traduzioni buone ma diverse.

L'allineamento EN↔IT è temporale: le due tracce hanno segmentazioni diverse,
quindi ogni blocco inglese viene appaiato a quello italiano con la maggiore
sovrapposizione di tempo.

Uso:
    venv\\Scripts\\python mt_eval\\build_film_bench.py --video "Y:\\...\\film.mkv"
    venv\\Scripts\\python mt_eval\\build_film_bench.py --video ... --limit 400
"""

import argparse
import json
import os
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

TS = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def ts_to_seconds(value: str) -> float:
    m = TS.search(value)
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


# Tesseract confonde sistematicamente la "I" maiuscola isolata con la barra
# verticale: sul sorgente inglese di Deadpool 2 succede nel 15% dei blocchi.
# Il modulo OCR del progetto è volutamente *verbatim* e non corregge nulla, il
# che è giusto per la revisione manuale ma qui falserebbe la misura: i motori
# verrebbero penalizzati per un errore di riconoscimento, non di traduzione.
# La sostituzione è sicura perché "|" non è mai testo valido di sottotitolo.
_OCR_BAR_I = re.compile(r"(?<![A-Za-z0-9])\|(?=[\s'’]|$)", re.M)


def clean_ocr(text: str) -> str:
    return _OCR_BAR_I.sub("I", text)


# Le tracce inglesi "[CC]" (closed caption) portano cose che la traccia
# italiana per udenti non ha: descrizioni sonore fra parentesi quadre, note
# musicali, ed etichette di parlante in maiuscolo. Tradurle e poi confrontarle
# con un riferimento che non le contiene produrrebbe errori inventati.
_CC_SOUND = re.compile(r"^\s*[\[(].*?[\])]\s*$|^\s*♪.*♪\s*$")
_CC_SPEAKER = re.compile(r"^[A-Z][A-Z0-9 .'\-]{2,}(?:\s*\[[^\]]*\])?\s*:\s*")


def strip_cc(text: str):
    """Toglie l'etichetta di parlante; None se il blocco è solo suono."""
    lines = []
    for line in text.split("\n"):
        if _CC_SOUND.match(line.strip()):
            continue
        lines.append(_CC_SPEAKER.sub("", line).strip())
    out = "\n".join(l for l in lines if l).strip()
    return out or None


def parse_srt(path):
    """[(start, end, testo)] in secondi."""
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read().replace("\r\n", "\n").lstrip("\ufeff")
    for block in content.split("\n\n"):
        lines = [l for l in block.split("\n") if l.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, _, end = lines[1].partition("-->")
        text = "\n".join(lines[2:]).strip()
        if text:
            out.append((ts_to_seconds(start), ts_to_seconds(end), text))
    return sorted(out, key=lambda x: x[0])


def probe_subtitles(video):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "s",
           "-show_entries", "stream=index,codec_name:stream_tags=language,title",
           "-of", "json", video]
    out = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    streams = json.loads(out.stdout or "{}").get("streams", [])
    for s in streams:
        tags = s.get("tags") or {}
        s["language"] = (tags.get("language") or "und").lower()
        s["title"] = tags.get("title") or ""
    return streams


def pick_streams(streams):
    """Traccia italiana testuale COMPLETA + traccia inglese bitmap COMPLETA.

    Le tracce 'forced' coprono solo il dialogo in lingua straniera: poche
    decine di blocchi, inutilizzabili come riferimento.
    """
    def is_forced(s):
        return "forced" in s["title"].lower()

    ita = [s for s in streams
           if s["language"].startswith("it") and s["codec_name"] == "subrip"
           and not is_forced(s)]
    eng_bmp = [s for s in streams
               if s["language"].startswith("en")
               and "pgs" in s["codec_name"] and not is_forced(s)]
    eng_txt = [s for s in streams
               if s["language"].startswith("en") and s["codec_name"] == "subrip"
               and not is_forced(s)]
    return (ita[0] if ita else None,
            eng_txt[0] if eng_txt else None,
            eng_bmp[0] if eng_bmp else None)


def extract_srt(video, index, out_path):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video,
           "-map", f"0:{index}", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0 and os.path.getsize(out_path) > 0


def ocr_english(video, stream, out_path, log):
    """OCR della traccia PGS inglese riusando il motore già nel progetto."""
    from core.pgs_ocr import PgsOcr
    from core.pgs_types import events_to_srt
    from utils.config import get_config

    ocr = PgsOcr(video, get_config(), log_callback=log)
    events, _lang = ocr._ocr_single_stream(stream)
    srt = events_to_srt(events)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(srt)
    return len(events)


def align(src_blocks, ref_blocks, min_overlap=0.5):
    """Appaia ogni blocco inglese a quello italiano che si sovrappone di più.

    La sovrapposizione è richiesta in ENTRAMBE le direzioni. Le due tracce
    hanno segmentazioni diverse e quella inglese è spesso più fine: senza il
    controllo bidirezionale, due battute inglesi finiscono sullo stesso
    riferimento italiano, e ciascuna viene poi giudicata contro un testo che
    contiene anche la battuta dell'altra — errori inventati su entrambe.

    Ogni riferimento può essere usato una sola volta: in caso di contesa vince
    l'appaiamento con la sovrapposizione maggiore.
    """
    cand = []
    j = 0
    for si, (s0, s1, stext) in enumerate(src_blocks):
        s_dur = max(s1 - s0, 0.001)
        best = None
        k = j
        while k < len(ref_blocks) and ref_blocks[k][0] < s1 + 5.0:
            r0, r1, rtext = ref_blocks[k]
            ov = min(s1, r1) - max(s0, r0)
            if ov > 0:
                r_dur = max(r1 - r0, 0.001)
                score = min(ov / s_dur, ov / r_dur)
                if best is None or score > best[0]:
                    best = (score, k, rtext)
            if r1 < s0 - 5.0:
                j = k
            k += 1
        if best and best[0] >= min_overlap:
            cand.append((best[0], si, best[1], stext, best[2], s0, s1))

    # Un riferimento, un solo appaiamento: si assegna prima chi combacia meglio.
    cand.sort(key=lambda c: -c[0])
    used_ref, used_src = set(), set()
    keep = []
    for score, si, ri, stext, rtext, s0, s1 in cand:
        if ri in used_ref or si in used_src:
            continue
        used_ref.add(ri)
        used_src.add(si)
        keep.append((si, s0, s1, stext, rtext))

    keep.sort(key=lambda x: x[0])
    return [{"start": round(s0, 3), "end": round(s1, 3),
             "source": stext, "reference": rtext}
            for _, s0, s1, stext, rtext in keep]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--name", default="film")
    ap.add_argument("--limit", type=int, default=0,
                    help="tieni solo i primi N blocchi allineati")
    ap.add_argument("--skip-ocr", action="store_true",
                    help="riusa l'SRT inglese già prodotto")
    args = ap.parse_args()

    video = args.video
    if not os.path.isfile(video):
        sys.exit(f"File non trovato: {video}")

    work = os.path.join(SCRIPT_DIR, "film")
    os.makedirs(work, exist_ok=True)
    eng_srt = os.path.join(work, f"{args.name}_en.srt")
    ita_srt = os.path.join(work, f"{args.name}_it_pro.srt")
    out_set = os.path.join(SCRIPT_DIR, f"filmset_{args.name}.jsonl")

    streams = probe_subtitles(video)
    print("Tracce sottotitoli:")
    for s in streams:
        print(f"  [{s['index']}] {s['codec_name']:<20} {s['language']:<4} "
              f"{s['title']}")

    ita, eng_txt, eng_bmp = pick_streams(streams)
    if not ita:
        sys.exit("Nessuna traccia italiana testuale completa: banco impossibile.")
    print(f"\nRiferimento italiano : traccia {ita['index']} ({ita['title']})")

    if not os.path.isfile(ita_srt):
        if not extract_srt(video, ita["index"], ita_srt):
            sys.exit("Estrazione della traccia italiana fallita")
    ref_blocks = parse_srt(ita_srt)
    print(f"  {len(ref_blocks)} blocchi")

    if args.skip_ocr and os.path.isfile(eng_srt):
        print(f"\nSorgente inglese     : riuso {os.path.basename(eng_srt)}")
    elif eng_txt:
        print(f"\nSorgente inglese     : traccia {eng_txt['index']} (testuale)")
        if not extract_srt(video, eng_txt["index"], eng_srt):
            sys.exit("Estrazione della traccia inglese fallita")
    elif eng_bmp:
        print(f"\nSorgente inglese     : traccia {eng_bmp['index']} (PGS, OCR)")
        print("  l'OCR di un film intero richiede parecchi minuti...")
        n = ocr_english(video, eng_bmp, eng_srt, log=lambda m: print(f"    {m}"))
        print(f"  {n} eventi riconosciuti")
    else:
        sys.exit("Nessuna traccia inglese utilizzabile")

    src_blocks = parse_srt(eng_srt)
    fixed = sum(1 for _, _, t in src_blocks if _OCR_BAR_I.search(t))
    if fixed:
        print(f"  corretto '|' → 'I' in {fixed} blocchi "
              f"({fixed * 100 // max(len(src_blocks), 1)}%): artefatto OCR noto")
        src_blocks = [(a, b, clean_ocr(t)) for a, b, t in src_blocks]

    before = len(src_blocks)
    cleaned = []
    for a, b, t in src_blocks:
        stripped = strip_cc(t)
        if stripped:
            cleaned.append((a, b, stripped))
    if len(cleaned) != before or any(
            c[2] != s[2] for c, s in zip(cleaned, src_blocks)):
        print(f"  ripuliti i marcatori closed-caption "
              f"({before - len(cleaned)} blocchi di solo suono rimossi)")
    src_blocks = cleaned
    print(f"  {len(src_blocks)} blocchi")

    pairs = align(src_blocks, ref_blocks)
    print(f"\nAllineati {len(pairs)}/{len(src_blocks)} blocchi inglesi "
          f"({len(pairs) * 100 // max(len(src_blocks), 1)}%)")
    if args.limit:
        pairs = pairs[:args.limit]

    for i, p in enumerate(pairs, 1):
        p["id"] = i
        p["category"] = "film"

    with open(out_set, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # Il bersaglio di stile: cosa fa il professionista con questi tempi.
    n = len(pairs) or 1
    src_len = sum(len(p["source"].replace("\n", " ")) for p in pairs) / n
    ref_len = sum(len(p["reference"].replace("\n", " ")) for p in pairs) / n
    over_cpl = sum(1 for p in pairs
                   if any(len(l) > 42 for l in p["reference"].split("\n")))
    over_cps = sum(1 for p in pairs
                   if (p["end"] - p["start"]) > 0
                   and len(p["reference"].replace("\n", " "))
                   / (p["end"] - p["start"]) > 17.0)
    print(f"\nBERSAGLIO DI STILE (traduzione professionale, tempi reali)")
    print(f"  caratteri per blocco : {ref_len:.1f}  (inglese {src_len:.1f}, "
          f"rapporto {ref_len / max(src_len, 1):.2f})")
    print(f"  righe oltre 42 car   : {over_cpl * 100 // n}%")
    print(f"  blocchi oltre 17 CPS : {over_cps * 100 // n}%")
    print(f"\nSet scritto: {out_set}")


if __name__ == "__main__":
    main()
