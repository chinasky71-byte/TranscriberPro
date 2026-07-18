# Changelog

Tutte le modifiche rilevanti di Transcriber Pro. Versioni secondo
[SemVer](https://semver.org/lang/it/): `APP_VERSION` in `main.py` è l'unica fonte di verità.

## [1.9.2] — 2026-07

### Ancoraggio sottotitoli alle battute + fix batch adattivo
- La regola anti-frammento riunisce la coda corta solo se è un vero frammento
  della stessa frase (pausa ≤ 0,8 s e frase non conclusa) — niente più blocchi
  con due battute distanti nella stessa riga.
- Fix batch adattivo trascrizione: lettura memoria a livello device, cap batch
  16, tetto VRAM-aware anche in modalità classica (su Windows/WDDM lo
  sforamento VRAM non dà OOM ma spillover silenzioso in RAM condivisa).
- Barra di progresso non più interrotta dai log di aggiustamento batch.

## [1.9.1] — 2026-07

### Ottimizzazione picco memoria Demucs
- Tensori residenti su CPU: `apply_model` sposta sulla GPU solo il segmento in
  lavorazione → picco VRAM costante (~0,6 GB) indipendente dalla durata del
  file (prima: >21 GB GPU committed su un episodio da 83 min).
- Unload anticipato di Demucs e Whisper a fine STEP 3 quando l'engine
  pianificato è Qwen3 / Canary.

## [1.9.0] — 2026-07

### Stile dialoghi professionale (Netflix)
- Trattini "- " solo quando due parlanti condividono lo stesso blocco SRT
  (una battuta per riga); speaker diarization estesa a tutti gli engine
  (opzione `dialogue_style_enabled`, default ON, richiede token HuggingFace).
- Trattini preservati anche negli SRT tradotti (tutti e 4 i backend).
- Nuovo `core/subtitle_formatter.py`: CPL 42, anti-flash, merge frammenti,
  raggruppamento dialoghi.

## [1.8.1] — 2026-07

- Fix: il gender corrector non gira più sulle trascrizioni in italiano nativo
  (senza traduzione).

## [1.8.0] — 2026-07

### Trascrizione multi-engine con routing automatico per lingua
- **NVIDIA Canary-Qwen-2.5B** (solo inglese, WER migliore; opzionale, richiede
  `venv_canary` dedicato con NeMo 2.7.3).
- **Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B** (pacchetto pip `qwen-asr`):
  11 lingue con timestamp word-level (zh, en, yue, fr, de, it, ja, ko, pt, ru,
  es), auto-detect lingua nativo.
- **Faster-Whisper large-v3** come fallback universale garantito: la pipeline
  non fallisce mai per colpa di un engine nuovo.
- Un solo engine ASR in VRAM per volta.
- Nuove chiavi config: `transcription_engine_mode` (auto / canary / qwen3 /
  faster-whisper), `canary_enabled`, `qwen3_enabled`; combo di selezione
  engine nelle impostazioni profilo.

## [1.7.0] — 2026-07-16

### Avvio senza freeze UI
- Tab Traduzione da 3719 ms a 15 ms; I/O asincrono; torch mai importato nel
  processo GUI (check ambiente via CLI esterna); splash in ~2 s.

## [1.6.1] — 2026-07-15

- Fix (GUI): rimosso "(LLM)" dall'etichetta della checkbox correzione genere.

## [1.6.0] — 2026-07-15

### Gender Corrector v2 — redesign completo (audio-driven, deterministico)

Il correttore di genere LLM (Qwen2.5-14B GGUF) è stato sostituito integralmente:
misurato sul benchmark, correggeva 2 errori su ~90 (+0,66 punti — di fatto inerte).

**Nuovo approccio**: il genere di chi parla non è deducibile dal testo
("I'm tired" non dice se parla un uomo o una donna) — ma è nella **voce**.

- **Speaker Gender Map** (`core/speaker_gender.py`): diarization pyannote +
  classificatore ECAPA (VoxCeleb2) → genere di ogni parlante con confidenza.
  Accuratezza 95,0% (validata su 22 episodi contro sottotitoli professionali).
- **Selettore morfosintattico** (`core/gender_line_selector.py`, spaCy in venv
  separato): individua le sole forme di 1ª/2ª persona che concordano col
  parlante/interlocutore; esclusioni blindate (participi con *avere*,
  modificatori nominali, dialoghi doppi, impersonali...).
- **Riscrittura deterministica + validatore** (`core/gender_rewriter.py`):
  flip morfologico (-o↔-a + tabella articoli/pronomi) accettato solo se ogni
  parola cambiata è una coppia di flessione plausibile → allucinazioni
  impossibili per costruzione. Il motore deterministico ha battuto Qwen2.5-14B
  nel confronto diretto (86,8% vs 83,1%).
- **2ª persona** ("sei stanca?"): genere dell'interlocutore dai turni di
  dialogo (91,4%, modalità strict) e dai vocativi col cast TMDB
  ("Sei cresciuta, Veronica").
- **Riuso diarization**: i turni calcolati in trascrizione vengono riusati
  dallo STEP 6.5 (~1-2 minuti risparmiati a film).

**Risultati** (ground-truth auto-estratto da sottotitoli professionali dual-track):
| Metrica | Prima (NLLB) | Dopo |
|---|---|---|
| 1ª persona femminile (corpus) | 19,3% | **86,8%** |
| 1ª persona maschile (corpus) | 89,3% | **93,3%** |
| A/B episodio reale, femminili | 0% | **60%** |
| A/B episodio reale, maschili | 100% | **100%** (mai degradato) |

**Migrazione**: il modello GGUF non serve più. Per la correzione genere ora
servono: venv NLP separato con spaCy (`venv_nlp/`, vedi README → Installation)
e un token HuggingFace (pyannote). Nuove chiavi config:
`gender_correction_second_person` (default on), `gender_selector_python`
(auto-discovery se vuota). UI impostazioni aggiornata.

Include inoltre: harness di valutazione completo in `gender_eval/`
(benchmark MT-GenEval, ground-truth builder dai film dual-track, A/B runner).

## [1.5.x] — 2026-06/07

Versioni precedenti al changelog: modulo OCR bitmap PGS/VOBSUB → SRT
(Tesseract parallelo, review UI, writeback mux/sidecar), integrazione Library
Scanner (badge bitmap, batch OCR, Superpower), routing OCR nella coda
principale, GUI revamp (icone SVG, settings unificati, i18n IT/EN),
ottimizzazione avvio (~2s), fix import bitmap in coda. Vedi la cronologia git.
