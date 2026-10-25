"""Translate one SRT with the project's translator factory (bench subprocess).

Usage: python -m bench._translate <model_type> <source.srt> <output.srt>
Exit code 0 on success, 1 on failure.
"""
from __future__ import annotations

import sys

from utils.cache_bootstrap import HF_HOME  # noqa: F401  (side effect: cache inside models/)


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print("usage: python -m bench._translate <model_type> <in.srt> <out.srt>", file=sys.stderr)
        return 2
    model_type, source, output = argv[1], argv[2], argv[3]

    from core.translator import get_translator

    translator = get_translator(model_type=model_type)
    translator.set_log_callback(lambda message: print(message, flush=True))
    try:
        ok = translator.translate_file(
            input_path=source, output_path=output,
            src_lang="eng", tgt_lang="ita",
        )
    finally:
        try:
            translator.cleanup()
        except Exception:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
