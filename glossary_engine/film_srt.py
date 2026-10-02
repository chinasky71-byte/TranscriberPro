# -*- coding: utf-8 -*-
"""
Helper SRT/ffprobe del motore Glossario per show (glossary_engine/).

Copiati VERBATIM da mt_eval/build_film_bench.py (parse_srt, probe_subtitles,
extract_srt, align, ts_to_seconds): il Glossario li usa per leggere i sottotitoli
degli episodi e allineare le tracce. Qui vivono per non far dipendere codice
attivo da una cartella di banchi di prova (mt_eval/). Solo stdlib.
"""
import json
import os
import re
import subprocess

TS = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def ts_to_seconds(value: str) -> float:
    m = TS.search(value)
    if not m:
        return 0.0
    h, mi, s, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


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


def extract_srt(video, index, out_path):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", video,
           "-map", f"0:{index}", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0 and os.path.getsize(out_path) > 0


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
