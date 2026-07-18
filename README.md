# Transcriber Pro

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?logo=qt)
![License](https://img.shields.io/badge/License-MIT-green)
![GPU](https://img.shields.io/badge/GPU-NVIDIA%20CUDA-76B900?logo=nvidia)
![Version](https://img.shields.io/badge/Version-1.9.4-orange)

AI-powered desktop application for automatic subtitle transcription, translation, and bitmap OCR from video files.

---

> 🇮🇹 **[Versione italiana](#versione-italiana)** più in basso.

---

## What It Does

Transcriber Pro takes any video file and produces clean `.srt` subtitle files through two complementary pipelines:

**Audio → SRT pipeline**: extracts or transcribes audio with Faster-Whisper, then translates into Italian (or other languages) using local AI models or cloud APIs. Output is optionally uploaded to OpenSubtitles automatically.

**Bitmap OCR pipeline**: converts PGS (Blu-ray) and VOBSUB (DVD) image-based subtitle tracks directly to text SRT — entirely local, no cloud, verbatim faithful to the source bitmap. Non-Italian tracks are OCR'd and automatically translated to Italian.

**No subscription. No cloud dependency for local models. Runs entirely on your GPU.**

---

## Features

### Transcription & Translation
- **Multi-engine transcription with automatic language routing** — NVIDIA Canary-Qwen-2.5B (English only, best WER; optional, requires a dedicated `venv_canary` with NeMo 2.7.3), Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B (11 languages with word-level timestamps: zh, en, yue, fr, de, it, ja, ko, pt, ru, es; native language auto-detect), Faster-Whisper `large-v3` as guaranteed universal fallback (99 languages, VAD filter) — the pipeline never fails because of a new engine. Only one ASR engine in VRAM at a time. Engine selector in profile settings (`transcription_engine_mode`: auto / canary / qwen3 / faster-whisper)
- **Multiple translation engines**: NLLB-200-3.3B, NLLB fine-tuned, Aya-23-8B, Claude Sonnet API, OpenAI GPT-4o-mini
- **Professional dialogue style (Netflix)** — "- " dashes only when two speakers share the same SRT block (one line per speaker); speaker diarization extended to all engines (`dialogue_style_enabled`, default ON, requires a HuggingFace token); dashes preserved in translated SRTs across all 4 translation backends; `core/subtitle_formatter.py` handles CPL 42, anti-flash, fragment merging and dialogue grouping
- **Vocal separation** via Meta Demucs — isolates speech before transcription for better accuracy
- **Intelligent audio chunking** — splits at silence points for accurate timestamp alignment
- **Transcription profiles** — Fast / Balanced / Quality / Maximum / Batch presets
- **Force audio transcription** — bypass embedded subtitle extraction and always transcribe from audio
- **Gender correction v2 (audio-driven)** — fixes Italian grammatical gender in 1st/2nd person by detecting the speaker's gender **from the voice** (pyannote diarization + ECAPA classifier, 95% acc), then applying a deterministic morphological rewrite guarded by a validator — no LLM, no extra VRAM, hallucinations impossible by construction. Feminine accuracy on first-person lines: 19% → 87% (validated on 700+ auto-extracted test points). Addressee gender for 2nd person comes from dialogue turn-taking (91% acc) and TMDB-cast vocatives

### Bitmap OCR (PGS / VOBSUB → SRT)
- **PGS (Blu-ray) and VOBSUB (DVD)** bitmap subtitle tracks converted to text SRT — verbatim, no AI hallucination
- **Parallel multi-core OCR** — Tesseract runs on multiple CPU cores simultaneously (~8× faster vs single-core; ~1 min for a full film vs ~3 min before)
- **Per-track language detection** — Tesseract model selected automatically from the track's language tag; supported: Italian, English, Spanish, French, German, Portuguese, Dutch (tessdata_best)
- **Automatic translation to Italian** — non-Italian tracks are OCR'd in their source language, saved as `<stem>.<lang>.srt`, then translated to Italian and saved as `<stem>.it.srt` (both files kept)
- **Configurable strategy** — *Targeted review* (OCR + human review UI showing uncertain lines side-by-side with the original bitmap image) or *Automatic* (no review, direct output)
- **Configurable parallel workers** — slider in Settings → Subtitle OCR; default auto = `min(CPU cores, 8)`
- **Write-back modes** — remux SRT as new track inside the MKV in-place, or save as sidecar `.srt` next to the video (VOBSUB always sidecar)

### Library Scanner Integration
- **Self-hosted media server integration** (Plex / Jellyfin) — scans the library, shows files without Italian subtitles
- **Format filter** — filter by All / PGS / VOBSUB to target bitmap-only files for OCR conversion
- **Bitmap badges** — PGS / VOB / MIX clickable badge on each row; click launches OCR for that file
- **Batch OCR** — "Convert all (OCR)" button converts all visible bitmap files automatically
- **Live progress in processing queue** — OCR jobs appear in the main processing queue with status dot, progress bar, and OCR·PGS/VOBSUB tag; do not interfere with the audio transcription queue
- **Automatic DB sync** — after each successful OCR the scanner database is notified (`notify-subtitle` endpoint) so the file exits the "no subtitles" list; a widget sync refreshes the view
- **ASS/SSA → SRT conversion** — server-side remux of text-based embedded subtitles (handled by Library Scanner container, not Transcriber Pro)
- **Italian audio detection** — filename tag detection (ITA, NUiTA, MULTI, etc.)
- **Real-time DB update** on subtitle creation

### Metadata & Upload
- **TMDB / OMDB metadata** — auto-fetches film synopsis for context-aware translation; robust title parsing
- **OpenSubtitles upload** — REST API integration with duplicate detection

### Interface & Infrastructure
- **IT / EN interface** — full bilingual UI; auto-detects system locale; language selector in General Settings
- **Unified Settings dialog** — sidebar + stacked content: General, Transcription, Translation, Adaptive Batch, OpenSubtitles, **Subtitle OCR** (new)
- **SVG icon system** — 38 vector icons, theme-aware
- **Real-time resource monitor** — GPU / CPU / RAM usage during processing
- **GPU memory management** — sequential model loading/unloading; Demucs, ASR engine, and translation model never run simultaneously; cuBLAS workspace cleanup; Demucs tensors kept on CPU (only the segment being processed moves to GPU) → constant ~0.6 GB VRAM peak regardless of file length
- **Freeze-free startup** — torch is never imported in the GUI process (environment check via external CLI); async I/O; splash in ~2 s, Translation tab from 3719 ms to 15 ms
- **Embedded subtitle extraction** — skips transcription when clean text subtitles already exist; bitmap-only streams trigger the OCR pipeline instead
- **Immediate stop** — confirmation dialog; kills FFmpeg / Demucs / Whisper within seconds; cleans temp files automatically
- **Processing queue** — Queued / Active / Completed / Failed filters with live badges

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **GPU** | NVIDIA 6 GB VRAM | NVIDIA RTX 3060 12 GB |
| **RAM** | 12 GB | 16 GB+ |
| **Storage** | SSD (models + temp files) | NVMe SSD |
| **OS** | Windows 10/11 | Windows 11 |

> CPU-only mode is supported but ~10× slower. GPU is strongly recommended.

---

## Software Requirements

- **Python** 3.11
- **CUDA** 12.6 + cuDNN
- **FFmpeg** 6.0+ (must be in PATH)
- **Tesseract OCR 5+** with `ita` and `eng` traineddata from [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) (required for the OCR pipeline)
- **MKVToolNix** (`mkvextract`) — required for VOBSUB extraction only
- **Git** (for cloning)

> The Qwen3 ASR engine is installed with the standard dependencies (`qwen-asr` pip package, already in `requirements.txt`). The NVIDIA Canary engine is **optional** and lives in a dedicated `venv_canary` virtual environment with NeMo 2.7.3 (its dependencies conflict with the app's pinned ones); if absent, the router simply falls back to Qwen3 / Faster-Whisper.

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/chinasky71-byte/TranscriberPro.git
cd TranscriberPro

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Install PyTorch with CUDA first (adjust CUDA version if needed)
pip install torch==2.8.0+cu126 torchaudio==2.8.0+cu126 --index-url https://download.pytorch.org/whl/cu126

# 4. Install remaining dependencies
pip install -r requirements.txt

# 5. (Optional, for Gender Correction v2) Create the separate NLP venv.
#    spaCy lives in its own environment so it never touches the app's
#    pinned dependencies (ctranslate2 4.6.0, setuptools <= 69.5.1),
#    and its RAM is fully released when the helper subprocess exits.
python -m venv venv_nlp
venv_nlp\Scripts\pip install spacy
venv_nlp\Scripts\python -m spacy download it_core_news_lg
#    Also required: a HuggingFace token in the app settings (pyannote
#    diarization models). Accept the pyannote/speaker-diarization-3.1
#    user conditions on huggingface.co once.

# 6. Run
python main.py
```

> For Tesseract OCR: install via [scoop](https://scoop.sh) (`scoop install tesseract`) or the Windows installer, then download `ita.traineddata` and `eng.traineddata` from [tessdata_best](https://github.com/tesseract-ocr/tessdata_best/tree/main) into the Tesseract `tessdata/` folder.

---

## Credentials Configuration

All credentials are entered through the application GUI — no config files to edit manually.

| Credential | Where to enter | How to obtain | Enables |
|---|---|---|---|
| **Claude API Key** | Settings → Translation → Claude | [console.anthropic.com](https://console.anthropic.com) | Claude Sonnet translation |
| **OpenAI API Key** | Settings → Translation → OpenAI | [platform.openai.com](https://platform.openai.com) | GPT-4o-mini translation |
| **HuggingFace Token** | Settings → Translation → HuggingFace | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) | Aya-23-8B (gated model) |
| **OpenSubtitles credentials** | Settings → OpenSubtitles | [opensubtitles.com](https://www.opensubtitles.com) | Subtitle upload |
| **TMDB API Key** | Settings → General → TMDB | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) | Film metadata |
| **OMDB API Key** | Settings → General → OMDB | [omdbapi.com/apikey](http://www.omdbapi.com/apikey.aspx) | IMDb metadata fallback |
| **Library Scanner API Key** | Settings → Library Scanner | Your self-hosted server | Library integration |

All credentials are optional except for the translation model you choose to use. Local models (NLLB, Aya) and the OCR pipeline require no API keys.

---

## Basic Usage

### Audio transcription
1. Add video files — drag and drop or use the file picker
2. Select a transcription profile (Balanced recommended)
3. Choose a translation engine
4. Click **Start** — Demucs → chunking → Whisper → translation → SRT saved next to the video

### Bitmap OCR (PGS / VOBSUB)
1. Open the **Library Scanner** panel (requires a configured self-hosted media server)
2. Set the **Format** filter to PGS or VOBSUB
3. Click the badge on a single row, or **Convert all (OCR)** for the entire filtered list
4. The OCR pipeline runs automatically; progress appears in the main processing queue
5. Italian tracks → `.it.srt`; non-Italian tracks → `.<lang>.srt` + `.it.srt` (translated)

---

## Supported Models

| Model | Type | Size | VRAM | Quality | Speed |
|-------|------|------|------|---------|-------|
| Faster-Whisper large-v3 | Transcription (universal fallback) | 1.5 B params | ~4 GB | ★★★★★ | ★★★★☆ |
| Qwen3-ASR-1.7B + ForcedAligner-0.6B | Transcription (11 languages, word-level timestamps) | 1.7 B + 0.6 B params | ~5 GB | ★★★★★ | ★★★★☆ |
| NVIDIA Canary-Qwen-2.5B | Transcription (English only, optional venv) | 2.5 B params | ~6 GB | ★★★★★ | ★★★★☆ |
| NLLB-200-3.3B | Translation (local) | 3.3 B params | ~5 GB | ★★★☆☆ | ★★★★★ |
| NLLB-200 fine-tuned | Translation (local) | 3.3 B params | ~5 GB | ★★★★☆ | ★★★★★ |
| Aya-23-8B | Translation (local) | 8 B params | ~8 GB | ★★★★☆ | ★★★☆☆ |
| Claude Sonnet (API) | Translation (cloud) | — | 0 GB | ★★★★★ | ★★★★☆ |
| GPT-4o-mini (API) | Translation (cloud) | — | 0 GB | ★★★★☆ | ★★★★★ |
| pyannote 3.1 + ECAPA gender | Gender correction v2 (voice) | — | ~3 GB (transient) | ★★★★☆ | ★★★★☆ |
| spaCy it_core_news_lg | Gender correction v2 (text) | — | 0 GB (CPU, separate venv) | ★★★★☆ | ★★★★★ |
| Tesseract 5 (ita/eng/…) | Bitmap OCR | — | 0 GB | ★★★★☆ | ★★★★★ |

Models are loaded and unloaded sequentially to fit within available VRAM.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER                        │
│                        (PyQt6 GUI)                            │
│  MainWindow · LibraryScannerWidget · OcrReviewDialog          │
│  SettingsDialog · ResourceMonitor · ProfileDialog             │
└───────────────────────────┬──────────────────────────────────┘
                            │ Qt Signals / Slots
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                   CORE PROCESSING LAYER                       │
│          ProcessingPipeline (audio transcription)             │
│  SubtitleExtractor · AudioProcessor · Transcriber             │
│  Translator (NLLB / Aya / Claude / OpenAI)                    │
│  GenderCorrectorV2 (speaker gender map · selector · rewriter) │
│                                                               │
│          PgsOcr · VobSubOcr · BitmapOcrCommon                 │
│  pgsreader (vendored) · vobsub parser (vendored)              │
│  Tesseract (parallel ThreadPool)                              │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                    UTILS / DATA LAYER                         │
│  Config · TMDBClient · IMDbClient · OpenSubtitles             │
│  FileHandler · Logger · ResourceMonitor                       │
│  LibraryScanner API client (notify-subtitle)                  │
└──────────────────────────────────────────────────────────────┘
```

---

## Performance Benchmarks

Tested on: i7-12700KF · 32 GB RAM · RTX 3060 12 GB · NVMe SSD

### Audio transcription (GPU vs CPU)

| Content | Duration | GPU | CPU | Speedup |
|---------|----------|-----|-----|---------|
| Short clip | 5 min | 45 sec | 7 min | 9.3× |
| TV episode | 45 min | 7 min | 67 min | 9.5× |
| Movie | 2 h 15 min | 20 min | 3 h 22 min | 10.1× |
| Long documentary | 4 h | 38 min | 6 h 12 min | 9.8× |

**Average: ~10× speedup with GPU.**

### Bitmap OCR (parallel multi-core, RTX 3060)

| File | Events | Single-core | 8-core parallel | Speedup |
|------|--------|-------------|-----------------|---------|
| Prospect (2018) PGS | 767 | ~195 s | ~17 s | ~11× |
| The Aviator (2004) PGS | 1833 | ~329 s | ~40 s | ~8× |
| Duplex (2003) VOBSUB | 934 | ~150 s | ~20 s | ~7.5× |

**Average OCR speedup: ~8× with 8 parallel workers.**

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m 'Add my feature'`
4. Push and open a Pull Request

Please open an issue first for major changes.

---

## License

This project is licensed under the MIT License.

---

## Changelog

### v1.9.4
- **Multi-engine diarization spacing fix** — sentences split by speaker diarization on a speaker change could come out with words stuck together ("Sièe trasferitadapoco" instead of "Si è trasferita da poco") when the transcription came from the Qwen3-ASR or Canary engines. Cause: the sub-segment text reconstruction assumed faster-whisper's spacing convention (leading space embedded in each word), which doesn't hold for the other two engines. Fixed with an engine-independent spacing normalization.

### v1.9.3
- **Adaptive translation batch fix** — the batch manager for NLLB / NLLB fine-tuned / Aya-23 ignored its class's historical ceiling and only followed the configuration threshold shared with transcription, in some cases overshooting dedicated VRAM with silent spillover into shared RAM (on Windows/WDDM this doesn't raise an out-of-memory error, just a severe slowdown). Each translator now respects its own historically safe batch ceiling.

### v1.9.2
- **Subtitles anchored to lines** — the anti-fragment rule now merges a short tail only when it is a true fragment of the same sentence (pause ≤ 0.8 s and unfinished sentence) — no more blocks joining two distant lines on the same row.
- **Adaptive transcription batch fix** — memory read at device level, batch cap at 16, VRAM-aware ceiling also in classic mode (on Windows/WDDM exceeding VRAM does not raise OOM but silently spills into shared RAM).
- **Progress bar no longer interrupted** by batch-adjustment log lines.

### v1.9.1
- **Demucs memory peak optimization** — tensors stay resident on CPU (`apply_model` moves only the segment being processed to the GPU) → constant VRAM peak (~0.6 GB) regardless of file duration (before: >21 GB GPU committed on an 83-min episode, with spillover into shared RAM).
- **Early unload** of Demucs and Whisper at the end of STEP 3 when the planned engine is Qwen3 / Canary.

### v1.9.0
- **Professional dialogue style (Netflix)** — "- " dashes only when two speakers share the same SRT block (one line per speaker); speaker diarization extended to all engines (`dialogue_style_enabled` option, default ON, requires HuggingFace token); dashes preserved in translated SRTs too (all 4 translation backends).
- **New `core/subtitle_formatter.py`** — CPL 42, anti-flash, fragment merging, dialogue grouping.

### v1.8.1
- Fix: the gender corrector no longer runs on native Italian transcriptions (no translation involved).

### v1.8.0
- **Multi-engine transcription system with automatic language routing**: NVIDIA Canary-Qwen-2.5B (English only, best WER; requires a dedicated `venv_canary` with NeMo 2.7.3 — optional), Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B (11 languages with word-level timestamps: zh, en, yue, fr, de, it, ja, ko, pt, ru, es; native language auto-detect), Faster-Whisper large-v3 as guaranteed universal fallback — the pipeline never fails because of a new engine.
- **Only one ASR engine in VRAM at a time.**
- New config keys: `transcription_engine_mode` (auto / canary / qwen3 / faster-whisper), `canary_enabled`, `qwen3_enabled`; engine selection combo in profile settings.

### v1.7.0
- **Freeze-free startup** — Translation tab from 3719 ms to 15 ms, async I/O, torch never imported in the GUI process (environment check via external CLI), splash in ~2 s.

### v1.6.1
- Fix (GUI): removed "(LLM)" from the gender-correction checkbox label.

### v1.6.0
- **Gender Corrector v2 — complete redesign (audio-driven, deterministic)** — the LLM corrector (Qwen2.5-14B GGUF) was measured as ineffective (+0.66pt) and fully replaced. The speaker's gender is now detected **from the voice** (pyannote diarization + ECAPA classifier, 95% acc) and only 1st/2nd-person forms are rewritten via a deterministic morphological flip guarded by a validator — no LLM, no extra VRAM, hallucinations impossible by construction. First-person feminine accuracy: 19% → 87% (corpus), 0% → 60% on a real full-pipeline episode; masculine never degraded.
- **2nd person support** — addressee gender inferred from dialogue turn-taking (91% acc, strict two-party mode) and TMDB-cast vocatives ("Sei cresciuta, *Veronica*"). Toggle: `gender_correction_second_person`.
- **Diarization reuse** — transcription diarization turns are saved and reused by the corrector (~1–2 min saved per film).
- **Separate NLP venv** — spaCy runs in its own throwaway subprocess environment (`venv_nlp/`): app dependencies untouched, RAM fully returned on exit. See Installation.
- **Evaluation harness** (`gender_eval/`) — MT-GenEval benchmark, automatic ground-truth extraction from dual-track professional subtitles (~700 test points, zero manual annotation), engine comparison, A/B episode runner.
- Migration: the GGUF model is no longer needed; requires NLP venv + HuggingFace token (pyannote). Settings UI updated.

### v1.5.4
- **Per-film subprocess isolation** — each video now processes in a separate Python subprocess that terminates on completion, returning *all* native RAM/VRAM (PyTorch / ctranslate2 / CUDA / NLLB allocator pools) to the OS. Fixes system-RAM growth on long queues (RAM was climbing past 24 GB over 9 films). Opt-out via the `pipeline_subprocess_isolation` config flag. Bonus: a ctranslate2 crash now stays confined to the child — the film fails, the queue continues, the GUI survives.
- **RAM diagnostics** — opt-in `diagnose_ram` logs system RAM + process commit per pipeline step (`[DIAG-RAM]`), centralized in the parent log file, never on screen.
- **Unified & clean logging** — single log file per session; library noise (tqdm download bars, transformers/speechbrain warnings, whisperX / torch.hub stdout) filtered to the log file only; no more console windows flashing from nested subprocesses (`CREATE_NO_WINDOW`).
- **Concurrency guard** — OCR jobs and the audio-transcription pipeline never run simultaneously (OOM prevention): a new OCR request is queued while a transcription runs, and vice versa.
- **Complete NLLB language map** — added ~40 missing Whisper+NLLB languages; ISO 639-2 → 639-1 conversion before Whisper (fixes crash on e.g. Serbian tracks).
- **Failed files no longer stuck** — a failing file correctly moves to "Failed" and the queue advances.
- **Configurable NLLB beam size** — in Settings → Translation.
- **Faster startup** — splash visible in ~1.6 s, main window in ~3.5 s (cold).
- **Library Scanner fixes** — scan progress bar uses the global file total across all paths (no per-disk reset); ASS/SSA conversion bar reaches 100%; `notify-subtitle` no longer marks files with embedded Italian ASS/SSA as "done" (they stayed stuck in the convertible list).

### v1.5.3
- **ASS/SSA filter in Library Scanner widget** — Italian-aware server-side ASS/SSA → SRT conversion (converts only Italian ASS/SSA tracks, preserves the title and the other tracks)

### v1.5.2
- Fix: NoSrt filter incorrectly launched OCR instead of the standard queue

### v1.5.1
- Structured OCR logging (emoji + in-place progress updates)

### v1.5.0
- **Superpower OCR** — pull all bitmap files from the Library Scanner and process them locally in batch
- **Multi-track bitmap OCR** — processes *all* Italian bitmap tracks (not just the first); preserves forced disposition in the mux
- **VOBSUB OCR mux in-place** — remuxes the SRT and removes the original bitmap track
- **Library Scanner scan progress bar** + stale-scan recovery + automatic cleanup of orphan files from crashed OCR runs
- **NoSrt filter** + SRT track titles + window resize/jitter fixes

### v1.4.0
- **Bitmap OCR pipeline** (PGS / VOBSUB → SRT) — verbatim, parallel multi-core Tesseract; ~8× faster than single-core
- **Per-track language OCR** — model selected from stream language tag; non-Italian tracks auto-translated to Italian
- **Library Scanner: Format filter** — filter queue by PGS / VOBSUB; clickable badges; "Convert all (OCR)" batch button
- **OCR jobs in processing queue** — live progress, status dot, progress bar; do not interfere with audio transcription
- **Automatic DB sync** — `notify-subtitle` API endpoint updates scanner DB after each OCR; widget auto-refreshes
- **Unified Settings → Subtitle OCR** — strategy, language, confidence threshold, parallel workers, Tesseract path, write-back mode
- **OCR review dialog** — side-by-side bitmap image + editable OCR text; jump to flagged low-confidence lines
- **Fix**: PGS auto mode now uses the validated pgsreader+Tesseract engine (pgsrip removed — was failing when PATH did not include scoop shims in GUI context)
- **Fix**: extension now follows track language (was always `.ita.srt` regardless of track language)

### v1.3.8
- Queue tab badge update fix

### v1.3.7
- **Local model cache** — all AI models download into `models/.cache/` inside the project folder
- **Auto cache cleanup** — non-Italian models removed from cache after each file; re-download is automatic
- **Force audio transcription** — new option to bypass embedded subtitle extraction

### v1.3.6
- **Gender correction settings UI** — v2 prerequisites status (NLP venv + HF token), 2nd-person toggle, enable/disable

### v1.3.5
- **Gender Correction v2** — deterministic audio-driven Italian gender fix (speaker gender from voice + morphological rewrite with validator); replaces the LLM approach
- **VRAM cleanup fix** — fixed 3.2 GB VRAM stuck after NLLB cleanup (cuBLAS persistent workspaces)
- **Encoding fix** — UnicodeDecodeError on Windows with non-ASCII filenames

### v1.3.1
- **OOM prevention** — adaptive batch size ceiling based on real-time VRAM; fatigue tracking

### v1.3.0
- **Immediate stop** — confirmation dialog; kills all subprocesses within 2–3 seconds; temp cleanup
- **TMDB parser fix** — double HTML entity decoding for edge-case titles

### v1.2.0
- Full IT/EN interface with auto locale detection
- Library Scanner: Italian audio tag detection; real-time DB update
- WhisperX forced alignment (word-level timestamps)
- Embedded subtitle extraction with bitmap auto-skip

### v1.1.0
- Speaker diarization via pyannote.audio
- Adaptive batch size manager
- Subtitle formatter with professional dialogue style
- OpenSubtitles REST API upload with duplicate detection

### v1.0.0
- Initial release: Faster-Whisper, NLLB/Aya/Claude/OpenAI, Demucs, TMDB, OpenSubtitles

---

## Acknowledgements

- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) — CTranslate2-optimized Whisper
- [WhisperX](https://github.com/m-bain/whisperX) — forced alignment and word-level timestamps
- [NLLB-200](https://huggingface.co/facebook/nllb-200-3.3B) — Meta No Language Left Behind
- [Aya-23-8B](https://huggingface.co/CohereForAI/aya-23-8B) — Cohere multilingual model
- [Demucs](https://github.com/facebookresearch/demucs) — Meta source separation
- [pgsreader](https://github.com/EzraBC/pgsreader) — PGS subtitle parser (vendored, patched)
- [VobSub-ML-OCR](https://github.com/vincrichard/VobSub-ML-OCR) — VOBSUB parser ported from Subtitle Edit (vendored)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — OCR engine
- [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) — high-accuracy Tesseract traineddata
- [OpenSubtitles](https://www.opensubtitles.com) — subtitle database and API
- [jonatasgrosman](https://huggingface.co/jonatasgrosman) — wav2vec2 alignment models

---

---

# Versione Italiana

## Cos'è Transcriber Pro

Applicazione desktop AI per la trascrizione, traduzione e conversione OCR automatica di sottotitoli da file video.

Transcriber Pro produce file `.srt` attraverso due pipeline complementari:

**Pipeline audio → SRT**: estrae o trascrive l'audio con Faster-Whisper, poi traduce in italiano (o altre lingue) con modelli AI locali o API cloud. L'output può essere caricato automaticamente su OpenSubtitles.

**Pipeline OCR bitmap**: converte le tracce sottotitolo PGS (Blu-ray) e VOBSUB (DVD) direttamente in testo SRT — tutto in locale, nessun cloud, fedele verbatim al bitmap originale. Le tracce non italiane vengono OCR'd e tradotte automaticamente in italiano.

**Nessun abbonamento. Nessuna dipendenza cloud per i modelli locali. Gira interamente sulla GPU.**

---

## Funzionalità

### Trascrizione e Traduzione
- **Trascrizione multi-engine con routing automatico per lingua** — NVIDIA Canary-Qwen-2.5B (solo inglese, WER migliore; opzionale, richiede un `venv_canary` dedicato con NeMo 2.7.3), Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B (11 lingue con timestamp word-level: zh, en, yue, fr, de, it, ja, ko, pt, ru, es; auto-detect lingua nativo), Faster-Whisper `large-v3` come fallback universale garantito (99 lingue, filtro VAD) — la pipeline non fallisce mai per colpa di un engine nuovo. Un solo engine ASR in VRAM per volta. Selettore engine nelle impostazioni profilo (`transcription_engine_mode`: auto / canary / qwen3 / faster-whisper)
- **Motori di traduzione multipli**: NLLB-200-3.3B, NLLB finetuned, Aya-23-8B, Claude Sonnet API, OpenAI GPT-4o-mini
- **Stile dialoghi professionale (Netflix)** — trattini "- " solo quando due parlanti condividono lo stesso blocco SRT (una battuta per riga); speaker diarization estesa a tutti gli engine (opzione `dialogue_style_enabled`, default ON, richiede token HuggingFace); trattini preservati anche negli SRT tradotti su tutti e 4 i backend di traduzione; `core/subtitle_formatter.py` gestisce CPL 42, anti-flash, merge frammenti e raggruppamento dialoghi
- **Separazione vocale** via Meta Demucs — isola la voce prima della trascrizione per maggiore accuratezza
- **Chunking audio intelligente** — divide ai punti di silenzio per timestamp precisi
- **Profili di trascrizione** — Fast / Balanced / Quality / Maximum / Batch
- **Forza trascrizione audio** — ignora i sottotitoli embedded e trascrive sempre dall'audio
- **Correzione genere v2 (audio-driven)** — corregge il genere grammaticale di 1ª/2ª persona deducendo il genere di chi parla **dalla voce** (diarization pyannote + classificatore ECAPA, 95%) e riscrivendo con un flip morfologico deterministico protetto da validatore — niente LLM, niente VRAM extra, allucinazioni impossibili. Accuratezza femminile in 1ª persona: 19% → 87%. La 2ª persona usa i turni di dialogo (91%) e i vocativi col cast TMDB

### OCR Bitmap (PGS / VOBSUB → SRT)
- **Tracce PGS (Blu-ray) e VOBSUB (DVD)** convertite in SRT testuale — verbatim, nessuna allucinazione AI
- **OCR parallelo multi-core** — Tesseract gira su più core CPU in contemporanea (~8× più veloce; ~1 min per un film intero)
- **Rilevamento lingua per traccia** — il modello Tesseract viene scelto automaticamente dal tag lingua della traccia; supportate: italiano, inglese, spagnolo, francese, tedesco, portoghese, olandese (tessdata_best)
- **Traduzione automatica in italiano** — le tracce non italiane vengono salvate come `<nome>.<lingua>.srt` e tradotte in `<nome>.it.srt` (entrambi i file conservati)
- **Strategia configurabile** — *Revisione mirata* (UI di revisione che mostra le righe incerte affiancate all'immagine bitmap originale) o *Solo automatico* (nessuna revisione, output diretto)
- **Worker paralleli configurabili** — slider in Impostazioni → OCR Sottotitoli; default auto = `min(core CPU, 8)`
- **Modalità write-back** — rimuxa l'SRT come nuova traccia nell'MKV in-place, oppure sidecar `.srt` accanto al video (VOBSUB sempre sidecar)

### Integrazione Library Scanner
- **Integrazione server multimediale self-hosted** (Plex / Jellyfin) — scansiona la libreria, mostra i file senza sottotitoli italiani
- **Filtro Formato** — filtra per Tutti / PGS / VOBSUB per individuare i file solo-bitmap da convertire
- **Badge bitmap** — PGS / VOB / MIX cliccabile su ogni riga; clic avvia l'OCR per quel file
- **Batch OCR** — "Converti tutti (OCR)" converte automaticamente tutti i file bitmap visibili
- **Avanzamento in tempo reale nella coda** — i job OCR appaiono nella coda di processamento principale con dot di stato, barra di avanzamento e tag OCR·PGS/VOBSUB; non interferiscono con la coda di trascrizione audio
- **Sync automatico DB** — dopo ogni OCR riuscito il database dello scanner viene notificato; il file esce dalla lista "senza sub"; un sync del widget aggiorna la vista
- **Conversione ASS/SSA → SRT** — remux server-side dei sottotitoli testo embedded (gestito dal container Library Scanner)
- **Rilevamento audio italiano** — dai tag nel nome file (ITA, NUiTA, MULTI, ecc.)

### Metadati e Upload
- **Metadati TMDB / OMDB** — recupera la sinossi del film per traduzioni contestuali
- **Upload OpenSubtitles** — integrazione REST API con rilevamento duplicati

### Interfaccia e Infrastruttura
- **Interfaccia IT / EN** — UI completamente bilingue; rileva automaticamente la lingua del sistema
- **Dialog Impostazioni unificato** — sidebar + contenuto: Generale, Trascrizione, Traduzione, Batch Adattivo, OpenSubtitles, **OCR Sottotitoli** (nuovo)
- **Sistema icone SVG** — 38 icone vettoriali, adattive al tema
- **Monitor risorse in tempo reale** — GPU / CPU / RAM durante l'elaborazione
- **Gestione memoria GPU** — caricamento/scaricamento sequenziale; Demucs, engine ASR e traduttore non girano mai contemporaneamente; tensori Demucs residenti su CPU (solo il segmento in lavorazione va sulla GPU) → picco VRAM costante ~0,6 GB indipendente dalla durata del file
- **Avvio senza freeze** — torch mai importato nel processo GUI (check ambiente via CLI esterna); I/O asincrono; splash in ~2 s, tab Traduzione da 3719 ms a 15 ms
- **Estrazione sottotitoli embedded** — salta la trascrizione se esistono sub testo; le tracce solo-bitmap avviano la pipeline OCR
- **Stop immediato** — dialog di conferma; termina FFmpeg / Demucs / Whisper in pochi secondi; pulizia temp automatica
- **Coda di processamento** — filtri In coda / Attivi / Completati / Errori con badge live

---

## Requisiti Hardware

| Componente | Minimo | Consigliato |
|-----------|---------|-------------|
| **GPU** | NVIDIA 6 GB VRAM | NVIDIA RTX 3060 12 GB |
| **RAM** | 12 GB | 16 GB+ |
| **Storage** | SSD (modelli + temp) | NVMe SSD |
| **OS** | Windows 10/11 | Windows 11 |

> La modalità solo-CPU è supportata ma ~10× più lenta. GPU fortemente consigliata.

---

## Requisiti Software

- **Python** 3.11
- **CUDA** 12.6 + cuDNN
- **FFmpeg** 6.0+ (nel PATH)
- **Tesseract OCR 5+** con traineddata `ita` e `eng` da [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) (richiesto per la pipeline OCR)
- **MKVToolNix** (`mkvextract`) — solo per l'estrazione VOBSUB
- **Git**

> L'engine ASR Qwen3 si installa con le dipendenze standard (pacchetto pip `qwen-asr`, già in `requirements.txt`). L'engine NVIDIA Canary è **opzionale** e vive in un ambiente virtuale dedicato `venv_canary` con NeMo 2.7.3 (le sue dipendenze confliggono con quelle bloccate dell'app); se assente, il router ripiega semplicemente su Qwen3 / Faster-Whisper.

---

## Installazione

```bash
# 1. Clona il repository
git clone https://github.com/chinasky71-byte/TranscriberPro.git
cd TranscriberPro

# 2. Crea l'ambiente virtuale
python -m venv venv
venv\Scripts\activate

# 3. Installa PyTorch con CUDA (adatta la versione CUDA se necessario)
pip install torch==2.8.0+cu126 torchaudio==2.8.0+cu126 --index-url https://download.pytorch.org/whl/cu126

# 4. Installa le dipendenze
pip install -r requirements.txt

# 5. (Opzionale, per la Correzione Genere v2) Crea il venv NLP separato.
#    spaCy vive in un ambiente proprio: non tocca le dipendenze bloccate
#    dell'app (ctranslate2 4.6.0, setuptools <= 69.5.1) e la sua RAM viene
#    liberata del tutto quando il subprocess termina.
python -m venv venv_nlp
venv_nlp\Scripts\pip install spacy
venv_nlp\Scripts\python -m spacy download it_core_news_lg
#    Serve inoltre un token HuggingFace nelle impostazioni (modelli
#    pyannote): accetta una volta le condizioni d'uso di
#    pyannote/speaker-diarization-3.1 su huggingface.co.

# 6. Avvia
python main.py
```

> Per Tesseract OCR: installa via [scoop](https://scoop.sh) (`scoop install tesseract`) o con l'installer Windows, poi scarica `ita.traineddata` e `eng.traineddata` da [tessdata_best](https://github.com/tesseract-ocr/tessdata_best/tree/main) nella cartella `tessdata/` di Tesseract.

---

## Configurazione Credenziali

Tutte le credenziali si inseriscono dall'interfaccia — nessun file di configurazione da modificare manualmente.

| Credenziale | Dove inserire | Come ottenere | Abilita |
|---|---|---|---|
| **Claude API Key** | Impostazioni → Traduzione → Claude | [console.anthropic.com](https://console.anthropic.com) | Traduzione Claude Sonnet |
| **OpenAI API Key** | Impostazioni → Traduzione → OpenAI | [platform.openai.com](https://platform.openai.com) | Traduzione GPT-4o-mini |
| **Token HuggingFace** | Impostazioni → Traduzione → HuggingFace | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) | Aya-23-8B (modello gated) |
| **Credenziali OpenSubtitles** | Impostazioni → OpenSubtitles | [opensubtitles.com](https://www.opensubtitles.com) | Upload sottotitoli |
| **TMDB API Key** | Impostazioni → Generale → TMDB | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) | Metadati film |
| **OMDB API Key** | Impostazioni → Generale → OMDB | [omdbapi.com/apikey](http://www.omdbapi.com/apikey.aspx) | Fallback metadati IMDb |
| **Library Scanner API Key** | Impostazioni → Library Scanner | Il tuo server self-hosted | Integrazione libreria |

Tutte le credenziali sono opzionali tranne quella del motore di traduzione scelto. I modelli locali (NLLB, Aya) e la pipeline OCR non richiedono API key.

---

## Utilizzo Base

### Trascrizione audio
1. Aggiungi file video — trascina o usa il selettore file
2. Scegli un profilo di trascrizione (Balanced consigliato)
3. Scegli il motore di traduzione
4. Clicca **Avvia** — Demucs → chunking → Whisper → traduzione → SRT salvato accanto al video

### OCR Bitmap (PGS / VOBSUB)
1. Apri il pannello **Library Scanner** (richiede un server media self-hosted configurato)
2. Imposta il filtro **Formato** su PGS o VOBSUB
3. Clicca il badge su una singola riga, o **Converti tutti (OCR)** per l'intera lista filtrata
4. La pipeline OCR parte automaticamente; l'avanzamento appare nella coda di processamento principale
5. Tracce italiane → `.it.srt`; tracce non italiane → `.<lingua>.srt` + `.it.srt` (tradotto)

---

## Modelli Supportati

| Modello | Tipo | Dimensione | VRAM | Qualità | Velocità |
|---------|------|-----------|------|---------|---------|
| Faster-Whisper large-v3 | Trascrizione (fallback universale) | 1,5 B params | ~4 GB | ★★★★★ | ★★★★☆ |
| Qwen3-ASR-1.7B + ForcedAligner-0.6B | Trascrizione (11 lingue, timestamp word-level) | 1,7 B + 0,6 B params | ~5 GB | ★★★★★ | ★★★★☆ |
| NVIDIA Canary-Qwen-2.5B | Trascrizione (solo inglese, venv opzionale) | 2,5 B params | ~6 GB | ★★★★★ | ★★★★☆ |
| NLLB-200-3.3B | Traduzione (locale) | 3,3 B params | ~5 GB | ★★★☆☆ | ★★★★★ |
| NLLB-200 finetuned | Traduzione (locale) | 3,3 B params | ~5 GB | ★★★★☆ | ★★★★★ |
| Aya-23-8B | Traduzione (locale) | 8 B params | ~8 GB | ★★★★☆ | ★★★☆☆ |
| Claude Sonnet (API) | Traduzione (cloud) | — | 0 GB | ★★★★★ | ★★★★☆ |
| GPT-4o-mini (API) | Traduzione (cloud) | — | 0 GB | ★★★★☆ | ★★★★★ |
| pyannote 3.1 + ECAPA gender | Correzione genere v2 (voce) | — | ~3 GB (transitori) | ★★★★☆ | ★★★★☆ |
| spaCy it_core_news_lg | Correzione genere v2 (testo) | — | 0 GB (CPU, venv separato) | ★★★★☆ | ★★★★★ |
| Tesseract 5 (ita/eng/…) | OCR bitmap | — | 0 GB | ★★★★☆ | ★★★★★ |

I modelli vengono caricati e scaricati sequenzialmente per rientrare nella VRAM disponibile.

---

## Licenza

Questo progetto è distribuito con licenza MIT.

---

## Changelog

### v1.9.4
- **Fix spaziatura diarization multi-engine** — le frasi divise dalla speaker diarization per cambio di parlante potevano comparire con le parole attaccate ("Sièe trasferitadapoco" invece di "Si è trasferita da poco") quando la trascrizione proveniva dagli engine Qwen3-ASR o Canary. Causa: la ricostruzione del testo del sotto-segmento assumeva la convenzione di spaziatura di faster-whisper (spazio incorporato a inizio parola), non valida per gli altri due engine. Corretto con una normalizzazione della spaziatura indipendente dall'engine.

### v1.9.3
- **Fix batch adattivo di traduzione** — il batch manager di NLLB / NLLB fine-tuned / Aya-23 ignorava il tetto storico della propria classe e seguiva solo la soglia di configurazione condivisa con la trascrizione, causando in alcuni casi lo sforamento della VRAM dedicata con spillover silenzioso in RAM condivisa (Windows/WDDM non genera un errore di memoria in quel caso, solo un forte rallentamento). Ora ogni traduttore rispetta il proprio tetto di batch storicamente sicuro.

### v1.9.2
- **Sottotitoli ancorati alle battute** — la regola anti-frammento riunisce la coda corta solo se è un vero frammento della stessa frase (pausa ≤ 0,8 s e frase non conclusa) — niente più blocchi con due battute distanti nella stessa riga.
- **Fix batch adattivo trascrizione** — lettura memoria a livello device, cap batch 16, tetto VRAM-aware anche in modalità classica (su Windows/WDDM lo sforamento VRAM non dà OOM ma spillover silenzioso in RAM condivisa).
- **Barra di progresso non più interrotta** dai log di aggiustamento batch.

### v1.9.1
- **Ottimizzazione picco memoria Demucs** — tensori residenti su CPU (`apply_model` sposta sulla GPU solo il segmento in lavorazione) → picco VRAM costante (~0,6 GB) indipendente dalla durata del file (prima: >21 GB GPU committed su un episodio da 83 min, con spillover in RAM condivisa).
- **Unload anticipato** di Demucs e Whisper a fine STEP 3 quando l'engine pianificato è Qwen3 / Canary.

### v1.9.0
- **Stile dialoghi professionale (Netflix)** — trattini "- " solo quando due parlanti condividono lo stesso blocco SRT (una battuta per riga); speaker diarization estesa a tutti gli engine (opzione `dialogue_style_enabled`, default ON, richiede token HuggingFace); trattini preservati anche negli SRT tradotti (tutti e 4 i backend di traduzione).
- **Nuovo `core/subtitle_formatter.py`** — CPL 42, anti-flash, merge frammenti, raggruppamento dialoghi.

### v1.8.1
- Fix: il gender corrector non gira più sulle trascrizioni in italiano nativo (senza traduzione).

### v1.8.0
- **Sistema di trascrizione multi-engine con routing automatico per lingua**: NVIDIA Canary-Qwen-2.5B (solo inglese, WER migliore; richiede un `venv_canary` dedicato con NeMo 2.7.3 — opzionale), Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B (11 lingue con timestamp word-level: zh, en, yue, fr, de, it, ja, ko, pt, ru, es; auto-detect lingua nativo), Faster-Whisper large-v3 come fallback universale garantito — la pipeline non fallisce mai per colpa di un engine nuovo.
- **Un solo engine ASR in VRAM per volta.**
- Nuove chiavi config: `transcription_engine_mode` (auto / canary / qwen3 / faster-whisper), `canary_enabled`, `qwen3_enabled`; combo di selezione engine nelle impostazioni profilo.

### v1.7.0
- **Avvio senza freeze UI** — tab Traduzione da 3719 ms a 15 ms, I/O asincrono, torch mai importato nel processo GUI (check ambiente via CLI esterna), splash in ~2 s.

### v1.6.1
- Fix (GUI): rimosso "(LLM)" dall'etichetta della checkbox correzione genere.

### v1.6.0
- **Correzione Genere v2 — redesign completo (audio-driven, deterministico)** — il correttore LLM (Qwen2.5-14B GGUF), misurato inefficace (+0,66pt), è stato interamente sostituito. Il genere del parlante ora si deduce **dalla voce** (diarization pyannote + classificatore ECAPA, 95%) e si riscrivono solo le forme di 1ª/2ª persona con un flip morfologico deterministico protetto da validatore — niente LLM, niente VRAM extra, allucinazioni impossibili per costruzione. Accuratezza femminile in 1ª persona: 19% → 87% (corpus), 0% → 60% su un episodio reale da pipeline completa; maschile mai degradato.
- **Supporto 2ª persona** — genere dell'interlocutore dai turni di dialogo (91%, modalità strict a due parlanti) e dai vocativi col cast TMDB ("Sei cresciuta, *Veronica*"). Toggle: `gender_correction_second_person`.
- **Riuso diarization** — i turni della trascrizione vengono salvati e riusati dal correttore (~1–2 min risparmiati a film).
- **Venv NLP separato** — spaCy gira in un subprocess usa-e-getta col proprio ambiente (`venv_nlp/`): dipendenze dell'app intatte, RAM restituita all'uscita. Vedi Installazione.
- **Harness di valutazione** (`gender_eval/`) — benchmark MT-GenEval, ground-truth automatico dai sottotitoli professionali dual-track (~700 punti di test, zero annotazione manuale), confronto motori, A/B su episodio.
- Migrazione: il modello GGUF non serve più; servono venv NLP + token HuggingFace (pyannote). UI impostazioni aggiornata.

### v1.5.4
- **Isolamento della pipeline per-film in subprocess** — ogni video viene ora elaborato in un processo Python separato che termina a fine elaborazione, restituendo *tutta* la RAM/VRAM nativa (pool allocator di PyTorch / ctranslate2 / CUDA / NLLB) all'OS. Risolve la crescita della RAM di sistema su code lunghe (saliva oltre 24 GB su 9 film). Disattivabile con il flag `pipeline_subprocess_isolation`. Bonus: un crash di ctranslate2 resta confinato al processo figlio — il film va in "Falliti", la coda prosegue, la GUI sopravvive.
- **Diagnostica RAM** — flag opt-in `diagnose_ram`: logga RAM di sistema + commit del processo per ogni step (`[DIAG-RAM]`), centralizzata nel file di log principale, mai a schermo.
- **Logging unificato e pulito** — un solo file di log per sessione; il rumore delle librerie (barre di download tqdm, warning transformers/speechbrain, stdout di whisperX / torch.hub) va solo nel file, non a schermo; niente più finestre console lampeggianti dalle subprocess annidate (`CREATE_NO_WINDOW`).
- **Guardia anti-concorrenza** — i job OCR e la pipeline di trascrizione audio non girano mai contemporaneamente (prevenzione OOM): una nuova richiesta OCR viene accodata mentre una trascrizione è in corso, e viceversa.
- **Mappa lingue NLLB completa** — aggiunte ~40 lingue Whisper+NLLB mancanti; conversione ISO 639-2 → 639-1 prima di Whisper (risolve il crash su tracce es. serbe).
- **File falliti non più bloccati** — un file che fallisce passa correttamente a "Falliti" e la coda avanza.
- **Beam size NLLB configurabile** — in Impostazioni → Traduzione.
- **Avvio più veloce** — splash visibile in ~1,6 s, finestra principale in ~3,5 s (cold).
- **Fix Library Scanner** — la barra di scansione usa il totale globale su tutti i percorsi (nessun reset per disco); la barra di conversione ASS/SSA arriva al 100%; `notify-subtitle` non marca più "done" i file con ASS/SSA italiano ancora embedded (restavano bloccati nella lista convertibili).

### v1.5.3
- **Filtro ASS/SSA nel widget Library Scanner** — conversione ASS/SSA → SRT server-side, italiana-aware (converte solo le tracce ASS/SSA italiane, preserva il titolo e le altre tracce)

### v1.5.2
- Fix: il filtro NoSrt avviava l'OCR invece della coda standard

### v1.5.1
- Logging OCR strutturato (emoji + aggiornamento progress in-place)

### v1.5.0
- **Superpower OCR** — recupera tutti i file bitmap dal Library Scanner e li elabora localmente in batch
- **OCR bitmap multi-traccia** — elabora *tutte* le tracce bitmap italiane (non solo la prima); preserva la disposition forced nel mux
- **VOBSUB OCR mux in-place** — rimuxa l'SRT e rimuove la traccia bitmap originale
- **Barra di avanzamento scansione Library Scanner** + recovery scansioni bloccate + pulizia automatica file orfani da OCR crashati
- **Filtro NoSrt** + titoli traccia SRT + fix resize/jitter finestra

### v1.4.0
- **Pipeline OCR bitmap** (PGS / VOBSUB → SRT) — verbatim, Tesseract parallelo multi-core; ~8× più veloce del single-core
- **OCR per lingua della traccia** — modello scelto automaticamente dal tag lingua; tracce non italiane tradotte automaticamente in italiano
- **Library Scanner: filtro Formato** — filtra per PGS / VOBSUB; badge cliccabili; pulsante "Converti tutti (OCR)"
- **Job OCR nella coda di processamento** — avanzamento live, dot di stato, barra progress; non interferiscono con la coda audio
- **Sync automatico DB** — endpoint `notify-subtitle` aggiorna il DB scanner dopo ogni OCR; widget si aggiorna col sync
- **Impostazioni → OCR Sottotitoli** — strategia, lingua, soglia confidenza, worker paralleli, path Tesseract, modalità write-back
- **Dialog di revisione OCR** — immagine bitmap affiancata al testo OCR editabile; salto automatico alle righe a bassa confidenza
- **Fix**: modalità automatica PGS usa ora il motore validato pgsreader+Tesseract (rimosso pgsrip — falliva quando il PATH non includeva gli shim nel contesto GUI)
- **Fix**: estensione file segue la lingua della traccia (era sempre `.ita.srt` indipendentemente dalla lingua)

### v1.3.8
- Fix aggiornamento badge tab coda

### v1.3.7
- **Cache modelli locale** — tutti i modelli AI scaricano in `models/.cache/` dentro il progetto
- **Pulizia cache automatica** — modelli non italiani rimossi dopo ogni file; re-download automatico
- **Forza trascrizione audio** — nuova opzione per ignorare i sottotitoli embedded

### v1.3.6
- **UI impostazioni correzione genere** — stato prerequisiti v2 (venv NLP + token HF), toggle 2ª persona, abilitazione

### v1.3.5
- **Correzione Genere v2** — fix deterministico guidato dall'audio (genere del parlante dalla voce + riscrittura morfologica validata); sostituisce l'approccio LLM
- **Fix VRAM** — risolti 3,2 GB VRAM bloccati dopo cleanup NLLB (cuBLAS persistent workspaces)
- **Fix encoding** — UnicodeDecodeError su Windows con nomi file non-ASCII

### v1.3.1
- **Prevenzione OOM** — ceiling adattivo batch size basato su VRAM disponibile in tempo reale

### v1.3.0
- **Stop immediato** — dialog di conferma; termina tutti i sottoprocessi in 2–3 secondi; pulizia temp
- **Fix parser TMDB** — doppia decodifica entity HTML per titoli edge-case

### v1.2.0
- Interfaccia IT/EN completa con rilevamento locale automatico
- Library Scanner: rilevamento audio italiano; aggiornamento DB in tempo reale
- Allineamento forzato WhisperX (timestamp a livello parola)
- Estrazione sottotitoli embedded con skip automatico bitmap

### v1.1.0
- Diarizzazione speaker via pyannote.audio
- Gestore batch adattivo per VRAM
- Formattatore sottotitoli professionale
- Upload OpenSubtitles REST API con rilevamento duplicati

### v1.0.0
- Release iniziale: Faster-Whisper, NLLB/Aya/Claude/OpenAI, Demucs, TMDB, OpenSubtitles

---

## Ringraziamenti

- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) — Whisper ottimizzato con CTranslate2
- [WhisperX](https://github.com/m-bain/whisperX) — allineamento forzato e timestamp a livello parola
- [NLLB-200](https://huggingface.co/facebook/nllb-200-3.3B) — Meta No Language Left Behind
- [Aya-23-8B](https://huggingface.co/CohereForAI/aya-23-8B) — modello multilingua Cohere
- [Demucs](https://github.com/facebookresearch/demucs) — separazione sorgenti Meta
- [pgsreader](https://github.com/EzraBC/pgsreader) — parser PGS (vendorizzato, con patch)
- [VobSub-ML-OCR](https://github.com/vincrichard/VobSub-ML-OCR) — parser VOBSUB portato da Subtitle Edit (vendorizzato)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — motore OCR
- [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) — traineddata ad alta precisione
- [OpenSubtitles](https://www.opensubtitles.com) — database sottotitoli e API
- [jonatasgrosman](https://huggingface.co/jonatasgrosman) — modelli wav2vec2 per allineamento
