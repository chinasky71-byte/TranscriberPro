#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Does the glossary change anything? Isolated test, without the ASR in the way.

Takes the reference lines that contain glossary terms, translates them with the
real translator twice — once with an empty glossary and once with the show
glossary — and reports, for every line, whether the term survived correctly.

Why isolate it: in the end-to-end run the glossary showed no measurable effect on
clip A, but that run mixed ASR errors (a name heard as something else never
reaches the translator) with translation errors. Here only the translator is
measured.

    python bench/glossary_check.py --reference clipA-ref-eng.srt \
        --glossary ~/.transcriberpro/glossary/manual_monster-2022.json \
        --model nllb --json /var/tmp/glossary-check.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.text import parse_srt_entries  # noqa: E402


def lines_with_terms(reference: Path, terms: List[str], limit: int = 0) -> List[str]:
    """Reference cue texts that contain at least one glossary term."""
    selected: List[str] = []
    for entry in parse_srt_entries(reference):
        text = re.sub(r"</?[a-zA-Z][^>]*>", "", entry["text"]).strip()
        if not text:
            continue
        lowered = text.lower()
        if any(term.lower() in lowered for term in terms):
            selected.append(text)
        if limit and len(selected) >= limit:
            break
    return selected


def _write_srt(lines: List[str], path: Path) -> Path:
    blocks = []
    for index, text in enumerate(lines, start=1):
        start = f"00:00:{index:02d},000"
        end = f"00:00:{index:02d},900"
        blocks.append(f"{index}\n{start} --> {end}\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def _read_srt_lines(path: Path) -> List[str]:
    return [entry["text"] for entry in parse_srt_entries(path)]


def translate_lines(lines: List[str], glossary: Dict[str, str], model: str,
                    work_dir: Path, tag: str,
                    src_lang: str = "en", tgt_lang: str = "it") -> List[str]:
    """Translate the lines through the real translator, returning the output lines."""
    from core.translator import get_translator
    source = _write_srt(lines, work_dir / f"in-{tag}.srt")
    target = work_dir / f"out-{tag}.srt"
    translator = get_translator(model_type=model, glossary=glossary)
    translator.translate_file(source, target, src_lang, tgt_lang)
    return _read_srt_lines(target)


def score_line(source: str, translated: str, terms: List[str]) -> Dict[str, Any]:
    """Is a glossary term still present, and did the translation keep it as-is?"""
    present = [term for term in terms if term.lower() in source.lower()]
    kept = [term for term in present if term.lower() in translated.lower()]
    return {"terms": present, "kept": kept,
            "missing": [term for term in present if term not in kept]}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Isolated glossary check")
    parser.add_argument("--reference", required=True, help="reference SRT in the source language")
    parser.add_argument("--glossary", required=True, help="glossary JSON (term -> rendering)")
    parser.add_argument("--model", default="nllb", help="translator to use (default: nllb)")
    parser.add_argument("--limit", type=int, default=0, help="max lines to test")
    parser.add_argument("--src", default="en", help="source language (default: en)")
    parser.add_argument("--tgt", default="it", help="target language (default: it)")
    parser.add_argument("--work-dir", default="/var/tmp/tp-glossary-check")
    parser.add_argument("--json", default="", help="write the full result here")
    args = parser.parse_args(argv)

    glossary = json.loads(Path(args.glossary).read_text(encoding="utf-8"))
    terms = list(glossary)
    lines = lines_with_terms(Path(args.reference), terms, args.limit)
    if not lines:
        print("no reference line contains a glossary term", file=sys.stderr)
        return 2
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)

    print(f"{len(lines)} righe con termini, glossario da {len(terms)} voci, modello {args.model}")
    without = translate_lines(lines, {}, args.model, work, "noglo", args.src, args.tgt)
    with_glossary = translate_lines(lines, glossary, args.model, work, "glo", args.src, args.tgt)

    rows = []
    for source, plain, guided in zip(lines, without, with_glossary):
        rows.append({"source": source, "without": plain, "with": guided,
                     "score_without": score_line(source, plain, terms),
                     "score_with": score_line(source, guided, terms)})

    total_terms = sum(len(row["score_without"]["terms"]) for row in rows)
    kept_without = sum(len(row["score_without"]["kept"]) for row in rows)
    kept_with = sum(len(row["score_with"]["kept"]) for row in rows)
    changed = sum(1 for row in rows if row["without"] != row["with"])

    for row in rows:
        print(f"\nsrc : {row['source']}")
        print(f"senza: {row['without']}")
        print(f"con  : {row['with']}")

    print(f"\ntermini presenti nella reference : {total_terms}")
    print(f"termini mantenuti senza glossario : {kept_without}/{total_terms}")
    print(f"termini mantenuti con glossario   : {kept_with}/{total_terms}")
    print(f"righe tradotte diversamente       : {changed}/{len(rows)}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "model": args.model,
            "lines": len(rows),
            "terms": total_terms,
            "kept_without": kept_without,
            "kept_with": kept_with,
            "changed_lines": changed,
            "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"json: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
