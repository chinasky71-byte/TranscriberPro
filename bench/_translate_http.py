"""Translate an SRT through a running llama.cpp server (OpenAI-compatible API).

One request per block, same prompt and decoding for every model, so the
comparison is about the model and not about a per-model prompt.

Usage:
    python -m bench._translate_http <base_url> <model> <in.srt> <out.srt> [--timeout 120]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from bench.text import parse_srt_entries, srt_from_entries

SYSTEM_PROMPT = (
    "You are a professional subtitle translator. Translate the user's text "
    "from English to Italian. Output only the Italian translation, with no "
    "quotes, labels, notes or explanations."
)


def _clean(text: str) -> str:
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    for prefix in ("Italian:", "Italiano:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return " ".join(text.split())


def _translate(base_url: str, model: str, text: str, timeout: float) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": max(64, int(len(text) * 3)),
        "stream": False,
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    return _clean(body["choices"][0]["message"]["content"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("model")
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    entries = parse_srt_entries(args.source)
    if not entries:
        print("empty source SRT", file=sys.stderr)
        return 2

    translated = 0
    for position, entry in enumerate(entries, start=1):
        text = entry["text"]
        result = ""
        for attempt in range(2):
            try:
                result = _translate(args.base_url, args.model, text, args.timeout)
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                print(f"[{position}/{len(entries)}] error: {exc}", file=sys.stderr, flush=True)
                result = ""
            if result:
                break
        entry["text"] = result or text
        if result:
            translated += 1
        if position % 10 == 0 or position == len(entries):
            print(f"[{position}/{len(entries)}] translated", file=sys.stderr, flush=True)

    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(srt_from_entries(entries))
    print(f"done: {translated}/{len(entries)} blocks translated", file=sys.stderr, flush=True)
    return 0 if translated else 1


if __name__ == "__main__":
    sys.exit(main())
