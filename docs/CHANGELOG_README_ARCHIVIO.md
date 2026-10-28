# Archivio del changelog condensato del README

Queste sono le note per versione che stavano nel `README.md` fino alla 1.34.41, spostate qui senza modifiche quando il README e' stato riscritto (il dettaglio completo e piu' recente e' in [`CHANGELOG.md`](../CHANGELOG.md)). / These are the per-version notes that lived in `README.md` up to 1.34.41, moved here unchanged when the README was rewritten (the complete and more recent detail is in [`CHANGELOG.md`](../CHANGELOG.md)).

---

# English

## Changelog

> **Note on this repository:** only active code is published here. The test benches and evaluation harnesses mentioned below
> (`mt_eval/`, `asr_eval/`, `whisper_split_eval/`, `split_eval/`, `gender_eval/`, `diar_eval/`, `Gemma training/`) stay in the
> author's working folder and are not part of the repository. The per-show glossary engine, which used to live in `mt_eval/`,
> is now in `glossary_engine/`.

### v1.24.0 - v1.30.2
Six weeks of work on translation/transcription quality for non-English sources, condensed here; full detail,
measurement methodology and decision rules for every claim below are in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.41** — Library Scanner client, row display logic and import/OCR/Superpower actions moved out of the GUI (`core/services/`, no Qt): same GUI and behaviour (verified on Windows against a real server and a fake one), groundwork for a future web UI. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.40** — OCR review, transcription profile and translation-model dialog logic moved out of the GUI (`core/jobs/`, `core/services/`, no Qt): same GUI and behaviour (verified with real PGS/VobSub files: identical SRT and muxed MKV), groundwork for a future web UI. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.39** — Subtitle Sync and Glossary logic moved out of the GUI (`core/jobs/`, `core/services/`, no Qt): same GUI and behaviour (verified with real files: identical synced SRT and queue results), groundwork for a future web UI. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.38** — Settings, history and metadata logic moved out of the GUI (`core/services/`, no Qt): same GUI and behaviour, groundwork for a future web UI. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.37** — Queue refactoring: one engine (`core/jobs/`) shared by the GUI and the headless queue; same GUI, headless queue now logs like the GUI, writes the history and the step preview. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.36** — IQ3_M GGUF threshold lowered to 7.3 GiB free VRAM (measured on an RTX 3060 limited to 7.3 GiB), so 8 GB cards stay on the GGUF path. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.35** — Progress bar and ETA for speaker recognition (diarization) in the pipeline card and the overall bar. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.34** — Fixes from the first real AMD GPU validation (Linux/ROCm); translation is no longer reported as successful when most blocks stay untranslated. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.33** — Language auto-detect by voting on several chunks; wait for ASR VRAM release before GPU translation; progress bar and ETA for gender correction v2. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.32** — GGUF installer: restored its translated messages, replaces files only when the SHA-256 differs; new test on all tr()/_tr() keys. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.31** — TranslateGemma GGUF path ON by default (Q4_K_M on 12-20 GB cards, IQ3_M on 8-12 GB, automatic NF4 fallback); installer downloads the GGUF files. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.30** — Urgent fix: the app did not start on Windows (PyQt6 was imported before onnxruntime by the language detection). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.29** — GGUF translator now runs in a clean subprocess (fixes the Windows crash); quality bench: Q4_K_M/Q3_K_M/IQ3_M non-inferior to NF4 and ~14x faster; GGUF files published on Hugging Face. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.28** — GGUF path: fixed a Windows crash (`llama_supports_gpu_offload` before backend init). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.27** — TranslateGemma GGUF path for 8-12 GB and AMD/Vulkan cards (code ready, OFF by default until the quality bench). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.26** — Interface translation (phase B): pipeline log lines follow the interface language (cloud session, PR #8-#13). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.25** — Interface translation (phase A): about 120 texts that were Italian-only now follow the interface language. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.24** — Language names and queue tabs now follow the interface language. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.23** — "Force audio transcription" added to the per-file options of the queue's right-click menu. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.22** — Default job options moved to Settings ("Job options" tab); the main panel keeps a one-line summary and the shutdown checkbox, freeing space for the queue and the Library Scanner. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.21** — Per-file job options from the queue's right-click menu (subtitle language, translation engine, gender correction, mux, OpenSubtitles upload, OCR review) and multi-selection. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.20** — Detected graphics card shown under the status pill: green for NVIDIA, red for AMD, "CPU only" when no compatible GPU. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.19** — Installer: with `--no-gpu`/`-NoGpu` a failed CPU-wheel download now stops with a clear message instead of falling back to CUDA wheels; Linux/AMD work from the cloud session merged. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.18** — Remove a waiting file from the queue while it is processing (Delete key or context menu); a file already being processed can no longer be queued a second time. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.17** — Multi-vendor GPU detection (`utils/gpu_detect.py`, Windows and Linux; NVIDIA, AMD, Intel; CUDA/ROCm/Vulkan backends). Not verified on real AMD/Intel hardware. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.16** — Linux (unverified): `install.sh --with-models --qwen-size=auto|7b|14b` downloads the Qwen 14B/7B and the fine-tuned NLLB, like the Windows installer. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.15** — Qwen2.5-7B is now the automatic fallback for GPUs under 12 GB (glossary building and L3 reservoir); the 14B stays the default and an explicitly set model path behaves exactly as before. Installer option `-QwenSize`. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.14** — Licensing: added `LICENSE` and `NOTICE.md`, removed the TMDB key hardcoded in the source (now `tmdb_api.txt` / `TMDB_API_KEY`), removed third-party film test fixtures. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.13** — Linux phase 3 (UNVERIFIED on a real Linux machine): `install.sh`/`run.sh`, Library Scanner mounted-folder mapping, portable self-check, `notify-send`. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.12** — Clean-PC install: external tools (Tesseract, MKVToolNix) are found outside PATH, `-NoGpu` installs CPU torch, Library Scanner default address fixed. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.11** — Installer: with `-NoGpu` it installs the CPU wheel of llama-cpp-python (the CUDA one cannot load without the NVIDIA driver). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.10** — Installer: with `-InstallSystemDeps` it now downloads Tesseract's `ita`/`eng` language data by itself (UAC copy when the folder is a system one). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.9** — Linux compatibility, phase 3a: outside Windows, drive-letter paths saved in a copied config are ignored in favour of the defaults (no change on Windows). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.8** — Linux compatibility, phase 1b: the glossary engine's Qwen bridge also uses `utils/platform_compat.py` (identical values on Windows). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.7** — Linux compatibility, phase 1: known Windows-specific spots now go through `utils/platform_compat.py` (identical values on Windows; glossary cancel uses psutil instead of `taskkill`). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.6** — Linux compatibility, phase 0: new `utils/platform_compat.py` helper (no behaviour change on Windows). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.5** — Compact Log is on by default at startup. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.4** — Steps card: no stale ETA when an engine reports 100%. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.3** — UI: slimmer Start / Stop buttons (more room for the queue and the Library Scanner). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.2** — Steps card: transcription and translation are held at 99% until the next step starts (diarization / recovery still running). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.1** — Gender correction ETA shown in the steps card. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.0** — Engine ETA (transcription, Demucs, NLLB/API translation) in the steps card; real progress bar for the standard Demucs path. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.4** — UI: the steps card shows the translation engine's own ETA (no 3% / 20 s thresholds). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.3** — UI: Library Scanner OCR progress and stats share one row (about 28 px more for the list). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.2** — UI: slimmer Library Scanner buttons (Import all filtered / Superpower), more room for the list. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.1** — UI: the "Pipeline in progress" card stays after the queue ends and is regenerated by the next file. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.0** — UI: with Compact Log on, a "Pipeline in progress" card lists every step of the current file (done / active with percent, ETA and bar / pending / disabled / not needed); Demucs ETA in the log. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.32.3** — UI: scanner badge contrast (AA), format badges no longer clipped, buttons no longer keep focus after a click, 16 unused tokens removed. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.32.2** — UI: slimmer card headers; with the Library Scanner open, the queue and the scanner table share the free vertical space. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.32.1** — UI: spinbox digits no longer clipped, compact Library Scanner (filters on one row, taller list), smaller job-option checkboxes in an aligned 2x2 grid. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.32.0** — UI polish: AA contrast, duplicate emoji removed next to icons, capsule progress bar with separate percentage label, SVG control icons, dialogs aligned to the palette, three pre-existing layout bugs fixed. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.31.1** — UI logic separated from the view (`gui/services/`: queue, metadata, job options, settings, log filter); fixes a crash when pressing Start with the glossary or sync running. 216 tests + visual bench. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.31.0** — UI foundations: design tokens (`gui/design_tokens.py`), QSS theme generated from a template, reusable components and per-dialog style templates; ~145 hard-coded colors and ~45 scattered stylesheets removed with pixel-identical rendering (visual bench). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.13** — Anime uploads to OpenSubtitles: when TMDB has no episode IMDb ID, it is looked up on OMDb by exact, unique episode title, so more episodes are attached to their own page instead of "uncategorized". Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.12** — Subtitle blocks with out-of-order start times (14 of 654 own sidecars) are now sorted by the cleaner, and the mux check compares lines as a set, so "Mux into video" no longer rejects them. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.11** — "Mux into video" now works on MKVs with mjpeg cover/attachment streams (mkvmerge fallback when ffmpeg fails, plus a check that only the intended subtitle track was replaced); leftover mojibake fixed; bench extended (mjpeg mux, ETA with Canary/Whisper, OCR failure falling back to audio). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.10** — Source mojibake fixed (log/effects emoji and accents), `output` reported for OCR episodes, multi-track bitmap OCR in pipeline now writes one sidecar and leaves the MKV untouched. Bench 13/13. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.9** — Internal refactor completed: subtitle selection/OCR (STEP 0/1/1b) moved out of `process()`, behaviour unchanged (9/9 bench cases). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.8** — Internal refactor: `process()` split into private step methods, behaviour unchanged (9/9 bench cases, identical traces). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.7** — The pipeline now reports what it is doing as structured events next to the text log (opt-in via `TP_EVENTS=1`, text parsing kept as a fallback); per-file progress no longer depends on log wording. Validated on real clips (9/9). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.6** — A bitmap subtitle track (PGS/VobSub) tagged Italian but containing another language is now replaced in the MKV by the Italian sidecar after OCR + translation; fixes an `UnboundLocalError` that made OCR fall back silently to audio transcription when the content language was corrected. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.5** — Headless queue runner (`python -m core.queue_runner <folder>`) with a live `queue_status.json`; transcription ETA rounds to the nearest minute. Validated on real clips with a bench (outside the repo). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.4.15.10.26** — Guard against the video being rewritten by another program (e.g. FileFlows) during a job: upload and in-place remux are skipped if its size/mtime changed. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.4** — Per-file progress (queue row and poster bar) follows the real duration of each phase instead of a fixed step table: no more freezing at 60% during transcription or 88% during translation. OCR+translation now shows its progress bars. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.3.15.10.26** — The transcription progress bar shows the estimated time remaining (Qwen3, Canary, Whisper); Whisper's single-file path now reports real progress. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.3.14.10.26** — Cosmetic: progress bars in the subtitle-sync dialog log are rewritten in place like in the main log. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.3** — New job option "Mux into video" (Job options card, next to the OpenSubtitles upload): the subtitle created by the job is added to the MKV as a new track after the upload; the `.srt` stays next to the video. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.2.11.10.26** — An embedded text track tagged Italian whose content is another language (e.g. English tagged `ita`) is replaced in the MKV by the generated Italian sidecar (kept next to the video); only for that case, after the OpenSubtitles upload. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.2.10.10.26** — Cosmetic: the translation progress bar now appears after the batch warm-up lines instead of before them (TranslateGemma and NLLB). Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.2.09.10.26** — Embedded subtitle selection by content (new `core/subtitle_lang.py`): a track tagged `it` that was not recognised (two-letter code) was translated Italian→Italian and a full subtitle flagged "forced" was ignored in favour of transcribing the audio (RahXephon); "Forced SRT" titled tracks were chosen over the regular one in 3 films of the history. Also: engine model caches (Canary, Qwen3, pyannote…) are no longer wiped at the end of a queue (a 54-minute re-download), switch `model_cache_cleanup_enabled`. Details in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.2** — Transcription profile locked at Maximum, cleaner on-screen log, queue reordering; Spanish sentence-split rules published; per-show glossary engine moved to `glossary_engine/` (benches removed from the repository). (1) `Config.get_transcription_profile()`
  always returns `maximum` while `transcription_profile_locked` is true (default; new installs used to start on Balanced). Measured on 40 min
  of Italian: Whisper 2.9 / 2.3 / 1.9 / 1.8 / 1.5 min per audio hour (Maximum / Quality / Batch / Balanced / Fast) with only 0.1–0.4 % of
  words different from Maximum; Qwen3-ASR 8.7–9.3 min/h with *identical* text at batch 2, 4 and 8, so the profile is useless there; Canary-Qwen
  does not read profiles. The profile cards are hidden (code kept) and the engine group shows typical times per engine. (2) The Diagnostics
  "Model" tile shows the model actually in use (`🧩 Modello trascrizione`, emitted by the pipeline, Whisper after load and the router).
  (3) On-screen log: per-chunk lines (punctuation restore, retried chunks) and loading internals now go to the log file only, with an
  end-of-phase summary; progress bars are always the last line and are rewritten per bar (an interleaved line used to restart them on a new
  line); "Generazione rallentata" shows once per file and the total appears in the "Completato in" line. (4) Queue items still waiting can be
  reordered by drag & drop, also while processing is running. Layout and column sizes are unchanged.
- **v1.30.1 / v1.30.0** — Forced-language retry for Qwen3-ASR and Faster-Whisper (`core/qwen3_lang_retry.py`,
  `core/whisper_lang_retry.py`): both engines forced the declared track language on every chunk, so content in
  another language (English songs inside non-English films, mostly) came back empty or garbled. Suspect
  chunks/segments — and, for Whisper, the *gaps* its own VAD leaves around sung content — are retried with
  language auto-detect and kept only if English is detected (the only language validated against false
  positives on noise). Found and fixed on 9 real X Factor performances; covers both the whole-file and the
  chunked Whisper code paths.
- **v1.29.0** — Spanish routed to Faster-Whisper instead of Qwen3-ASR after a 5-engine bench (Qwen3, Whisper,
  NVIDIA Canary-1B-v2, Cohere Transcribe, HiTZ) on 4 original-language films: no new candidate beat the two
  incumbents on the bench's own pass/fail rule, but Whisper matched Qwen3 on recall with fewer hallucinations
  and much better blocks once combined with sentence-aware splitting (now extended to Spanish too).
- **v1.28.0 / v1.27.0** — Sentence-aware splitting extended to German and French, each confirmed on 8 unseen
  original-language films against professional subtitles (mid-sentence blocks 37-51% → 1-6%).
- **v1.26.0** — French and German routed to fine-tuned Whisper models (`whisper_model_by_language`) instead of
  Qwen3, picked after a 5-engine bench against a proper-noun-heavy reference.
- **v1.25.0** — Non-English sources no longer go through TranslateGemma (fine-tuned English→Italian only, which
  hallucinated or left lines untranslated on other source languages) — automatically routed to NLLB fine-tuned
  instead, in both the main queue and bitmap OCR.
- **v1.24.0** — Multi-file subtitle sync queue + new timing-only alignment engine (`core/timing_aligner.py`):
  100% of rows within 0.5 s on real episodes, ~2 s per episode instead of ~81 minutes; replaced Qwen2.5-14B as
  the default path.

### v1.23.0
- **Sentence-aware splitting of Whisper segments, now on for English and Italian.** faster-whisper used to cut long segments at 80 characters / 6 s regardless of punctuation, so 37-47% of subtitle blocks ended mid-sentence and translation received fragments. The split now prefers sentence boundaries (`core/whisper_sentence_split.py`, options `whisper_split_sentence_aware` and `whisper_split_sentence_langs`, default `["en", "it"]`; other languages keep the original split; `false` restores the previous behavior). Mid-sentence blocks drop to 6-11%, words are identical, and blocks no longer end on articles, prepositions or conjunctions (24.9% -> 2.1% in Italian, checked with an independent spaCy pass). Each language was confirmed on fresh whole files under pre-frozen decision rules (English: 8 files; Italian: 8 new files after a first round exposed a Whisper timestamp glitch inside words, now handled). Caveats: Italian is mostly covered by dubbed films (3 original-Italian files), and the effect on translation was not measured. Evidence, rules and verdicts are in `whisper_split_eval/`.
- **Demucs uses chunked processing above 60 minutes** (was 90): the standard path held four full stems in RAM and could exhaust a 32 GB machine.
- Versions 1.17.0 - 1.22.0 are documented in [CHANGELOG.md](CHANGELOG.md).

### v1.16.0
- **Audio transcription pipeline: 3 real defects diagnosed and fixed on a real film.** Starting point was an actual production output (Goodrich 2024, Italian audio transcribed directly): duplicated lines from overlapping audio chunks, dialogue text attributed to the wrong character, and ~30% of blocks missing punctuation entirely in crosstalk/heated-argument scenes.
  - **Chunker bug** (`core/audio_processor.py`): extending an under-length chunk could physically overlap into the next one, so the ASR transcribed the same line twice with slightly different timestamps. Fixed, plus a final safety net guaranteeing `chunk[i].end <= chunk[i+1].start` by construction. Verified: 12 backward timestamp jumps → 0 on a real rerun.
  - **Confidence gate on the dialogue dash** (`core/subtitle_formatter.py`, `core/diarizer.py`): the "- " dash was assigned purely on gap/length, with no check on how reliable the underlying speaker attribution was — a weak call became a permanent dash on the wrong character's line. New per-segment `speaker_confidence`, gated by a minimum threshold before granting the dash.
  - **Configurable chunk duration with per-engine caps** (`ENGINE_CHUNK_CAP_S`): duration is no longer hardcoded at 20s and is capped per engine (Canary ≤35s, Qwen3 ≤150s, Whisper ≤30s) so it can never exceed what each engine actually supports.
  - **`qwen3_max_new_tokens` fix**: the generation cap was hardcoded at 256, already at the truncation limit on dense 25s chunks. Now 0 = auto-computed from the configured max chunk duration.
  - **Word-level speaker assignment rewrite** (behind `diarization_word_vote_enabled`, still `False` by default — not yet promoted): overlap-weighted voting instead of a midpoint lookup, and an explicit policy for short runs (interjections like "Sì."/"No.") instead of always merging them into the previous run. The historical path is untouched and remains the active default.
  - **New `core/punctuation_restorer.py`** — restores punctuation on ASR chunks that come back with none at all (dedicated model, `oliverguhr/fullstop-punctuation-multilang-large`, CPU-only, structurally guaranteed 1:1 word-to-timestamp mapping). **Promoted to the default** (`punctuation_restore_mode='missing'`) after targeted validation on 22 hand-written sample sentences (the word-count invariant held in every case; only one case altered the sentence's meaning). Known limitation: the model can never emit "!" — a fixed set of training labels, not a bug.
  - **Pyannote clustering threshold promoted to default** (`diarization_clustering_threshold=0.85`, vs. the model publisher's own calibrated 0.7046): measurably reduces over-clustering (27→12 detected "speakers") in a dedicated tuning campaign — new reusable bench **`diar_eval/`** (`diar_bench.py` + `metrics.py`; prepare/run/gold-make/gold-score/sweep-c subcommands), scored against 50 hand-labeled audio pairs. **Honest caveat**: a later recheck found the aggregate-metric signal was statistically weak (not significant, McNemar p=1.00, on a sample of that size) — this stays a deliberate call, not a decisive result, and is the first thing to revisit if over-merging symptoms show up on a different film genre.
  - Three bugs the user found firsthand while hand-labeling the gold set (a context margin that bled a second voice into an adjacent-turn clip, 17ms pyannote micro-turns sampled by mistake, and CSV parsing that broke on files re-saved by Excel in an Italian locale) — all fixed in `diar_eval/diar_bench.py`.

### v1.15.0
- **Correction to v1.14.0's diagnosis, and the real fix — credit to a user who questioned it.** The PAL/NTSC note below states the sync feature "doesn't detect progressive drift." That framing was wrong, and disproven with the same kind of empirical test that had been used to justify it: the user pointed out that anchors are per-line, real timestamps pulled straight from *this* video's own embedded track (or a Whisper transcription of its audio) — not a global offset or scale factor computed once and applied everywhere. If Qwen matches an external line to the right anchor, the timestamp it gets is that anchor's true value for that exact moment, regardless of how far the external file's *own* original timing had drifted. Reproduced with a semantically-perfect matcher (zero hallucinations) against a simulated PAL-drifted file: with the plausibility gate's offset check disabled, **100% exact, 0.0s max error** — the per-line matching was never the problem. The actual cause was the gate itself (added in the two rounds behind v1.14.0): it compared every candidate timestamp against the external line's *original* (increasingly wrong, on a drifted file) position, so it rejected correct anchor-matches late in the film as "implausible," and the window capture logic never even proposed 65% of late-film lines to the right window in the first place — both anchored to the same flawed reference.
  - **Fix**: the gate and the capture window now compare against a *learned* expected position instead of the raw original one — a linear model (`shift(t) = a·t + b`, fit via Theil-Sen — a median-of-pairwise-slopes method, robust to the exact kind of noisy outliers a wrong match would introduce) built from the matches already accepted, refined window by window as the film progresses. A mandatory quality gate (residuals ≤2s, ≥60% inliers) means a bad fit — e.g. under a heavy hallucination rate — leaves the model at its default (a=0, b=0), which is byte-for-byte the old behavior; verified this doesn't regress a file with no drift and 100% hallucinated matches. On the same simulated PAL file (0% hallucination, isolating drift as the only variable): 100% exact, 0.0s max error, and the model correctly recovered a slope of 0.0427 — the real 25/23.976 PAL/film ratio.
  - The lesson generalizes past this one bug: a "detect and reject implausible values" safety net is only as good as what it's compared against — comparing against a stale or already-wrong reference makes it reject the *correct* answer instead of the *wrong* one, and no amount of re-testing the rejection logic in isolation would have caught that, only questioning what it was being compared to.

### v1.14.0
- **Subtitle Synchronization ("Anchor & Match"): from "never validated" to a verified correctness guarantee, in two review rounds.** The feature — align an out-of-sync external Italian `.srt` to the correct timestamps from a video's embedded subtitles or a Whisper transcription, semantically matched via a local Qwen2.5-14B — had never been exercised end to end. A first bugcheck found 15 defects, the worst of which (four compounding bugs) silently produced a **wrong output SRT in 50% of rows** on a simulated full-length film, with no error and a "completed" message. Fixed and verified (100% exact on the same simulation) in a first pass, but a second review round found the fix for the worst bug was only *partial* — measured at 22% of rows still wrong, because the merge criterion relied on the LLM's self-reported confidence, which real inference showed is almost always ≈1.0 even on wrong matches. The real fix is a **global offset gate**: no row can be moved further than a configurable `sync_max_offset_sec` from its original position, regardless of what the model claims — the third review round found this gate had a wide-open bypass for the "split one external into two anchors" case (up to 176s of error) and fixed it, verified on a real 794-line episode with zero inverted or overlapping cues and every error bounded by the configured tolerance.
  - Root defect: overlapping matching windows resolved each external independently and "first window wins" — a row borrowed by the wrong window (its real anchor was in the next one) got a positional guess restricted to the wrong window's anchors, tens of seconds off, silently.
  - The positional fallback itself was a second bug: for the handful of rows never resolved by the LLM, it spread them by index ratio over the *entire* film instead of interpolating from resolved neighbors — with a single unresolved row, the ratio (`0/max(0,1)=0`) always sent it to the very start of the file.
  - The "split one line into two" path was dead code: a shortcut that trusted the LLM's own timestamps (forced non-null by the JSON grammar) meant both halves of a split always received *identical* timestamps, which a downstream formatter step then silently merged into one line, losing a caption outright. That formatter step (borrowed from a different feature, meant to merge/reflow/clean aligner output) has been removed from this path entirely: the contract here is "change only the timing," and it was also stripping user line breaks, dialogue dashes and italics tags.
  - Gender correction on the synchronized file was a no-op that reported success: the subprocess call was missing `video_path`, the one field the corrector actually needs to build a speaker map from audio.
  - The anchor's source language was never detected past a fixed default; the language-matching logic itself had false positives/negatives (a Polish track could be picked up as Portuguese). Fixing this exposed — and required fixing — a second issue: some real-world language tags (`pob`, `pt-BR`, `en-US`) aren't recognized by the translator at all, so naively passing them through made the whole synchronization fail outright instead of just mistranslating; a canonicalization step with a fallback closes that.
  - A window-generation off-by-a-constant could leave the last 1-2 subtitles of a file (~11% of files, by anchor count) never proposed to the model at all.
  - Two real UI bugs fixed alongside: the completion dialog could show a file path that didn't exist (computed from the video path instead of the actual output path, which follows the external SRT's location); closing the dialog with Esc bypassed the cancellation logic entirely, and — found in the final review pass — the close-button path and Esc could both fire the same 30-second shutdown wait, freezing the window for up to a minute.
  - Synchronization and the transcription queue / glossary tool now refuse to run at the same time (all three load large models onto the same GPU).
  - **Known limit, not yet addressed**: progressive drift across a file (the classic PAL/NTSC 25↔23.976fps mismatch, where desync grows continuously instead of staying constant) is not detected — measured at ~79% of rows ending up outside tolerance on such a file. The gate correctly refuses to guess past its configured tolerance rather than producing confident garbage, and now logs a loud warning naming `sync_max_offset_sec` when that happens, but this is a design gap, not a bug fix away.
  - Also known and deferred: the whole pipeline still loads NLLB + Whisper + Qwen-14B inside the GUI process instead of an isolated subprocess (this project's convention for exactly this reason), and cancellation can't interrupt a single in-flight model call.

### v1.13.0
- **OpenSubtitles upload actually works now — verified with 4 real uploads, first time ever in this project.** The feature existed since v3.8 and had never once succeeded end to end; two full bugcheck passes plus live testing against the real API found and fixed a chain of independent defects:
  - **Root cause of every upload failing outright**: the XML-RPC uploader compressed `subcontent` with **gzip**; the protocol expects **zlib**. The server decompressed to an empty string every time, which produced both "SubHashes do not match" and "invalid subtitle format" from a single cause, not two. `utils/opensubtitles_xmlrpc_uploader.py` now uses `zlib.compress`.
  - **opensubtitles.org and opensubtitles.com are separate accounts with separate credentials**, even under the same username — the app only ever had one credential slot. A misdiagnosis inherited from old code attributed XML-RPC's `401 Unauthorized` to an unregistered User-Agent (a manual registration process that stopped being available in 2022) instead of the real cause: `.com` credentials being used against the `.org` login. New dedicated `opensubtitles_xmlrpc_username`/`_password` config keys and Settings fields, separate from the existing `.com`/REST ones; `authenticate()` now reports the real "wrong credentials for this account" error.
  - **The REST API's `/upload` endpoint used by the code didn't exist** (404 — a made-up path, not what OpenSubtitles wrongly rejected). The real path, `/api/v1/subtitles/upload`, returns `403 uploads_not_enabled` for ordinary API keys — the feature is opt-in and needs OpenSubtitles to whitelist the key on request. Endpoint constant fixed for when that's granted; REST is no longer the default upload path (XML-RPC is, since it's the one that actually works today) and the automatic REST fallback on XML-RPC failure was removed (it could never have helped: REST can't upload for this API key regardless of the XML-RPC outcome).
  - **A wrong IMDb ID for TV episodes** — only the *series* IMDb ID was ever resolved; uploads for individual episodes need the episode-specific one when available. `utils/tmdb_client.py` now looks it up via TMDB's per-episode `external_ids` and falls back to the series ID when an episode entry doesn't exist.
  - **Wrong subtitle language uploaded for 5 languages** — a naive reverse-lookup dict comprehension picked the wrong ISO 639-2 form depending on declaration order; German, Dutch, Czech, Romanian and Greek were affected, worst case Romanian (`rum`) silently slicing to `ru` — **Russian**. Replaced with an explicit, unambiguous mapping table; the REST language-code translator now returns `None` instead of guessing on an unmapped code, and the caller aborts the upload rather than send a wrong language.
  - **App-crashing bug**: "Test Connection" with incomplete credentials raised an unhandled `AttributeError` outside the method's own `try/except`, taking down the whole process.
  - Removed three dead/misleading modules (`opensubtitles_client.py`, `opensubtitles_integration.py`, `opensubtitles_config.py`) — one of them silently returned "success" from a `# TODO: implement this` stub without ever calling any API, the kind of file that actively misleads whoever reads it next.
  - Several more: a settings dialog that wiped just-typed, unsaved credentials when switching API method; a stale tooltip contradicting the new default; a credentials-check used by the separate "OpenSubtitles AI" translator that had drifted to accept upload-only credentials; a duplicate-database check re-doing the work XML-RPC's own upload call already does internally.
- **Process note**: live-testing an unfixed code path against the real OpenSubtitles API produced one unintended side effect — an early diagnostic call published a subtitle for one episode anonymously, with the raw (BOM/CRLF, unstripped promotional line) file content, before the pipeline's actual cleaning step was involved. It sits alongside the correct, properly-attributed upload for the same episode; it isn't fixable from our side (no account is attached to it) and needs a report to OpenSubtitles to remove. A reminder that live experimentation against a real third-party API — even to "just isolate a variable" — can leave a public trace, not only pass/fail output.

### v1.12.2
- **Per-show glossary tool: fixed wrong TMDB ID silently written on Plex-style libraries (`V:\Show\Season N\...`)** — when the folder picked in the "Per-show glossary" dialog was the *season* subfolder rather than the show folder, its name ("Season 2") degraded to "Season" through filename parsing and matched an unrelated TMDB result — a wrong `tmdb_id` written into the glossary with no warning. The dialog now recognizes season/specials-style folder names in several languages, and derives a real title candidate list (parent folder name, then the show name parsed from the first episode file found) before ever calling `search_tv()`.
- **Fix: orphaned GPU subprocess left ~9GB resident in VRAM after cancelling the glossary builder** — the Qwen channel launches its GPU-side pass as a subprocess on the main venv (bridged from the tool's own isolated `venv_glossary`); cancelling only terminated the direct child, which on Windows doesn't propagate to a subprocess's own descendants. Now tracks the GPU subprocess's PID and kills the whole process tree (`taskkill /T`) on cancel.
- **Glossary tool and the main transcription/translation queue are now mutually exclusive** — both can use the GPU; running one while the other starts would contend for the same VRAM. Each now refuses to start while the other is active, with a clear message instead of silent slowdown or an OOM.
- `qwen_n_gpu_layers` is now a configurable per-show setting for the glossary builder's Qwen channel (previously hardcoded).

### v1.12.1
- **Adaptive batch manager: don't shrink the batch when the memory pressure isn't ours** — measured on a real run (two NLLB translations launched in parallel): memory jumped from 50% to 85% while our own batch stayed at 24, and the manager reduced it anyway — reducing a batch doesn't free memory another process is holding, and measurably made things 62% slower per sentence (0.271s → 0.438s). New `_external_pressure_gb()` compares `torch.cuda.memory_reserved()` (this process's own allocation) against total used memory; when the gap exceeds 1.5GB the manager holds size and logs a warning instead of shrinking. **A real bug was found and fixed in this same guard during review**: it only sampled pressure inside the `mem > high_threshold` branch, so on a file that starts clean and hits contention mid-run, the *first* sample already lands during the contention and gets recorded as the baseline — pressure reads as zero and the guard is inert on exactly the case it exists for. Fixed by sampling every batch.
- **Time-based throughput guard (ms/token), the closest thing to an OOM signal Windows/WDDM actually gives us** — checked the full log history: zero real OOM events have ever fired in production, because WDDM silently pages VRAM overflow into system RAM instead of raising a CUDA error. The only real signature is generation time climbing. Added to both the NLLB and LLM branches: tracks the best-observed ms/token (or ms/char for the LLM branch, which returns text, not tensors) for the file and logs one warning if a batch runs ≥2× slower — deliberately observability-only, not an automatic reaction, since reducing batch size under *external* contention doesn't help (see above).
- **Multiplicative batch growth instead of +1** — measured 9 batches wasted recovering from 16 to 24 one step at a time after contention cleared, at reduced throughput the whole time, on memory readings that had already confirmed real headroom.
- **Root-cause data**: an artifact-published analysis of 875 real batches across 23 runs found the existing 85% reduction threshold is itself well-calibrated (93% recall at a lower threshold came from a confounded sample — most "degraded" batches in that set were from contended parallel runs where shrinking made things worse, not better) — so the threshold itself was left untouched; the actual fix was giving the manager a way to tell contention apart from its own legitimate memory use.

### v1.12.0
- **Fix: subtitle lines silently left in English when a glossary-mask placeholder wasn't reproduced verbatim** — the LLM branch's `logger.warning` for this case never reached the log file or the screen (a bare `logging.getLogger()` call, the same class of bug already fixed for the batch manager in v1.11.0, here undiscovered because nobody had reason to look until real episodes showed English lines with no trace of a failure anywhere). Replaced the single "unmask fails → keep English" fallback with a five-level recovery chain, shared by both the NLLB and LLM branches: tolerant unmask repair (fixes a placeholder mangled by the model — stray spaces, wrong case, a missing bracket); a masking-free retry on the still-loaded primary engine (removes the actual failure cause — the synthetic token — instead of resending the input that already failed); a one-shot swap to a secondary "reservoir" engine for whatever survives, deduplicated by source text so a repeated line isn't retranslated twice; and, only if all of that fails, English with a loud, visible warning instead of a silent one. An independent audit closes every file regardless of cause: a source/output identity check flags anything still untranslated, so a future failure mode nobody anticipated still surfaces instead of vanishing. Verified on a real episode with an active per-show glossary (all 24 previously-silent English lines resolved or became visible failures) and on a 21-file production batch (20 episodes with a glossary + 1 without, as a no-regression control).
- **Reservoir engine chosen from a measurement, not an assumption** — a head-to-head GEMBA-MQM evaluation (Qwen2.5-14B vs. NLLB fine-tuned, 39 short glossary-heavy lines from 4 shows) found NLLB-FT decisively ahead (64% vs. 26% preferred, weighted MQM 1.41 vs. 4.31); Qwen produced real grammar errors and one outright hallucination. The reservoir now defaults to whichever engine differs from whatever is already the primary translator (NLLB fine-tuned when the primary is the LLM branch, Qwen when the primary is NLLB — never a second attempt with the same model that already failed twice), configurable via the new `reservoir_engine` config key.
- **Eight further bugs found and fixed during implementation review**, among them: a call to a method (`_apply_fallback`) that was never defined anywhere in the project, which turned any single empty LLM output into a crash of the *entire* file's translation; a validated-but-still-unusable LLM retry output silently overwriting the first attempt; glossary post-hoc replacement stopping after the first occurrence of a term repeated in the same line; a duplicated-batch bug in the NLLB branch's own error-retry path (pre-existing, unrelated to this fix, found while reviewing the same code); and a missing subprocess timeout on the reservoir process.

### v1.11.0.4.9.26
- **Fix: RAM leak in the per-show glossary align phase** — `glossary_align.unload()` only released Python references (`gc.collect` + `torch.cuda.empty_cache`), never returning the `venv_glossary` process's working set to the OS: the RAM used by LaBSE during alignment stayed resident through the whole subsequent Qwen/GPU phase. Fixed with the same `EmptyWorkingSet` trim already used in `utils/resource_monitor.py`, reimplemented inline since `venv_glossary` has no `psutil`.

### v1.11.0
- **Per-show glossary builder (semi-automatic)** — new `Tools → Per-show glossary` dialog finds candidate terms translated inconsistently across a show and proposes a fixed rendering, cross-checked by two independent channels (SimAlign+LaBSE word alignment + a local Qwen span-extraction pass, mechanically validated rather than trusted as a judge) instead of a single verbatim/absent heuristic that overstated real defects. Runs isolated in a new `venv_glossary/` (conflicts with the main venv's `transformers==4.57.6`); the GPU-side Qwen channel is delegated back to the main venv via a bridge subprocess. Review UI with per-term approve/reject cards and merge-not-overwrite save.
- **2nd-person addressee resolution fix** — `addressee_gender_for_range()` discarded a cue for *any* isolated third speaker anywhere in the ±8 s window, even when irrelevant to the conversation (measured on Knight's & Magic: 5/7 P2 candidates blocked this way vs. 1/7 from a true strict prev/next check). New shared `_resolve_addressee()`: real ambiguity is direct temporal overlap with the cue, not the mere presence of a third speaker elsewhere. P2 coverage 0/7 → 1/7 with `strict=True` (production setting unchanged).
- **Production LLM translator: LoRA adapter + custom model path support** — `llm_subtitle_translator` can now load a LoRA adapter and a local model path (config + UI + `translator.py`); the queue log now records which translation engine produced each file.
- **Fix: adaptive batch manager logger silently dropped info-level logs** — a bare `logging.getLogger()` call in `adaptive_batch_manager` discarded them before they reached the shared log file.

### v1.10.1.22.8.26
- **Fix: production LLM model cache wiped at the end of every queue** — the LLM model occupying the production slot (currently TranslateGemma-12B) was downloaded into the HuggingFace cache and then deleted again once the queue finished: the preserve list only covered the ASR engines (whisper/wav2vec), not the LLM translation branch. The fine-tuned LoRA adapter promoted to production was unaffected (it lives on disk outside the HF cache). The cleaner now resolves at runtime which model occupies the slot (config key `llm_translator_model`) and preserves it; models used only for experimental comparisons are still cleaned up as before.

### v1.10.1
- **Removed the LLM branch's "adapt" path: it could misalign lines and timestamps** — the LLM branch queried the model two ways: "mt" (one line per conversation, the output is the translation directly) and "adapt" (a batch of blocks as JSON with ids, which the model had to return intact). Below a certain size, models got the ids wrong — merging two blocks and writing subsequent translations under the wrong id, with timestamps still correct, so the file looked healthy but wasn't. The path had become unreachable from the UI after Aya's removal (v1.10.0) and risked being inherited by default by any future model added without explicitly opting out of it. Removed entirely; only "mt" remains, immune to the issue by construction.

### v1.10.0
- **LLM translation engine rewritten, TranslateGemma-12B replaces Aya** — the LLM branch is now a model-agnostic package with a model registry, fixing four long-standing defects (prompt without chat template, padding that corrupted batches, the second line of a dialogue block getting discarded, an English fallback). Evaluated on a synthetic benchmark and then on real films with professional subtitles as reference (Deadpool 2, A Man Called Otto): the verdict flips from the synthetic benchmark — **NLLB fine-tuned remains the production engine**, ahead of both TranslateGemma-12B and Aya. Aya removed from the registry.
- **Critical bug found by exercising the pipeline's real code path for the first time** — NLLB was translating the context (the film's plot synopsis) instead of the actual line, invisible until the context started actually being passed through.
- **US-convention music markers hallucinated 48 times out of 48** — `**text**` wasn't protected the way `♪text♪` was; any block with no letters at all is now passed through untouched.
- **Shared typographic post-processing** across every engine: out-of-spec lines dropped from 59.3% to 9.7%.
- `.gitignore`: closed four ~12 GB leaks the `venv/` pattern didn't cover.

### v1.9.7
- **Dialogue line-merge fix** — NLLB doesn't reliably preserve the embedded newline when translating a two-speaker dialogue block (dashed lines): it sometimes merged both lines into one, and sometimes even inserted its own spurious dashes, producing blocks like "- I wish you were here. Me too." instead of two correctly attributed lines. Dialogue blocks (identified by the already-tracked "- " dash markers) are now translated line by line instead of as a single joined string, guaranteeing by construction that the post-translation line count always matches the original.

### v1.9.6
- **Critical fix: NLLB source language ignored for every language but English** — the NLLB tokenizer requires `tokenizer.src_lang` to be set on every call to correctly tag the input text's language. This was never set and stayed pinned at whatever default was loaded at `from_pretrained()` time (`eng_Latn`) — any translation with a non-English source (German, French, Spanish, Russian, etc.) was tokenized as if the text were English, causing sentences to be left untranslated or hallucinated. Verified empirically on a sample of German sentences: 5/10 untranslated without the fix, 0/10 with it applied. The bug had been present since the NLLB module was introduced and affected every non-English-source translation.
- **Minor fixes (file naming and gender correction on .srt input)** — when the pipeline input was already a `.srt` file with a language code in its name (e.g. `Movie.en.srt`), the final output filename no longer correctly contained only the target language (`Movie.en.it.srt` instead of `Movie.it.srt`). Gender correction (STEP 6.5) also failed when the input was already a `.srt`: it tried to extract audio via ffmpeg directly from the subtitle file instead of resolving the real corresponding video in the same folder.

### v1.9.5
- **Adaptive translation batch fix, take two** — v1.9.3's static per-class batch ceiling (NLLB `max_size=24`) still allowed sustained shared-RAM spillover in some real-world runs, and it wasn't tied to source language as first suspected: it was two gaps in the batch manager's reactive logic. (1) During warm-up the manager only ever *grew* the batch size — it never checked memory pressure to shrink it, so on short files (most translation jobs run in under 10 batches) the whole file could complete while pinned at an oversized batch with GPU memory saturated. (2) `torch.cuda.empty_cache()` only ran on a fixed 10-batch cadence, which those same short files never reached, so PyTorch's caching allocator never released memory back to the driver. Both are now reactive to the live memory reading at every batch, warm-up included. Verified on the exact file that triggered the original report: translation step dropped from 800 s (13 m 13 s) with 2.44 GB sustained shared-memory spillover to 196 s (3 m 16 s) with only a ~19 s transient blip.

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
- **Evaluation harness** (`gender_eval/`, local only — not published in this repository) — MT-GenEval benchmark, automatic ground-truth extraction from dual-track professional subtitles (~700 test points, zero manual annotation), engine comparison, A/B episode runner.
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

---

# Italiano

## Changelog

> **Nota sul repository:** qui si pubblica solo il codice attivo. I banchi di prova e gli strumenti di valutazione citati sotto
> (`mt_eval/`, `asr_eval/`, `whisper_split_eval/`, `split_eval/`, `gender_eval/`, `diar_eval/`, `Gemma training/`) restano nella cartella
> di lavoro dell'autore e non fanno parte del repository. Il motore del Glossario per show, che stava in `mt_eval/`, ora è in `glossary_engine/`.

### v1.24.0 - v1.30.2
Sei settimane di lavoro sulla qualità di traduzione/trascrizione per le sorgenti non inglesi, condensate qui; il
dettaglio completo, la metodologia di misura e le regole di decisione per ogni affermazione sono in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.41** — Client, logica delle righe e azioni di importazione/OCR/Superpower del Library Scanner spostati fuori dalla GUI (`core/services/`, senza Qt): GUI e comportamento invariati (verificato su Windows con un server vero e uno finto), base per una futura web UI. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.40** — Logica di revisione OCR, profilo di trascrizione e dialogo del modello di traduzione spostata fuori dalla GUI (`core/jobs/`, `core/services/`, senza Qt): GUI e comportamento invariati (verificato con file PGS/VobSub reali: SRT e MKV con mux identici), base per una futura web UI. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.39** — Logica di Sync SRT e Glossario spostata fuori dalla GUI (`core/jobs/`, `core/services/`, senza Qt): GUI e comportamento invariati (verificato con file reali: SRT sincronizzato e risultati della coda identici), base per una futura web UI. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.38** — Logica di impostazioni, cronologia e metadati spostata fuori dalla GUI (`core/services/`, senza Qt): GUI e comportamento invariati, base per una futura web UI. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.37** — Refactoring della coda: un solo motore (`core/jobs/`) per la GUI e per la coda headless; GUI invariata, la coda headless ora logga come la GUI, scrive la cronologia e l'anteprima dei passi. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.36** — Soglia di IQ3_M abbassata a 7,3 GiB di VRAM libera (misura su una RTX 3060 limitata a 7,3 GiB): le schede da 8 GB restano sul percorso GGUF. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.34** — Correzioni dalla prima validazione su una vera GPU AMD (Linux/ROCm); la traduzione non è più dichiarata riuscita quando la maggior parte dei blocchi resta non tradotta. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.33** — Auto-detect della lingua con voto su più chunk; attesa che la VRAM degli ASR sia liberata prima della traduzione su GPU; barra di avanzamento ed ETA per la correzione genere v2. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.32** — Installer GGUF: ripristinati i messaggi tradotti, sostituisce i file solo se lo SHA-256 differisce; nuovo test su tutte le chiavi tr()/_tr(). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.31** — Percorso GGUF di TranslateGemma acceso di default (Q4_K_M su schede da 12-20 GB, IQ3_M su 8-12 GB, ripiego automatico su NF4); l'installer scarica i file GGUF. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.30** — Correzione urgente: l'app non partiva su Windows (PyQt6 veniva importato prima di onnxruntime dal rilevamento lingua). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.29** — Il traduttore GGUF ora gira in un sottoprocesso pulito (corregge il crash su Windows); banco di qualità: Q4_K_M/Q3_K_M/IQ3_M non inferiori a NF4 e ~14 volte più veloci; file GGUF pubblicati su Hugging Face. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.28** — Percorso GGUF: corretto un crash su Windows (`llama_supports_gpu_offload` prima dell'inizializzazione del backend). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.27** — Percorso GGUF di TranslateGemma per schede da 8-12 GB e AMD/Vulkan (codice pronto, SPENTO di default fino al banco di qualità). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.26** — Traduzione dell'interfaccia (fase B): le righe di log della pipeline seguono la lingua dell'interfaccia (sessione cloud, PR #8-#13). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.25** — Traduzione dell'interfaccia (fase A): circa 120 testi che erano solo in italiano ora seguono la lingua dell'interfaccia. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.24** — I nomi delle lingue e le schede della coda ora seguono la lingua dell'interfaccia. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.23** — "Forza trascrizione audio" aggiunto alle opzioni per file del menu contestuale della coda. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.22** — Opzioni job predefinite spostate in Impostazioni (scheda "Opzioni job"); il pannello principale tiene un riepilogo di una riga e la casella di spegnimento, liberando spazio per la coda e il Library Scanner. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.21** — Opzioni job per file dal menu contestuale della coda (lingua sottotitoli, motore di traduzione, correzione genere, mux, upload OpenSubtitles, revisione OCR) e selezione multipla. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.20** — Scheda grafica rilevata mostrata sotto la pillola di stato: verde per NVIDIA, rossa per AMD, "Solo CPU" se non c'è una GPU compatibile. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.19** — Installer: con `--no-gpu`/`-NoGpu` un download fallito della ruota CPU ora si ferma con un messaggio chiaro invece di ripiegare sulle ruote CUDA; integrato il lavoro Linux/AMD della sessione cloud. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.18** — Si può togliere dalla coda un file in attesa mentre se ne elabora un altro (tasto Canc o menu contestuale); un file già in elaborazione non può più essere accodato una seconda volta. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.17** — Rilevamento GPU multi-fornitore (`utils/gpu_detect.py`, Windows e Linux; NVIDIA, AMD, Intel; backend CUDA/ROCm/Vulkan). Non verificato su hardware AMD/Intel reale. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.16** — Linux (non verificato): `install.sh --with-models --qwen-size=auto|7b|14b` scarica Qwen 14B/7B e NLLB fine-tuned, come l'installer Windows. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.15** — Qwen2.5-7B è ora il ripiego automatico per le GPU sotto i 12 GB (costruzione del glossario e serbatoio L3); il 14B resta il predefinito e un percorso modello impostato esplicitamente si comporta come prima. Opzione dell'installer `-QwenSize`. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.14** — Licenza: aggiunti `LICENSE` e `NOTICE.md`, rimossa la chiave TMDB scritta nel sorgente (ora `tmdb_api.txt` / `TMDB_API_KEY`), rimossi i file di prova con film di terzi. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.13** — Linux fase 3 (NON VERIFICATA su una vera macchina Linux): `install.sh`/`run.sh`, mappatura delle cartelle montate del Library Scanner, self-check portabile, `notify-send`. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.12** — Installazione su PC pulito: gli strumenti esterni (Tesseract, MKVToolNix) si trovano anche fuori dal PATH, `-NoGpu` installa torch CPU, corretto l'indirizzo predefinito del Library Scanner. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.11** — Installer: con `-NoGpu` installa la ruota CPU di llama-cpp-python (quella CUDA non si carica senza il driver NVIDIA). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.10** — Installer: con `-InstallSystemDeps` ora scarica da solo i dati lingua `ita`/`eng` di Tesseract (copia con UAC se la cartella è di sistema). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.9** — Compatibilità Linux, fase 3a: fuori da Windows, i percorsi con lettera di unità salvati in una config copiata vengono ignorati a favore dei predefiniti (nessun cambiamento su Windows). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.8** — Compatibilità Linux, fase 1b: anche il ponte Qwen del motore glossario usa `utils/platform_compat.py` (valori identici su Windows). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.7** — Compatibilità Linux, fase 1: i punti noti specifici di Windows passano da `utils/platform_compat.py` (valori identici su Windows; l'annullo del glossario usa psutil invece di `taskkill`). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.6** — Compatibilità Linux, fase 0: nuovo helper `utils/platform_compat.py` (nessun cambiamento di comportamento su Windows). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.5** — Il Log Sintetico è attivo di default all'avvio. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.4** — Scheda dei passi: niente ETA obsoleta quando un motore riporta 100%. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.3** — UI: pulsanti Avvia / Ferma più sottili (più spazio per la coda e il Library Scanner). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.2** — Scheda dei passi: trascrizione e traduzione restano al 99% finché non parte il passo successivo (diarization / recupero ancora in corso). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.1** — ETA della correzione genere mostrata nella scheda dei passi. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.34.0** — ETA dei motori (trascrizione, Demucs, traduzione NLLB/API) nella scheda dei passi; barra di avanzamento reale per il percorso Demucs standard. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.4** — UI: la scheda dei passi mostra l'ETA propria del motore di traduzione (niente soglie 3% / 20 s). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.3** — UI: avanzamento OCR e statistiche del Library Scanner condividono una riga (circa 28 px in più per la lista). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.2** — UI: pulsanti del Library Scanner più sottili (Importa tutti i filtrati / Superpotere), più spazio per la lista. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.1** — UI: la scheda "Pipeline in corso" resta dopo la fine della coda e viene rigenerata dal file successivo. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.33.0** — UI: con il Log Sintetico attivo, una scheda "Pipeline in corso" elenca ogni passo del file corrente (fatto / attivo con percentuale, ETA e barra / in attesa / disattivato / non necessario); ETA di Demucs nel log. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.32.3** — UI: contrasto AA dei badge dello scanner, badge dei formati non più tagliati, i pulsanti non tengono più il focus dopo un clic, rimossi 16 token inutilizzati. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.32.2** — UI: intestazioni delle schede più sottili; con il Library Scanner aperto, la coda e la tabella dello scanner si dividono lo spazio verticale libero. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.32.1** — UI: cifre degli spinbox non più tagliate, Library Scanner compatto (filtri su una riga, lista più alta), caselle delle opzioni job più piccole in una griglia 2x2 allineata. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.32.0** — Rifinitura UI: contrasto AA, emoji duplicate tolte accanto alle icone, barra di avanzamento a capsula con etichetta percentuale separata, icone SVG dei controlli, dialog allineati alla palette, tre difetti di layout preesistenti corretti. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.31.1** — Logica della UI separata dalla vista (`gui/services/`: coda, metadati, opzioni job, impostazioni, filtro log); corregge un crash premendo Avvia con glossario o sync in corso. 216 test + banco visivo. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.31.0** — Fondamenta della UI: design token (`gui/design_tokens.py`), tema QSS generato da un modello, componenti riusabili e modelli di stile per dialog; rimossi ~145 colori scritti nel codice e ~45 fogli di stile sparsi con resa identica al pixel (banco visivo). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.13** — Upload di anime su OpenSubtitles: quando TMDB non ha l'IMDb ID dell'episodio, lo si cerca su OMDb per titolo esatto e univoco dell'episodio, così più episodi sono associati alla propria pagina invece che a "senza categoria". Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.12** — I blocchi di sottotitolo con tempi di inizio fuori ordine (14 su 654 sidecar propri) ora li ordina il cleaner, e il controllo del mux confronta le righe come insieme, quindi "Muxa nel video" non li rifiuta più. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.11** — "Muxa nel video" ora funziona sugli MKV con stream mjpeg di copertina/allegato (ripiego su mkvmerge se ffmpeg fallisce, più un controllo che sia stata sostituita solo la traccia sottotitoli prevista); corretto il mojibake residuo; banco esteso (mux mjpeg, ETA con Canary/Whisper, OCR fallito con ripiego sull'audio). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.10** — Corretto il mojibake nel sorgente (emoji e accenti di log/effetti), `output` riportato per gli episodi OCR, l'OCR bitmap multi-traccia in pipeline ora scrive un solo sidecar e lascia intatto l'MKV. Banco 13/13. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.9** — Completato il refactor interno: selezione sottotitoli/OCR (STEP 0/1/1b) spostata fuori da `process()`, comportamento invariato (9/9 casi del banco). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.8** — Refactor interno: `process()` suddiviso in metodi privati per passo, comportamento invariato (9/9 casi del banco, tracce identiche). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.7** — La pipeline ora riporta cosa sta facendo con eventi strutturati accanto al log testuale (opzionale con `TP_EVENTS=1`, parsing del testo mantenuto come ripiego); l'avanzamento per file non dipende più dalle parole del log. Validato su clip reali (9/9). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.6** — Una traccia sottotitolo bitmap (PGS/VobSub) marcata italiana ma con un'altra lingua ora viene sostituita nell'MKV dal sidecar italiano dopo OCR + traduzione; corretto un `UnboundLocalError` che faceva ripiegare in silenzio l'OCR sulla trascrizione audio quando la lingua del contenuto veniva corretta. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.5** — Coda headless (`python -m core.queue_runner <cartella>`) con un `queue_status.json` aggiornato in tempo reale; l'ETA di trascrizione si arrotonda al minuto più vicino. Validata su clip reali con un banco (fuori dal repository). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.4.15.10.26** — Protezione contro la riscrittura del video da parte di un altro programma (es. FileFlows) durante un job: upload e remux in-place vengono saltati se dimensione/data sono cambiate. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.4** — L'avanzamento per file (riga della coda e barra della locandina) segue la durata reale di ogni fase invece di una tabella di passi fissa: niente più blocco al 60% in trascrizione o all'88% in traduzione. L'OCR+traduzione ora mostra le sue barre di avanzamento. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.3.15.10.26** — La barra di trascrizione mostra il tempo stimato rimanente (Qwen3, Canary, Whisper); il percorso a file singolo di Whisper ora riporta l'avanzamento reale. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.3.14.10.26** — Estetico: le barre di avanzamento nel log del dialog di sincronizzazione si riscrivono sul posto come nel log principale. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.3** — Nuova opzione job "Muxa nel video" (scheda Opzioni job, accanto all'upload OpenSubtitles): il sottotitolo creato dal job viene aggiunto all'MKV come nuova traccia dopo l'upload; l'`.srt` resta accanto al video. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.2.11.10.26** — Una traccia testo embedded marcata italiana ma con contenuto in un'altra lingua (es. inglese marcato `ita`) viene sostituita nell'MKV dal sidecar italiano generato (conservato accanto al video); solo per quel caso, dopo l'upload su OpenSubtitles. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.2.10.10.26** — Estetico: la barra di avanzamento della traduzione ora compare dopo le righe di riscaldamento dei batch invece che prima (TranslateGemma e NLLB). Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.2.09.10.26** — Selezione dei sottotitoli embedded per contenuto (nuovo `core/subtitle_lang.py`): una traccia marcata `it` non riconosciuta (codice a due lettere) veniva tradotta italiano→italiano e un sottotitolo completo marcato "forced" veniva ignorato a favore della trascrizione dell'audio (RahXephon); tracce con titolo "Forced SRT" erano scelte al posto di quella normale in 3 film dello storico. Inoltre: le cache dei modelli dei motori (Canary, Qwen3, pyannote…) non vengono più cancellate a fine coda (un nuovo download di 54 minuti), interruttore `model_cache_cleanup_enabled`. Dettagli in [CHANGELOG.md](CHANGELOG.md).
- **v1.30.2** — Profilo di trascrizione bloccato su Massimo, log a schermo più pulito, riordino della coda; pubblicate le regole dello split per frasi in spagnolo; motore del Glossario per show spostato in `glossary_engine/` (banchi rimossi dal repository). (1) `Config.get_transcription_profile()`
  restituisce sempre `maximum` finché `transcription_profile_locked` è true (default; le nuove installazioni partivano da Bilanciato). Misurato su
  40 min di italiano: Whisper 2,9 / 2,3 / 1,9 / 1,8 / 1,5 min per ora di audio (Massimo / Alta qualità / Batch / Bilanciato / Veloce) con solo lo
  0,1–0,4 % di parole diverse dal Massimo; Qwen3-ASR 8,7–9,3 min/h con testo *identico* a batch 2, 4 e 8, quindi il profilo lì non serve;
  Canary-Qwen non legge i profili. Le schede dei profili sono nascoste (codice mantenuto) e il gruppo del motore mostra i tempi tipici per motore.
  (2) La tessera "Modello" della Diagnostica mostra il modello realmente in uso (`🧩 Modello trascrizione`, emessa dalla pipeline, da Whisper dopo
  il caricamento e dal router). (3) Log a schermo: le righe per chunk (ripristino punteggiatura, chunk ritrascritti) e gli interni di caricamento
  vanno solo nel file di log, con un riepilogo a fine fase; le barre di avanzamento sono sempre l'ultima riga e si riscrivono per singola barra
  (una riga intercalata le faceva ripartire su una riga nuova); "Generazione rallentata" compare una volta per file e il totale è nella riga
  "Completato in". (4) Gli elementi della coda ancora in attesa si riordinano con il trascinamento, anche a elaborazione avviata. Layout e
  dimensioni delle colonne invariati.
- **v1.30.1 / v1.30.0** — Ritrascrizione per lingua forzata per Qwen3-ASR e Faster-Whisper (`core/qwen3_lang_retry.py`,
  `core/whisper_lang_retry.py`): entrambi gli engine forzavano la lingua dichiarata della traccia su ogni chunk, per
  cui contenuto in un'altra lingua (canzoni in inglese dentro film non inglesi, principalmente) tornava vuoto o
  storpiato. I chunk/segmenti sospetti — e, per Whisper, i *vuoti* che il suo stesso VAD lascia intorno al cantato —
  vengono ritrascritti con rilevamento automatico della lingua e tenuti solo se viene rilevato inglese (l'unica
  lingua validata contro i falsi positivi su rumore). Trovato e corretto su 9 esibizioni reali di X Factor; copre
  sia il percorso Whisper a file intero che quello a chunk.
- **v1.29.0** — Spagnolo instradato su Faster-Whisper invece di Qwen3-ASR dopo un banco a 5 motori (Qwen3, Whisper,
  NVIDIA Canary-1B-v2, Cohere Transcribe, HiTZ) su 4 film in lingua originale: nessun nuovo candidato ha battuto i
  due incumbent sulla regola pass/fail del banco, ma Whisper era alla pari di Qwen3 sul recall con meno
  allucinazioni e blocchi molto migliori una volta combinato con lo split per frasi (ora esteso anche allo spagnolo).
- **v1.28.0 / v1.27.0** — Split per frasi esteso a tedesco e francese, confermato su 8 film in lingua originale mai
  visti contro sottotitoli professionali (blocchi a metà frase dal 37-51% all'1-6%).
- **v1.26.0** — Francese e tedesco instradati su modelli Whisper fine-tuned (`whisper_model_by_language`) al posto
  di Qwen3, scelti dopo un banco a 5 motori su un riferimento denso di nomi propri.
- **v1.25.0** — Le sorgenti non inglesi non passano più da TranslateGemma (fine-tuned solo inglese→italiano, che
  allucinava o lasciava righe non tradotte sulle altre lingue sorgente) — instradate automaticamente su NLLB
  finetuned, sia nella coda principale che nell'OCR bitmap.
- **v1.24.0** — Coda sync multi-file sottotitoli + nuovo motore di allineamento solo-tempi (`core/timing_aligner.py`):
  100% delle righe entro 0,5 s su episodi reali, ~2 s per episodio invece di ~81 minuti; ha sostituito Qwen2.5-14B
  come percorso di default.

### v1.23.0
- **Split dei segmenti Whisper sui confini di frase, ora attivo per inglese e italiano.** faster-whisper tagliava i segmenti lunghi a 80 caratteri / 6 s senza guardare la punteggiatura: il 37-47% dei blocchi finiva a metà frase e la traduzione riceveva frammenti. Ora lo split preferisce i confini di frase (`core/whisper_sentence_split.py`, opzioni `whisper_split_sentence_aware` e `whisper_split_sentence_langs`, default `["en", "it"]`; le altre lingue mantengono lo split originale; `false` ripristina il comportamento precedente). I blocchi a metà frase scendono al 6-11%, le parole restano identiche e i blocchi non finiscono più su articoli, preposizioni o congiunzioni (24,9% -> 2,1% in italiano, verificato con un controllo indipendente spaCy). Ogni lingua è stata confermata su file interi nuovi con regole congelate prima dei dati (inglese: 8 file; italiano: 8 file nuovi, dopo un primo giro che ha fatto emergere un glitch dei timestamp di Whisper dentro le parole, ora gestito). Riserve: l'italiano è coperto soprattutto da film doppiati (3 file in italiano originale) e l'effetto sulla traduzione non è stato misurato. Prove, regole e verdetti in `whisper_split_eval/`.
- **Demucs a chunk oltre i 60 minuti** (prima 90): lo standard path teneva in RAM quattro sorgenti intere e poteva esaurire una macchina da 32 GB.
- Le versioni 1.17.0 - 1.22.0 sono documentate in [CHANGELOG.md](CHANGELOG.md).

### v1.16.0
- **Pipeline di trascrizione audio: 3 difetti reali diagnosticati e corretti su un film reale.** Punto di partenza un file prodotto realmente (Goodrich 2024, audio italiano trascritto direttamente): duplicati da chunk audio sovrapposti, testo attribuito al personaggio sbagliato, ~30% dei blocchi senza punteggiatura nelle scene di crosstalk/litigio.
  - **Bug del chunker** (`core/audio_processor.py`): l'estensione di un chunk troppo corto poteva sconfinare fisicamente nel successivo, facendo trascrivere la stessa battuta due volte con timestamp leggermente diversi. Corretto, più una rete di sicurezza finale che garantisce `chunk[i].end <= chunk[i+1].start` per costruzione. Verificato: 12 salti temporali all'indietro → 0 su rerun reale.
  - **Gate di confidenza sul trattino di dialogo** (`core/subtitle_formatter.py`, `core/diarizer.py`): il trattino "- " veniva assegnato solo su gap/lunghezza, senza verificare l'affidabilità dell'attribuzione — una scelta debole diventava un trattino permanente sulla riga sbagliata. Nuovo campo `speaker_confidence` per segmento, soglia minima prima di concedere il trattino.
  - **Durata chunk configurabile con cap per motore** (`ENGINE_CHUNK_CAP_S`): la durata non è più fissa a 20s ed è limitata per motore (Canary ≤35s, Qwen3 ≤150s, Whisper ≤30s), così non può mai superare ciò che ogni motore supporta davvero.
  - **Fix `qwen3_max_new_tokens`**: il tetto di generazione era fisso a 256, già al limite del troncamento su chunk densi da 25s. Ora 0 = calcolato automaticamente dalla durata massima configurata dei chunk.
  - **Riscrittura assegnazione word-level** (dietro `diarization_word_vote_enabled`, ancora `False` di default — non promossa): voto pesato sull'overlap invece della ricerca a punto medio, e una politica esplicita per le run corte (interiezioni come "Sì."/"No.") invece di fonderle sempre nella run precedente. Il percorso storico resta intatto e rimane quello attivo di default.
  - **Nuovo `core/punctuation_restorer.py`** — ripristina la punteggiatura sui chunk ASR che tornano completamente privi di essa (modello dedicato, `oliverguhr/fullstop-punctuation-multilang-large`, solo CPU, corrispondenza 1:1 parola↔timestamp garantita per costruzione). **Promosso a default** (`punctuation_restore_mode='missing'`) dopo validazione mirata su 22 frasi campione scritte a mano (l'invariante sul numero di parole ha tenuto in ogni caso; solo un caso ha alterato il senso della frase). Limite noto: il modello non può mai emettere "!" — un insieme fisso di etichette di addestramento, non un bug.
  - **Soglia di clustering pyannote promossa a default** (`diarization_clustering_threshold=0.85`, contro lo 0,7046 calibrato dal produttore del modello): riduce in modo misurabile il sovra-clustering (27→12 "parlanti" rilevati) in una campagna di taratura dedicata — nuovo banco riutilizzabile **`diar_eval/`** (`diar_bench.py` + `metrics.py`; sottocomandi prepare/run/gold-make/gold-score/sweep-c), valutato su 50 coppie audio etichettate a mano. **Riserva onesta**: un ricalcolo successivo ha mostrato che il segnale sulla metrica aggregata era statisticamente debole (non significativo, McNemar p=1,00, su un campione di quella dimensione) — resta una scelta deliberata, non un risultato decisivo, ed è la prima cosa da rivedere se compaiono sintomi di sovra-fusione su un altro genere di film.
  - Tre bug trovati in prima persona dall'utente mentre etichettava a mano il gold set (un margine di contesto che faceva sconfinare una seconda voce in un clip di turno adiacente, micro-turni pyannote da 17ms campionati per errore, e un parsing CSV che si rompeva sui file risalvati da Excel in locale italiano) — tutti corretti in `diar_eval/diar_bench.py`.

### v1.15.0
- **Correzione alla diagnosi della v1.14.0, e il fix vero — merito di un utente che l'ha messa in dubbio.** La nota PAL/NTSC qui sotto dice che la sincronizzazione "non rileva il drift progressivo". Quella formulazione era sbagliata, ed è stata smentita con lo stesso tipo di test empirico usato in precedenza per giustificarla: l'utente ha fatto notare che gli anchor sono timestamp reali per-riga, presi direttamente dalla traccia embedded *di questo stesso video* (o da una trascrizione Whisper del suo audio) — non un offset o un fattore di scala globale calcolato una volta e applicato a tutto. Se Qwen abbina una riga esterna all'anchor giusto, il timestamp che riceve è quel valore vero per quell'istante esatto, indipendentemente da quanto la posizione ORIGINALE del file esterno si fosse allontanata dalla realtà. Riprodotto con un matcher semanticamente perfetto (zero allucinazioni) su un file con drift PAL simulato: disattivando solo il controllo di offset del gate, **100% esatto, errore massimo 0,0s** — il matching per-riga non è mai stato il problema. La causa vera era il gate stesso (aggiunto nei due giri dietro la v1.14.0): confrontava ogni timestamp candidato con la posizione ORIGINALE della riga esterna (sempre più sbagliata, su un file con drift), quindi scartava come "implausibili" match corretti verso la fine del film, e la logica di cattura delle finestre non proponeva nemmeno il 65% delle righe di fine film alla finestra giusta — entrambe ancorate allo stesso riferimento difettoso.
  - **Fix**: il gate e la finestra di cattura ora confrontano con una posizione attesa *appresa*, non con quella originale grezza — un modello lineare (`shift(t) = a·t + b`, stimato con Theil-Sen, la mediana delle pendenze a coppie, robusto proprio al tipo di outlier rumorosi che un match sbagliato introdurrebbe) costruito sui match già accettati, raffinato finestra dopo finestra man mano che il film avanza. Un controllo di qualità obbligatorio (residui ≤2s, ≥60% di inlier) fa sì che un fit scadente — es. con un tasso di allucinazione alto — lasci il modello al suo default (a=0, b=0), che è identico byte per byte al comportamento precedente; verificato che questo non peggiora un file senza drift e con il 100% dei match allucinati. Sullo stesso file PAL simulato (0% allucinazioni, isolando il drift come unica variabile): 100% esatto, errore massimo 0,0s, e il modello ha correttamente recuperato una pendenza di 0,0427 — il vero rapporto PAL/film 25/23,976.
  - La lezione vale oltre questo singolo bug: una rete di sicurezza "rileva e scarta i valori implausibili" vale quanto il riferimento con cui confronta — confrontare con un riferimento vecchio o già sbagliato la fa scartare la risposta CORRETTA invece di quella sbagliata, e nessuna quantità di ri-test della sola logica di rifiuto lo avrebbe scoperto: solo mettere in dubbio con cosa stesse confrontando.

### v1.14.0
- **Sincronizzazione sottotitoli ("Anchor & Match"): da "mai validata" a una garanzia di correttezza verificata, in tre giri di revisione.** La feature — allinea un `.srt` italiano esterno fuori sincrono ai timestamp corretti presi dai sottotitoli embedded del video o da una trascrizione Whisper, abbinati semanticamente con un Qwen2.5-14B locale — non era mai stata esercitata end-to-end. Un primo bugcheck ha trovato 15 difetti, il peggiore dei quali (quattro bug che si sommavano) produceva in silenzio un **SRT di output sbagliato nel 50% delle righe** su una simulazione di film intero, senza alcun errore e con un messaggio "completato". Corretto e verificato (100% esatto sulla stessa simulazione) in un primo giro, ma un secondo giro di revisione ha trovato che il fix del bug peggiore era solo *parziale* — misurato al 22% di righe ancora sbagliate, perché il criterio di merge si basava sulla confidence auto-riportata dal modello, che l'inferenza reale ha mostrato essere quasi sempre ≈1.0 anche sui match sbagliati. Il fix vero è un **gate di offset globale**: nessuna riga può spostarsi oltre un `sync_max_offset_sec` configurabile dalla sua posizione originale, qualunque cosa dichiari il modello — il terzo giro di revisione ha trovato che questo gate aveva un bypass spalancato per il caso "una riga esterna divisa su due anchor" (fino a 176s di errore) e l'ha corretto, verificato su un episodio reale da 794 righe con zero cue invertite o sovrapposte ed ogni errore contenuto entro la tolleranza configurata.
  - Difetto radice: finestre di matching sovrapposte risolvevano ogni riga esterna indipendentemente e vinceva "la prima finestra arrivata" — una riga presa in prestito dalla finestra sbagliata (il suo vero anchor era in quella successiva) riceveva una stima posizionale ristretta agli anchor della finestra sbagliata, sbagliata di decine di secondi, in silenzio.
  - Il fallback posizionale stesso era un secondo bug: per la manciata di righe mai risolte dal modello, le distribuiva per rapporto d'indice su TUTTO il film invece di interpolare dai vicini risolti — con una sola riga non risolta, il rapporto (`0/max(0,1)=0`) la mandava sempre all'inizio del file.
  - Il percorso "dividi una riga in due" era codice morto: una scorciatoia che si fidava dei timestamp del modello (resi obbligatori dalla grammatica JSON) faceva sì che le due metà di uno split ricevessero sempre timestamp IDENTICI, che una fase di formattazione a valle fondeva poi in silenzio in un'unica riga, perdendo una battuta. Quella fase di formattazione (presa in prestito da un'altra feature, pensata per fondere/riformattare/ripulire l'output di un aligner) è stata rimossa del tutto da questo percorso: il contratto qui è "cambia solo i tempi", e stava anche eliminando gli a-capo dell'utente, i trattini di dialogo e i tag corsivo.
  - La correzione di genere sul file sincronizzato era un no-op che dichiarava successo: alla chiamata subprocess mancava `video_path`, l'unico campo di cui il correttore ha davvero bisogno per costruire una mappa dei parlanti dall'audio.
  - La lingua sorgente dell'anchor non veniva mai rilevata oltre un default fisso; la logica di confronto lingua aveva essa stessa falsi positivi/negativi (una traccia polacca poteva essere scambiata per portoghese). Correggere questo ha esposto — e richiesto di correggere — un secondo problema: alcuni tag lingua reali (`pob`, `pt-BR`, `en-US`) non sono riconosciuti affatto dal traduttore, quindi passarli così com'erano faceva fallire l'intera sincronizzazione invece di limitarsi a tradurre male; un passaggio di canonizzazione con ripiego chiude il problema.
  - Un errore di calcolo nella generazione delle finestre poteva lasciare le ultime 1-2 righe di un file (~11% dei file, per conteggio di anchor) mai proposte al modello.
  - Corretti anche due bug reali di interfaccia: il dialog di completamento poteva mostrare un percorso file inesistente (calcolato dal percorso video invece di quello reale di output, che segue la posizione dell'SRT esterno); chiudere il dialog con Esc bypassava del tutto la logica di annullamento, e — trovato nell'ultimo giro di revisione — il percorso del pulsante di chiusura ed Esc potevano entrambi far scattare la stessa attesa di spegnimento da 30 secondi, bloccando la finestra fino a un minuto.
  - Sincronizzazione, coda di trascrizione e strumento glossario ora si rifiutano di girare in contemporanea (tutti e tre caricano modelli grandi sulla stessa GPU).
  - **Limite noto, non ancora affrontato**: il drift progressivo lungo un file (il classico disallineamento PAL/NTSC 25↔23,976fps, dove il desync cresce di continuo invece di restare costante) non viene rilevato — misurato ~79% delle righe fuori tolleranza su un file così. Il gate rifiuta correttamente di indovinare oltre la tolleranza configurata invece di produrre un risultato sbagliato con sicurezza, e ora logga un avviso esplicito che nomina `sync_max_offset_sec` quando succede, ma è un limite di progettazione, non un fix rimasto indietro.
  - Anche noto e rimandato: l'intera pipeline carica ancora NLLB + Whisper + Qwen-14B dentro il processo GUI invece che in un subprocess isolato (la convenzione di questo progetto esiste proprio per questo), e l'annullamento non riesce a interrompere una singola chiamata al modello già in corso.

### v1.13.0
- **L'upload OpenSubtitles ora funziona davvero — verificato con 4 upload reali, la prima volta in assoluto per questo progetto.** La funzione esisteva dalla v3.8 e non era mai riuscita end-to-end nemmeno una volta: due giri completi di bugcheck più test dal vivo contro l'API reale hanno trovato e corretto una catena di difetti indipendenti:
  - **Causa radice del fallimento totale di ogni upload**: l'uploader XML-RPC comprimeva `subcontent` con **gzip**; il protocollo si aspetta **zlib**. Il server decomprimeva sempre a stringa vuota, producendo sia "SubHashes non corrispondono" sia "formato sottotitolo non valido" da un'unica causa, non due. `utils/opensubtitles_xmlrpc_uploader.py` ora usa `zlib.compress`.
  - **opensubtitles.org e opensubtitles.com sono account separati con credenziali proprie**, anche a parità di username — l'app aveva un solo slot di credenziali. Una diagnosi sbagliata ereditata dal codice storico attribuiva il `401 Unauthorized` di XML-RPC a uno User-Agent non registrato (un processo di registrazione manuale non più disponibile dal 2022) invece della vera causa: le credenziali `.com` usate contro il login `.org`. Nuove chiavi di config dedicate `opensubtitles_xmlrpc_username`/`_password` e relativi campi nelle Opzioni, separate da quelle `.com`/REST esistenti; `authenticate()` ora segnala il vero errore "credenziali sbagliate per questo account".
  - **L'endpoint `/upload` della REST API usato dal codice non esisteva** (404 — un percorso inventato, non un rifiuto di OpenSubtitles). Il percorso reale, `/api/v1/subtitles/upload`, risponde `403 uploads_not_enabled` per le API key normali — la funzione è opt-in e richiede che OpenSubtitles abiliti la chiave su richiesta. Costante dell'endpoint corretta per quando verrà concesso; REST non è più il percorso di upload predefinito (lo è XML-RPC, l'unico che oggi funziona davvero) e il fallback automatico su REST dopo un fallimento XML-RPC è stato rimosso (non avrebbe mai potuto aiutare: REST non può caricare per questa API key indipendentemente dall'esito di XML-RPC).
  - **IMDb ID sbagliato per gli episodi TV** — veniva risolto solo l'IMDb ID della *serie*; gli upload di singoli episodi hanno bisogno di quello specifico dell'episodio, quando disponibile. `utils/tmdb_client.py` ora lo cerca tramite gli `external_ids` per-episodio di TMDB e ricade sull'ID di serie quando non esiste una scheda per l'episodio.
  - **Lingua sbagliata caricata per 5 lingue** — una dict-comprehension di inversione ingenua sceglieva la forma ISO 639-2 sbagliata a seconda dell'ordine di dichiarazione; tedesco, olandese, ceco, rumeno e greco erano affetti, il caso peggiore era il rumeno (`rum`) troncato in silenzio a `ru` — **russo**. Sostituita con una tabella di mappatura esplicita e non ambigua; il traduttore di codici lingua REST ora ritorna `None` invece di indovinare su un codice non mappato, e il chiamante interrompe l'upload invece di inviare una lingua sbagliata.
  - **Bug che faceva crashare l'app**: "Test connessione" con credenziali incomplete sollevava un `AttributeError` non gestito fuori dal `try/except` del metodo, abbattendo l'intero processo.
  - Rimossi tre moduli morti/fuorvianti (`opensubtitles_client.py`, `opensubtitles_integration.py`, `opensubtitles_config.py`) — uno di questi restituiva silenziosamente "successo" da uno stub `# TODO: implementa questo` senza mai chiamare alcuna API, il tipo di file che trae attivamente in inganno chi lo legge dopo.
  - Altri diversi: un dialog impostazioni che cancellava credenziali appena digitate e non salvate cambiando metodo API; un tooltip non aggiornato in contraddizione col nuovo default; un controllo credenziali usato dal traduttore separato "OpenSubtitles AI" che era scivolato ad accettare credenziali valide solo per l'upload; un controllo duplicati che rifaceva un lavoro già svolto internamente dalla chiamata di upload XML-RPC stessa.
- **Nota di processo**: testare dal vivo un percorso di codice non ancora corretto contro l'API reale di OpenSubtitles ha prodotto un effetto collaterale non voluto — una chiamata diagnostica iniziale ha pubblicato un sottotitolo per un episodio in forma anonima, con il contenuto grezzo del file (BOM/CRLF, riga promozionale non ripulita), prima che la vera fase di pulizia della pipeline fosse coinvolta. Resta accanto all'upload corretto e correttamente attribuito per lo stesso episodio; non è correggibile dal nostro lato (nessun account è associato) e serve una segnalazione a OpenSubtitles per rimuoverlo. Un promemoria che la sperimentazione dal vivo contro un'API reale di terze parti — anche solo per "isolare una variabile" — può lasciare una traccia pubblica, non solo un risultato pass/fail.

### v1.12.2
- **Strumento glossario per-show: corretto tmdb_id sbagliato scritto in silenzio su librerie in stile Plex (`V:\Show\Season N\...`)** — quando la cartella scelta nel dialog "Glossario per show" era la sottocartella stagione invece della cartella show, il suo nome ("Season 2") degradava a "Season" nel parsing del nome file e trovava corrispondenza con un risultato TMDB estraneo — un `tmdb_id` sbagliato scritto nel glossario senza alcun avviso. Il dialog ora riconosce i nomi di cartelle stagione/speciali in diverse lingue, e costruisce una lista di titoli candidati reali (nome della cartella padre, poi il titolo dello show estratto dal primo file episodio trovato) prima di chiamare `search_tv()`.
- **Fix: subprocess GPU orfano lasciava ~9GB residenti in VRAM annullando lo strumento glossario** — il canale Qwen lancia la sua fase lato GPU come subprocess sul venv principale (collegato dal venv isolato `venv_glossary` dello strumento); l'annullamento terminava solo il figlio diretto, che su Windows non si propaga ai discendenti del subprocess. Ora traccia il PID del subprocess GPU e uccide l'intero albero di processi (`taskkill /T`) all'annullamento.
- **Strumento glossario e coda principale di trascrizione/traduzione ora mutuamente esclusivi** — entrambi possono usare la GPU; farne partire uno mentre l'altro è attivo genererebbe contesa sulla stessa VRAM. Ognuno ora rifiuta di partire mentre l'altro è attivo, con un messaggio chiaro invece di rallentamento silenzioso o un OOM.
- `qwen_n_gpu_layers` è ora un'impostazione per-show configurabile per il canale Qwen dello strumento glossario (prima cablata nel codice).

### v1.12.1
- **Batch manager adattivo: non ridurre il batch quando la pressione di memoria non è nostra** — misurato su un run reale (due traduzioni NLLB lanciate in parallelo): la memoria è salita dal 50% all'85% mentre il nostro batch restava fermo a 24, e il gestore lo riduceva comunque — ridurre un batch non libera memoria tenuta da un altro processo, e ha misurabilmente peggiorato il tempo per frase del 62% (0,271s → 0,438s). Nuovo `_external_pressure_gb()`: confronta `torch.cuda.memory_reserved()` (quanto allocato da questo processo) con la memoria totale usata; se il divario supera 1,5GB il gestore tiene la dimensione e logga un avviso invece di ridurre. **Un bug reale è stato trovato e corretto in questa stessa guardia durante la revisione**: campionava la pressione solo dentro il ramo `mem > high_threshold`, quindi su un file che parte pulito e incontra la contesa a metà, la PRIMA lettura cade già durante la contesa e diventa la linea di base — la pressione risulta zero e la guardia è inerte esattamente sul caso per cui esiste. Corretto campionando a ogni batch.
- **Guardia temporale (ms/token), la cosa più vicina a un segnale di OOM che Windows/WDDM ci dà davvero** — controllato tutto lo storico dei log: zero eventi OOM reali sono mai scattati in produzione, perché WDDM pagina silenziosamente lo sconfinamento di VRAM in RAM di sistema invece di sollevare un errore CUDA. L'unica firma reale è il tempo di generazione che risale. Aggiunta sia al ramo NLLB che al ramo LLM (con ms/carattere invece di ms/token per l'LLM, che restituisce testo non tensori): traccia il ritmo migliore osservato nel file e logga un avviso se un batch è ≥2× più lento — deliberatamente solo diagnostica, non una reazione automatica, perché ridurre il batch sotto contesa ESTERNA non aiuta (vedi sopra).
- **Risalita del batch moltiplicativa invece di +1** — misurati 9 batch sprecati per tornare da 16 a 24 un passo alla volta dopo la fine di una contesa, a throughput ridotto per tutto il tempo, su letture di memoria che avevano già confermato margine reale.
- **Dati alla base della causa**: un'analisi pubblicata come artifact su 875 batch reali di 23 run ha trovato che la soglia di riduzione esistente (85%) è già ben calibrata (un richiamo del 93% con una soglia più bassa veniva da un campione confuso — la maggior parte dei batch "degradati" in quel set erano run in contesa parallela, dove ridurre peggiorava le cose invece di migliorarle) — quindi la soglia stessa non è stata toccata; il fix vero era dare al gestore un modo di distinguere la contesa dal proprio uso legittimo di memoria.

### v1.12.0
- **Fix: righe di sottotitolo rimaste silenziosamente in inglese quando un placeholder di mascheramento del glossario non veniva riprodotto fedelmente** — l'avviso (`logger.warning`) del ramo LLM per questo caso non arrivava mai né al file di log né a schermo (una chiamata nuda a `logging.getLogger()`, la stessa classe di bug già corretta per il batch manager nella v1.11.0, qui rimasta invisibile perché nessuno aveva motivo di controllare finché episodi reali non hanno mostrato righe inglesi senza alcuna traccia di errore). Sostituito l'unico ripiego "l'unmask fallisce → resta l'inglese" con una catena di recupero a cinque livelli, condivisa da entrambi i rami NLLB e LLM: riparazione tollerante del placeholder (corregge un token storpiato dal modello — spazi in più, maiuscole sbagliate, una parentesi persa); un retry senza mascheramento sul motore primario ancora in VRAM (elimina la vera causa del fallimento — il token sintetico — invece di rimandare lo stesso input che ha già fallito); uno scambio una tantum verso un motore di ripiego ("serbatoio") per tutto ciò che sopravvive, deduplicato per testo sorgente così una riga ripetuta non viene ritradotta due volte; e, solo se tutto questo fallisce, l'inglese ma con un avviso rumoroso e visibile invece che silenzioso. Un audit indipendente chiude ogni file a prescindere dalla causa: un controllo di identità sorgente/output segnala qualunque cosa resti non tradotta, così un futuro modo di fallimento non previsto emerge comunque invece di sparire. Verificato su un episodio reale con glossario per-show attivo (tutte le 24 righe prima silenziosamente inglesi risolte o diventate fallimenti visibili) e su un batch di produzione da 21 file (20 episodi con glossario + 1 senza, come controllo di non-regressione).
- **Motore del serbatoio scelto da una misura, non da un'assunzione** — una valutazione testa a testa GEMBA-MQM (Qwen2.5-14B vs NLLB fine-tuned, 39 righe corte dense di glossario da 4 show) ha trovato NLLB-FT nettamente avanti (64% contro 26% di preferenza, MQM pesato 1,41 contro 4,31); Qwen produceva veri errori grammaticali e un'allucinazione vera e propria. Il serbatoio ora sceglie di default il motore diverso da quello già usato come primario (NLLB fine-tuned quando il primario è il ramo LLM, Qwen quando il primario è NLLB — mai un secondo tentativo con lo stesso modello che ha già fallito due volte), configurabile con la nuova chiave `reservoir_engine`.
- **Altri otto bug trovati e corretti durante la revisione dell'implementazione**, tra cui: una chiamata a un metodo (`_apply_fallback`) mai definito da nessuna parte nel progetto, che trasformava un singolo output LLM vuoto in un crash della traduzione dell'*intero* file; un output di retry LLM validato ma ancora inservibile che sovrascriveva silenziosamente il primo tentativo; la sostituzione a posteriori del glossario che si fermava dopo la prima occorrenza di un termine ripetuto nella stessa riga; un bug di batch duplicato nel percorso di retry-errore del ramo NLLB (preesistente, non legato a questo fix, trovato rivedendo lo stesso codice); e un timeout mancante sul processo del serbatoio.

### v1.11.0.4.9.26
- **Fix: leak RAM nella fase di allineamento del glossario per-show** — `glossary_align.unload()` liberava solo i riferimenti Python (`gc.collect` + `torch.cuda.empty_cache`), senza mai restituire il working set del processo `venv_glossary` all'OS: la RAM usata da LaBSE durante l'allineamento restava occupata per tutta la fase Qwen/GPU successiva. Corretto con lo stesso trim `EmptyWorkingSet` già usato in `utils/resource_monitor.py`, reimplementato inline perché `venv_glossary` non ha `psutil`.

### v1.11.0
- **Costruttore glossario per-show (semi-automatico)** — nuovo dialog `Strumenti → Glossario per show`: trova i termini candidati tradotti in modo incoerente tra gli episodi di uno show e propone una resa fissa, verificata incrociando due canali indipendenti (allineamento parola-parola SimAlign+LaBSE + estrazione locale con Qwen, validata meccanicamente anziché fidata come giudice) al posto di un'unica euristica verbatim/assente che sovrastimava i difetti reali. Gira isolato in un nuovo `venv_glossary/` (confligge con `transformers==4.57.6` del venv principale); il canale Qwen su GPU è delegato al venv principale via subprocess-ponte. UI di revisione con schede approva/rifiuta per termine e salvataggio a merge.
- **Fix risoluzione dell'interlocutore in 2ª persona** — `addressee_gender_for_range()` scartava la cue per QUALSIASI terzo parlante isolato ovunque nella finestra ±8s, anche se irrilevante alla conversazione (misurato su Knight's & Magic: 5/7 candidate P2 bloccate così contro 1/7 dal vero controllo strict prev/next). Nuovo `_resolve_addressee()` condiviso: l'ambiguità vera è la sovrapposizione temporale diretta con la cue, non la sola presenza di un terzo parlante altrove. Copertura P2 0/7 → 1/7 con `strict=True` (invariato in produzione).
- **Traduttore LLM di produzione: supporto adattatore LoRA + path modello custom** — `llm_subtitle_translator` può ora caricare un adattatore LoRA e un path modello locale (config + UI + `translator.py`); il log di coda registra ora quale motore di traduzione ha prodotto ciascun file.
- **Fix: il logger del batch manager adattivo scartava silenziosamente i log info** — una chiamata nuda a `logging.getLogger()` in `adaptive_batch_manager` li scartava prima che raggiungessero il file di log condiviso.

### v1.10.1.22.8.26
- **Fix: cache del modello LLM di produzione cancellata a ogni fine coda** — il modello LLM che occupa lo slot di produzione (oggi TranslateGemma-12B) veniva scaricato nella cache HuggingFace e poi ricancellato a fine coda: la lista di preservazione copriva solo i motori ASR (whisper/wav2vec), non il ramo di traduzione LLM. L'adattatore LoRA fine-tuned promosso in produzione non era coinvolto (vive su disco fuori dalla cache HF). Il cleaner ora risolve a runtime quale modello occupa lo slot (chiave config `llm_translator_model`) e lo preserva; i modelli usati solo per confronti sperimentali continuano a essere cancellati come prima.

### v1.10.1
- **Rimosso il percorso "adapt" del ramo LLM: disallineava battute e tempi** — il ramo LLM interrogava il modello in due modi: "mt" (una battuta per conversazione, output diretto) e "adapt" (blocchi in JSON con id, che il modello doveva restituire intatti). Sotto una certa taglia i modelli sbagliavano gli id, fondendo blocchi e scrivendo le traduzioni successive nel posto sbagliato, coi tempi ancora corretti — il file sembrava sano ma non lo era. Il percorso era ormai irraggiungibile dall'interfaccia dopo la rimozione di Aya (v1.10.0) e rischiava di essere ereditato per difetto da un futuro modello. Rimosso interamente; resta solo "mt", immune al problema per costruzione.

### v1.10.0
- **Motore di traduzione LLM riscritto, TranslateGemma-12B sostituisce Aya** — il ramo LLM è ora un package model-agnostic con un registro dei modelli, corretti quattro difetti storici (prompt senza chat template, padding che corrompeva i batch, seconda battuta dei dialoghi scartata, fallback in inglese). Valutato su banco sintetico e poi su film reali con sottotitoli professionali come riferimento (Deadpool 2, A Man Called Otto): il verdetto si ribalta rispetto al banco sintetico, **NLLB fine-tuned resta il motore di produzione** davanti a TranslateGemma-12B e Aya. Aya rimossa dal registro.
- **Bug critico trovato eseguendo per la prima volta il percorso reale della pipeline** — NLLB traduceva il contesto (la trama del film) al posto della battuta stessa, invisibile finché il contesto non ha iniziato a essere passato davvero.
- **Marcatori musicali in convenzione USA allucinati 48 volte su 48** — `**testo**` non era protetto come `♪testo♪`; ora qualunque blocco senza lettere passa intatto.
- **Post-processing tipografico condiviso** su tutti i motori: righe fuori norma dal 59,3% al 9,7%.
- `.gitignore`: chiusi quattro buchi da ~12 GB che il pattern `venv/` non copriva.

### v1.9.7
- **Fix fusione battute nei blocchi dialogo multi-parlante** — NLLB non garantisce la preservazione dell'a capo quando traduce un blocco di sottotitoli a due parlanti (testo con newline interno tra le due battute): a volte le fondeva in un'unica riga, a volte inseriva persino trattini propri spuri, producendo blocchi come "- Vorrei che tu fossi qui. Anch'io." invece di due righe separate correttamente attribuite. I blocchi dialogo (identificati dai marcatori "- " già tracciati) vengono ora tradotti riga per riga anziché come blocco unico, garantendo per costruzione che il conteggio righe post-traduzione resti sempre fedele all'originale.

### v1.9.6
- **Fix critico: lingua sorgente NLLB ignorata per qualunque lingua diversa dall'inglese** — il tokenizer NLLB richiede `tokenizer.src_lang` impostato ad ogni chiamata per taggare correttamente la lingua del testo in input. Questo valore non veniva mai impostato e restava bloccato sul default caricato al momento del `from_pretrained()` (`eng_Latn`) — qualunque traduzione con sorgente diversa dall'inglese (tedesco, francese, spagnolo, russo, ecc.) veniva quindi tokenizzata come se il testo fosse inglese, causando frasi lasciate non tradotte o allucinazioni del modello. Verificato empiricamente su un campione di frasi tedesche: 5/10 non tradotte senza il fix, 0/10 con il fix applicato. Il bug era presente fin dall'introduzione del modulo NLLB e ha interessato ogni traduzione con sorgente non inglese.
- **Fix minori (naming file e correzione genere su input .srt)** — quando l'input della pipeline era già un file `.srt` con codice lingua nel nome (es. `Movie.en.srt`), il nome del file finale non includeva più correttamente solo la lingua di destinazione (produceva `Movie.en.it.srt` invece di `Movie.it.srt`). La correzione di genere grammaticale (STEP 6.5) andava in errore quando l'input della pipeline era già un `.srt`: tentava di estrarre l'audio con ffmpeg direttamente dal file dei sottotitoli invece di risolvere il video reale corrispondente nella stessa cartella.

### v1.9.5
- **Fix batch adattivo di traduzione, seconda puntata** — il tetto statico per classe introdotto in v1.9.3 (NLLB `max_size=24`) riduceva ma non eliminava lo sconfinamento sostenuto in RAM condivisa in alcuni run reali, e non era legato alla lingua sorgente come ipotizzato inizialmente: erano due lacune nella logica reattiva del batch manager. (1) Durante il warm-up il manager poteva solo *aumentare* il batch — non controllava mai la pressione di memoria per ridurlo, quindi sui file corti (la maggior parte delle traduzioni gira in meno di 10 batch) l'intero file poteva concludersi con un batch sovradimensionato e la memoria GPU satura. (2) `torch.cuda.empty_cache()` girava solo ogni 10 batch, soglia che quegli stessi file corti non raggiungevano mai, quindi la cache dell'allocator di PyTorch non veniva mai restituita al driver. Entrambi i punti ora reagiscono alla lettura di memoria reale ad ogni batch, warm-up incluso. Verificato sullo stesso file che aveva causato la segnalazione originale: lo step di traduzione è passato da 800 s (13 m 13 s) con 2,44 GB di sconfinamento sostenuto in RAM condivisa a 196 s (3 m 16 s) con solo un picco transitorio di ~19 s.

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
- **Harness di valutazione** (`gender_eval/`, solo locale — non pubblicato in questo repository) — benchmark MT-GenEval, ground-truth automatico dai sottotitoli professionali dual-track (~700 punti di test, zero annotazione manuale), confronto motori, A/B su episodio.
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
- Formattatore sottotitoli con stile di dialogo professionale
- Upload OpenSubtitles REST API con rilevamento duplicati

### v1.0.0
- Release iniziale: Faster-Whisper, NLLB/Aya/Claude/OpenAI, Demucs, TMDB, OpenSubtitles

---
