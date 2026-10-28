# Third-party notices

Transcriber Pro's own code is MIT-licensed (see `LICENSE`). The components below are **not** covered by that license and keep their own terms.

| Component | Where | License / terms |
|---|---|---|
| NLLB-200 tokenizer, SentencePiece model and config files (derived from `facebook/nllb-200-3.3B`, Meta AI, *No Language Left Behind*) | `NLLB_Tranined/` | **CC-BY-NC 4.0**: attribution required, **non-commercial use only**. The fine-tuned model weights are not in this repository. |
| `vobsub` (VobSub `.idx/.sub` parser) | `core/vendor/vobsub/` | MIT, Copyright (c) 2026 Vincent Richard (`core/vendor/vobsub/LICENSE`) |
| `pgsreader` (PGS `.sup` parser, upstream: EzraBC/pgsreader) | `core/vendor/pgsreader/` | The upstream project publishes **no license file**. Included with local patches (see `core/vendor/pgsreader/VENDOR.md`). If the author objects, it will be removed or rewritten. |
| Inter Tight, JetBrains Mono (fonts) | `assets/fonts/` | SIL Open Font License 1.1 (copyright and license are embedded in each font file's metadata) |
| `pywebview` 6.2.1 (optional native window shell; installed from `requirements-web.txt`, not redistributed here) | `requirements-web.txt` | BSD-3-Clause (upstream: r0x0r/pywebview). |
| `htm` 3.1.1 (Apache-2.0, includes `preact` 10.19.6, MIT; web UI, no CDN, copy in the repository) | `tpweb/static/vendor/` | Apache License 2.0 (`LICENSE-htm.txt`) and MIT (`LICENSE-preact.txt`). |
| Python dependencies | installed from `requirements*.txt` | Each package under its own license; they are downloaded at install time, not redistributed here. |
| Models (Whisper, Qwen, Canary, Gemma, pyannote, ...) | downloaded at run time | Each model under its own license/terms; some require accepting conditions on Hugging Face. |

External services used with the user's own credentials: TMDB (`tmdb_api.txt`), OMDb, OpenSubtitles, Hugging Face, Anthropic/OpenAI (optional). Keys are never stored in this repository.
