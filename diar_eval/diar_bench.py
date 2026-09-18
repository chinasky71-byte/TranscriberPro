"""
diar_eval - banco di taratura per diarization (punti A e C)
File: diar_eval/diar_bench.py

Uso: SEMPRE con l'interprete del venv principale (qwen-asr, demucs,
pyannote, ctranslate2 vivono lì):

    venv\\Scripts\\python.exe diar_eval\\diar_bench.py <sottocomando> ...

Sottocomandi:
    prepare      Demucs + trascrizione UNA VOLTA (~19 min), salva artefatti
    run          Un giro di diarization+formattazione con parametri dati (~3 min)
    gold-make    Estrae le clip audio per l'insieme oro (richiede etichettatura umana)
    gold-score   Valuta un run (o tutti) contro l'insieme oro etichettato
    sweep-c      Confronto v1/v2 sulla soglia del trattino (secondi, no GPU)
    report       Stampa runs.csv in forma leggibile

REGOLA FERREA (v. piano_fix_pipeline_trascrizione): questo script non
chiama MAI Config.set(). Ogni parametro passa come argomento esplicito a
Diarizer/SubtitleFormatter — la config globale viene solo letta e
fotografata nel manifest, mai scritta.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import metrics as m  # noqa: E402  (diar_eval/metrics.py, stesso folder)

SCHEMA_MANIFEST = "diar-bench/manifest/1"
SCHEMA_SEGMENTS = "diar-bench/segments/1"
SCHEMA_GOLD = "diar-bench/gold/1"

CSV_COLUMNS = [
    'run_id', 'model', 'source', 'thr', 'mcs', 'min_spk', 'max_spk', 'params_diverged',
    'word_vote', 'v2_params', 'dash_thr',
    'speakers', 'turns', 'speech_s', 'turn_med_s', 'top1_pct', 'top5_pct', 'n_spk_ge2pct', 'tail_lt2pct',
    'n_subsegments', 'n_blocks', 'n_dialogue_blocks', 'n_dash_rejected',
    'n_blocks_cleaned', 'n_dialogue_blocks_cleaned', 'n_lines_over_42cpl',
    'gold_recall_same', 'gold_spec_diff', 'gold_balanced_acc',
    'elapsed_s', 'srt_sha256',
]


def _emit(msg: str) -> None:
    print(msg, flush=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _read_manifest(work: Path) -> Dict:
    return json.loads((work / 'manifest.json').read_text(encoding='utf-8'))


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, allow_nan=False, indent=2)


_CONFIG_SNAPSHOT_KEYS = [
    'diarization_model',
    'diarization_audio_source', 'diarization_clustering_threshold',
    'diarization_min_cluster_size', 'diarization_max_speakers',
    'diarization_min_speakers', 'diarization_word_vote_enabled',
    'diarization_word_tolerance_ms', 'enable_forced_alignment',
    'transcription_engine_mode', 'asr_chunk_target_duration',
    'asr_chunk_min_duration', 'asr_chunk_max_duration',
]


def _warn_non_default_config(config_snapshot: Dict) -> None:
    """Avvisa se una chiave diarization_* è diversa dal SUO default reale
    (bug-check Opus, G5): confrontare con una lista fissa di valori "falsy"
    era sbagliato — 'diarization_word_tolerance_ms' ha default 100, non 0,
    quindi scattava SEMPRE e l'avviso veniva ignorato per abitudine.
    Ripetuto a ogni run_combo, non solo in prepare (bug-check Opus, B3): la
    config può cambiare fra un run e il successivo della stessa campagna."""
    from utils.config import Config
    non_default = {
        k: v for k, v in config_snapshot.items()
        if k.startswith('diarization_') and v != Config.DEFAULTS.get(k)
    }
    if non_default:
        _emit(f"  ⚠️ ATTENZIONE: config globale ha chiavi diarization_* diverse dal default: "
              f"{non_default} — un run 'senza tetto/soglia' (0) ricade su questi valori, "
              f"non sul comportamento vergine di pyannote.")


# ── segments.json: normalizzazione e I/O ──────────────────────────────────

_ALLOWED_SEG_KEYS = {'start', 'end', 'text', 'words'}
_ALLOWED_WORD_KEYS = {'start', 'end', 'word'}


def normalize_segment(seg: Dict, idx: int) -> Dict:
    extra = set(seg.keys()) - _ALLOWED_SEG_KEYS
    if extra:
        _emit(f"  ⚠️ segments[{idx}]: chiavi inattese scartate: {sorted(extra)}")
    words = []
    for wi, w in enumerate(seg.get('words') or []):
        w_extra = set(w.keys()) - _ALLOWED_WORD_KEYS
        if w_extra:
            _emit(f"  ⚠️ segments[{idx}].words[{wi}]: chiavi inattese scartate: {sorted(w_extra)}")
        words.append({'start': float(w['start']), 'end': float(w['end']), 'word': str(w['word'])})
    return {
        'start': float(seg['start']),
        'end': float(seg['end']),
        'text': str(seg.get('text', '')),
        'words': words,
    }


def dump_segments(path: Path, segments: List[Dict], engine: str, language: str) -> Dict:
    normalized = [normalize_segment(s, i) for i, s in enumerate(segments)]
    n_without_words = sum(1 for s in normalized if not s['words'])
    for s in normalized:
        assert 'speaker' not in s and 'speaker_confidence' not in s, (
            "segmento già annotato da diarization — dump_segments va chiamato PRIMA di assign_speakers")
    _write_json(path, {
        'schema': SCHEMA_SEGMENTS, 'engine': engine, 'language': language,
        'n': len(normalized), 'segments': normalized,
    })
    return {'n_segments': len(normalized), 'n_segments_without_words': n_without_words}


def load_segments(path: Path) -> List[Dict]:
    """Ricarica SEMPRE da disco: assign_speakers muta in-place i segmenti
    senza 'words' (v. Diarizer._assign_segment_speaker) — riusare la stessa
    lista Python fra due run contaminerebbe il run successivo in silenzio."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema') != SCHEMA_SEGMENTS:
        raise ValueError(f"schema segments.json inatteso: {data.get('schema')}")
    # deepcopy implicito: ogni chiamata rilegge e ri-costruisce i dict da JSON.
    return [dict(s, words=[dict(w) for w in s.get('words', [])]) for s in data['segments']]


# ── prepare: stage 1 ───────────────────────────────────────────────────────

def prepare(video: Path, work: Path, *, force: bool = False, keep_chunks: bool = False) -> Path:
    from utils.config import get_config
    from core.audio_track_selector import AudioTrackSelector
    from core.pipeline import ProcessingPipeline
    from core.transcriber import Transcriber
    from core.engine_router import EngineRouter
    from core.audio_processor import AudioProcessor
    from utils.resource_monitor import release_ram_to_os

    work = Path(work)
    manifest_path = work / 'manifest.json'
    if manifest_path.exists() and not force:
        _emit(f"  ℹ️ manifest già presente in {work} — uso --force per rifare stage 1")
        return manifest_path

    work.mkdir(parents=True, exist_ok=True)
    chunks_dir = work / 'chunks'
    chunks_dir.mkdir(parents=True, exist_ok=True)  # FFmpeg non crea directory (bug-check Opus, B1)
    t0 = time.time()

    config = get_config()
    config_snapshot = {k: config.get(k) for k in _CONFIG_SNAPSHOT_KEYS}
    _warn_non_default_config(config_snapshot)

    # STEP 2 (pipeline.py:452-467)
    _emit("1. Selezione ed estrazione traccia audio...")
    selector = AudioTrackSelector(str(video))
    track = selector.select_best_track()
    if not track:
        raise RuntimeError("Nessuna traccia audio trovata nel video")
    audio_path = work / 'extracted_audio.wav'
    if not selector.extract_audio_track(audio_path, track['index']):
        raise RuntimeError("Estrazione audio fallita")
    source_language_639_2 = selector.get_selected_language()
    lang_639_1 = ProcessingPipeline.LANG_MAP_639_2_TO_639_1.get(source_language_639_2)
    if lang_639_1 == 'und':
        lang_639_1 = None
    _emit(f"  ✅ Traccia {track['index']} ({source_language_639_2} → {lang_639_1})")

    # STEP 2.5 (pipeline.py:492-513): Transcriber PRIMA di Demucs — vincolo
    # ctranslate2/CUDA, non è un dettaglio stilistico.
    _emit("2. Pre-caricamento Transcriber (prima di Demucs)...")
    transcriber = Transcriber(log_callback=_emit)
    planned_engine, plan_reason = EngineRouter.plan(lang_639_1, config)
    _emit(f"  🧭 Engine pianificato: {planned_engine} ({plan_reason})")

    try:
        from faster_whisper import BatchedInferencePipeline  # noqa: F401
        use_batched = (planned_engine == 'faster-whisper')
    except ImportError:
        use_batched = False

    # STEP 3 (pipeline.py:524-533)
    _emit("3. Processing audio (Demucs + chunking)...")
    ap = AudioProcessor()
    ap.set_log_callback(_emit)
    chunk_list = ap.process_for_transcription(
        audio_path=audio_path, output_dir=chunks_dir,
        use_batched_pipeline=use_batched, engine=planned_engine)
    if not chunk_list:
        raise RuntimeError("Chunking/Demucs falliti")
    _emit(f"  ✅ {len(chunk_list)} chunk pronti")

    # Unload anticipato (pipeline.py:555-562)
    if planned_engine != 'faster-whisper' and len(chunk_list) > 1:
        _emit("  🧹 Unload anticipato Demucs + Whisper...")
        ap.cleanup_model()
        transcriber.unload_engines()
        release_ram_to_os()

    # STEP 4 (pipeline.py:567-593)
    _emit(f"4. Trascrizione ({planned_engine})...")
    transcribed_srt = work / 'transcribed.srt'
    success, detected_lang = transcriber.transcribe_chunks(
        audio_chunks=chunk_list, output_path=str(transcribed_srt),
        whisper_language=lang_639_1)
    if not success:
        raise RuntimeError("Trascrizione fallita")
    segments = list(transcriber._last_segments)
    _emit(f"  ✅ {len(segments)} segmenti, lingua rilevata {detected_lang}")

    # STEP 4.2 (pipeline.py:614-634): replica la CONDIZIONE, non il valore
    # di config — su un file diverso da Goodrich potrebbe entrare.
    enable_forced_alignment = bool(config.get('enable_forced_alignment', False))
    if enable_forced_alignment and len(chunk_list) == 1:
        _emit("  🔠 Forced alignment (batched, 1 chunk)...")
        from core.aligner import ForcedAligner
        import torch
        aligner = ForcedAligner(_emit)
        try:
            device_align = "cuda" if torch.cuda.is_available() else "cpu"
            if aligner.load(detected_lang, device_align):
                segments = aligner.align(segments, str(chunk_list[0][0]))
        except Exception as e:
            # Come pipeline.py:631-632: un fallimento qui non deve buttare
            # via ~19 minuti di Demucs+ASR già fatti (bug-check Opus, G4).
            _emit(f"  ⚠️ Forced alignment fallito: {e} — timestamp Whisper mantenuti")
        finally:
            aligner.unload()

    transcriber.cleanup()
    ap.cleanup_model()
    release_ram_to_os()

    seg_stats = dump_segments(work / 'segments.json', segments, planned_engine, detected_lang or lang_639_1 or 'it')

    # Candidato vocals per la sorgente 'vocals' in run_combo (pipeline.py:660-670)
    if len(chunk_list) == 1:
        audio_vocals = str(chunk_list[0][0])
    else:
        _candidate = audio_path.parent / f"{audio_path.stem}_vocals.wav"
        audio_vocals = str(_candidate if _candidate.exists() else audio_path)

    production_srt = video.with_name(f"{video.stem}.it.srt")

    manifest = {
        'schema': SCHEMA_MANIFEST,
        'video': str(video), 'work': str(work),
        'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'audio_track_index': track['index'],
        'source_language_639_2': source_language_639_2,
        'detected_language_639_1': detected_lang,
        'planned_engine': planned_engine, 'plan_reason': plan_reason,
        'use_batched': use_batched, 'n_chunks': len(chunk_list),
        'audio_original': str(audio_path), 'audio_vocals': audio_vocals,
        'sha256': {'audio_original': _sha256(audio_path),
                   'segments': _sha256(work / 'segments.json')},
        **seg_stats,
        'config_snapshot': config_snapshot,
        'production_srt': str(production_srt) if production_srt.exists() else None,
        'elapsed_s': round(time.time() - t0, 1),
    }
    _write_json(manifest_path, manifest)

    if not keep_chunks and chunks_dir.exists():
        shutil.rmtree(chunks_dir, ignore_errors=True)

    _emit(f"✅ prepare completato in {manifest['elapsed_s']:.0f}s → {manifest_path}")
    return manifest_path


# ── run: stage 2 ────────────────────────────────────────────────────────────

def run_combo(
    work: Path, run_id: str, *,
    source: str = 'vocals', threshold: float = -1.0, min_cluster_size: int = -1,
    min_speakers: int = 0, max_speakers: int = 0,
    dash_confidence_min: float = 0.55,
    word_vote: bool = False, v2_params: Optional[Dict] = None,
    model: Optional[str] = None,
) -> Dict:
    """threshold/min_cluster_size (bug-check Opus #1 — insidia REALE, ha già
    prodotto un arm sbagliato):

        < 0  (default)  = nessun override esplicito -> Diarizer legge la
                          CONFIG GLOBALE ('diarization_clustering_threshold',
                          in produzione 0.85)
        = 0             = DEFAULT DI FABBRICA del modello caricato (0.7046/12
                          su 3.1, 0.6 su community-1): override esplicito a
                          "nessun override", la config globale NON viene letta
        > 0             = quel valore

    Prima di questa distinzione `threshold or None` mandava 0 e "non
    specificato" sullo stesso ramo: l'unico modo di ottenere il default di
    fabbrica di un modello diverso era scrivere nella config globale —
    esattamente ciò che la REGOLA FERREA di questo script vieta.

    min_speakers/max_speakers restano su 0 di proposito: lì 0 significa
    "nessun tetto/pavimento" e non esiste un "default di fabbrica" distinto.
    """
    from utils.config import get_config
    from core.diarizer import Diarizer
    from core.subtitle_formatter import SubtitleFormatter
    from core.subtitle_cleaner import SubtitleCleaner

    work = Path(work)
    manifest = _read_manifest(work)
    run_dir = work / 'runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_lines: List[str] = []

    def log(msg: str) -> None:
        log_lines.append(msg)
        _emit(f"  [{run_id}] {msg}")

    t0 = time.time()
    config = get_config()
    _warn_non_default_config({k: config.get(k) for k in _CONFIG_SNAPSHOT_KEYS})  # bug-check Opus, B3

    audio = manifest['audio_vocals'] if source == 'vocals' else manifest['audio_original']
    segments = load_segments(work / 'segments.json')  # copia fresca, v. load_segments

    tolerance_ms = 100  # esplicito, mai None: v. bug-check Opus B3 (osservabilità)
    # None = "non specificato" (Diarizer legge la config), 0.0/0 = "default di
    # fabbrica del modello". v. docstring: NON usare `threshold or None`.
    req_threshold = None if threshold < 0 else float(threshold)
    req_mcs = None if min_cluster_size < 0 else int(min_cluster_size)
    diar = Diarizer(config.get_huggingface_token(), log,
                     clustering_threshold=req_threshold,
                     min_cluster_size=req_mcs,
                     model_id=model or None)
    diar.load()
    turns = diar.diarize(audio, num_speakers=0,
                          min_speakers=min_speakers, max_speakers=max_speakers,
                          audio_source_label=source)
    _write_json(run_dir / 'turns.json', turns)

    # Valori EFFETTIVAMENTE usati da pyannote (bug-check Opus, B3): se la
    # config globale ha 'diarization_max_speakers' non a 0, un run
    # "--max-speakers 0" qui risulterebbe comunque limitato — l'avviso
    # sopra lo segnala, questi campi lo rendono visibile riga per riga.
    eff_threshold = diar._effective_threshold
    eff_mcs = diar._effective_min_cluster_size
    eff_min_spk = diar._effective_min_speakers
    eff_max_spk = diar._effective_max_speakers
    eff_model = diar._effective_model
    # Solo i parametri RICHIESTI ESPLICITAMENTE possono "divergere": se la
    # richiesta era "da config" (req_* None), ricevere il valore di config non
    # è una divergenza — la contaminazione è già coperta da
    # _warn_non_default_config e dalle colonne thr/mcs/model, che registrano
    # sempre l'effettivo. bool(): senza, `model=None` faceva valere None
    # all'intera espressione e la colonna params_diverged finiva vuota nel CSV.
    params_diverged = bool(
        (req_threshold is not None and eff_threshold != req_threshold)
        or (req_mcs is not None and eff_mcs != req_mcs)
        or eff_min_spk != min_speakers or eff_max_spk != max_speakers
        or (model and eff_model != model))
    if params_diverged:
        log(f"⚠️ parametri effettivi diversi da quelli richiesti: "
            f"model={eff_model} thr={eff_threshold} mcs={eff_mcs} min_spk={eff_min_spk} max_spk={eff_max_spk} "
            f"(richiesti: model={model or '(da config)'} "
            f"thr={req_threshold if req_threshold is not None else '(da config)'} "
            f"mcs={req_mcs if req_mcs is not None else '(da config)'} "
            f"min_spk={min_speakers} max_spk={max_speakers})")

    if v2_params and not word_vote:
        log("⚠️ v2_params passati ma word_vote=False — ignorati, questo NON è un run C.2")

    annotated = diar.assign_speakers(segments, turns, word_vote=word_vote,
                                      tolerance_ms=tolerance_ms, v2_params=v2_params)
    diar.unload()

    formatted_srt = run_dir / 'formatted.srt'
    formatter = SubtitleFormatter(dash_confidence_min=dash_confidence_min, log_callback=log)
    if not formatter.save(annotated, formatted_srt):
        raise RuntimeError(f"{run_id}: SubtitleFormatter.save() fallito, v. {run_dir/'log.txt'}")
    blocks_raw = m.parse_srt(formatted_srt)

    cleaned_srt = run_dir / 'cleaned.srt'
    SubtitleCleaner.clean_file(formatted_srt, cleaned_srt)  # STEP 5, obbligatorio (v. spec §Q3)
    blocks_clean = m.parse_srt(cleaned_srt)

    n_dash_rejected = formatter._dash_rejected_low_confidence  # letto DOPO save(): v. bug-check Opus §4
    tm = m.turn_metrics(turns)

    row = {
        'run_id': run_id, 'model': eff_model, 'source': source, 'thr': eff_threshold, 'mcs': eff_mcs,
        'min_spk': eff_min_spk, 'max_spk': eff_max_spk, 'params_diverged': params_diverged,
        'word_vote': word_vote, 'v2_params': json.dumps(v2_params) if v2_params else '',
        'dash_thr': dash_confidence_min,
        **tm,
        'n_subsegments': len(annotated),
        'n_blocks': len(blocks_raw), 'n_dialogue_blocks': m.count_dialogue_blocks(blocks_raw),
        'n_dash_rejected': n_dash_rejected,
        'n_blocks_cleaned': len(blocks_clean),
        'n_dialogue_blocks_cleaned': m.count_dialogue_blocks(blocks_clean),
        'n_lines_over_42cpl': m.count_cpl_violations(blocks_clean),
        'gold_recall_same': None, 'gold_spec_diff': None, 'gold_balanced_acc': None,
        'elapsed_s': round(time.time() - t0, 1),
        'srt_sha256': _sha256(cleaned_srt),
    }
    _write_json(run_dir / 'metrics.json', row)
    (run_dir / 'log.txt').write_text('\n'.join(log_lines), encoding='utf-8')
    _append_csv(work / 'runs.csv', row)
    _emit(f"✅ {run_id} completato in {row['elapsed_s']:.0f}s — "
          f"speakers={tm['speakers']} tail_lt2pct={tm['tail_lt2pct']} "
          f"blocchi_dialogo={row['n_dialogue_blocks_cleaned']}")
    return row


def _append_csv(path: Path, row: Dict) -> None:
    """Se CSV_COLUMNS è cambiato da quando il file esiste (schema evoluto a
    metà campagna), il vecchio file viene spostato da parte invece di
    scrivere righe disallineate sotto un header vecchio in silenzio
    (bug-check Opus, M1b)."""
    if path.exists():
        with open(path, encoding='utf-8') as f:
            existing_header = next(csv.reader(f), [])
        if existing_header and existing_header != CSV_COLUMNS:
            backup = path.with_suffix(path.suffix + '.schema_old')
            _emit(f"  ⚠️ Schema di {path.name} cambiato — vecchio file spostato in {backup.name}")
            path.replace(backup)

    is_new = not path.exists()
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction='ignore')
        if is_new:
            w.writeheader()
        w.writerow(row)


def _rewrite_csv_from_metrics(work: Path) -> None:
    """Ricostruisce runs.csv da tutti i runs/*/metrics.json (bug-check Opus,
    B2): gold_score aggiorna solo metrics.json per singolo run, e senza
    questa funzione le colonne gold_* in runs.csv restano vuote per sempre."""
    work = Path(work)
    runs_dir = work / 'runs'
    if not runs_dir.exists():
        return
    rows = []
    for run_dir in sorted(runs_dir.iterdir()):
        metrics_path = run_dir / 'metrics.json'
        if metrics_path.exists():
            rows.append(json.loads(metrics_path.read_text(encoding='utf-8')))
    if not rows:
        return
    csv_path = work / 'runs.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow(row)


# ── gold-make / gold-score ───────────────────────────────────────────────

_FFMPEG_NO_WINDOW = {'creationflags': 0x08000000}  # CREATE_NO_WINDOW, coerente col resto del progetto


def _clip_ok(t_start: float, t_end: float, src: str, out_path: Path,
             margin_before: float, margin_after: float) -> bool:
    """-ss/-t invece di -ss/-to (bug-check Opus, M4: -to in input è stato
    ambiguo storicamente fra versioni FFmpeg, -t è una durata, mai
    ambigua). Verifica l'esito: file creato e non vuoto, altrimenti False
    invece di lasciare un WAV mancante scoperto solo all'ascolto.

    Margini ASIMMETRICI (trovato dall'utente in etichettatura, non dal
    bugcheck): un margine fisso simmetrico sconfina nel turno vicino
    quando due turni sono adiacenti o quasi (gap≈0, il caso più comune
    proprio per le coppie 'local_dash' che contano di più) — v.
    _safe_margins, che li clamma alla metà del gap reale."""
    import subprocess
    duration = (t_end + margin_after) - max(0, t_start - margin_before)
    subprocess.run([
        'ffmpeg', '-y', '-ss', str(max(0, t_start - margin_before)), '-t', str(duration),
        '-i', src, '-ac', '1', '-ar', '16000', str(out_path),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, **_FFMPEG_NO_WINDOW)
    return out_path.exists() and out_path.stat().st_size > 0


MIN_CONTEXT_MARGIN = 0.08  # garantito anche a gap=0: compromesso deliberato, v. sotto


def _safe_margins(turns_sorted: list, idx: int, margin_s: float) -> Tuple[float, float]:
    """Margine (prima, dopo) per il turno turns_sorted[idx], clampato a
    metà del gap col turno precedente/successivo — non a cavallo del
    confine tale da far dominare l'altra voce, ma con un pavimento di
    MIN_CONTEXT_MARGIN anche a gap=0.

    Zero margine assoluto (versione precedente) risolveva il crosstalk ma
    rendeva le clip di turni brevi (0,2-0,4s, il caso 'local_dash' più
    interessante) troppo corte per un giudizio umano affidabile — trovato
    dall'utente in etichettatura. ~80ms di sbordo è un compromesso comune
    nel taglio di clip audio (coarticolazione, jitter dei confini
    dell'aligner) e non basta a rendere udibile una seconda voce per più
    di una frazione di secondo."""
    n = len(turns_sorted)
    this_start, this_end, _ = turns_sorted[idx]

    if idx == 0:
        margin_before = margin_s
    else:
        gap_before = this_start - turns_sorted[idx - 1][1]
        margin_before = margin_s if gap_before >= 2 * margin_s else max(MIN_CONTEXT_MARGIN, gap_before / 2)

    if idx == n - 1:
        margin_after = margin_s
    else:
        gap_after = turns_sorted[idx + 1][0] - this_end
        margin_after = margin_s if gap_after >= 2 * margin_s else max(MIN_CONTEXT_MARGIN, gap_after / 2)

    return margin_before, margin_after


def gold_make(work: Path, *, from_run: str = 'R0', n_local: int = 30, n_longrange: int = 20,
              margin_s: float = 0.3, max_attempts: int = 200_000) -> Path:
    """Costruisce le coppie oro dal run indicato: n_local coppie di segmenti
    adiacenti (per quota su dash/stesso-speaker/lontane) e n_longrange
    coppie fra turni distanti privilegiando la coda <2% (v. spec §3.6 —
    queste ultime misurano il sovra-clustering vero).

    Campionamento a lunga distanza per RIFIUTO (bug-check Opus, G3): mai
    materializzato l'insieme O(turni²) di tutte le coppie possibili — su
    un run sovra-clusterizzato (proprio il caso che questo comando serve a
    diagnosticare, con migliaia di turni) sarebbe qualche GB di RAM.
    """
    import random

    work = Path(work)
    manifest = _read_manifest(work)
    turns = json.loads((work / 'runs' / from_run / 'turns.json').read_text(encoding='utf-8'))
    turns = [(float(a), float(b), s) for a, b, s in turns]

    by_speaker: Dict[str, float] = {}
    for a, b, s in turns:
        by_speaker[s] = by_speaker.get(s, 0.0) + (b - a)
    speech_total = sum(by_speaker.values())
    tail_speakers = {s for s, d in by_speaker.items() if speech_total > 0 and d / speech_total < 0.02}

    rng = random.Random(20260907)  # seed fisso: l'oro deve essere riproducibile
    turns_sorted = sorted(turns, key=lambda t: t[0])
    n = len(turns_sorted)

    # Turni sotto questa soglia (artefatti pyannote da poche decine di ms,
    # o interiezioni troppo fugaci tipo un "Sì." tagliato corto) non danno
    # abbastanza audio per un giudizio umano affidabile nemmeno con un
    # margine di contesto — alzata da 0.15 a 0.4s dopo che l'utente ha
    # trovato in etichettatura una coppia da 0,34s ancora indistinguibile.
    MIN_TURN_S = 0.4

    # ── coppie locali, classificate come le vede DAVVERO il gate del
    # trattino (bug-check Opus, G1): speaker diverso è condizione
    # necessaria per 'local_dash', non solo il gap — altrimenti
    # 'local_same' risultava irraggiungibile per qualunque gap breve.
    local_candidates = []
    for i in range(n - 1):
        a, b = turns_sorted[i], turns_sorted[i + 1]
        if (a[1] - a[0]) < MIN_TURN_S or (b[1] - b[0]) < MIN_TURN_S:
            continue
        gap = b[0] - a[1]
        if not (-0.5 < gap < 3.0):
            continue
        if a[2] != b[2] and 0 <= gap <= 1.0:
            kind = 'local_dash'
        elif a[2] == b[2]:
            kind = 'local_same'
        else:
            kind = 'local_far'
        local_candidates.append((a, b, gap, kind, i, i + 1))

    # Quota per classe (bug-check Opus, G2): senza, su un film a 2
    # protagonisti le coppie same-speaker dominano e 'local_dash'/'local_
    # far' — le classi che contano — restano quasi assenti dal campione.
    by_kind: Dict[str, list] = {'local_dash': [], 'local_same': [], 'local_far': []}
    for c in local_candidates:
        by_kind[c[3]].append(c)
    for lst in by_kind.values():
        rng.shuffle(lst)
    quota = max(1, n_local // 3)
    chosen_local = (by_kind['local_dash'][:quota] + by_kind['local_same'][:quota]
                    + by_kind['local_far'][:quota])
    # Classi scarse: riempi con quel che resta delle altre, fino a n_local.
    leftover = (by_kind['local_dash'][quota:] + by_kind['local_same'][quota:]
                + by_kind['local_far'][quota:])
    rng.shuffle(leftover)
    chosen_local += leftover[:max(0, n_local - len(chosen_local))]
    if len(chosen_local) < n_local:
        _emit(f"  ⚠️ Solo {len(chosen_local)}/{n_local} coppie locali disponibili "
              f"(pochi turni o poca varietà di speaker in questo run)")

    # ── coppie a lunga distanza, campionamento per rifiuto ──
    tail_idx = [i for i, t in enumerate(turns_sorted)
                if t[2] in tail_speakers and (t[1] - t[0]) >= MIN_TURN_S]
    all_idx = [i for i, t in enumerate(turns_sorted) if (t[1] - t[0]) >= MIN_TURN_S]
    chosen_longrange = []
    seen_idx_pairs = set()
    attempts = 0
    while len(chosen_longrange) < n_longrange and attempts < max_attempts and n >= 2:
        attempts += 1
        i = rng.choice(tail_idx) if (tail_idx and rng.random() < 0.6) else rng.choice(all_idx)
        j = rng.choice(tail_idx) if (tail_idx and rng.random() < 0.6) else rng.choice(all_idx)
        if i == j:
            continue
        i, j = (i, j) if i < j else (j, i)
        if (i, j) in seen_idx_pairs:
            continue
        a, b = turns_sorted[i], turns_sorted[j]
        if b[0] - a[1] < 300:
            continue
        seen_idx_pairs.add((i, j))
        chosen_longrange.append((a, b, i, j))
    if len(chosen_longrange) < n_longrange:
        _emit(f"  ⚠️ Solo {len(chosen_longrange)}/{n_longrange} coppie a lunga distanza trovate "
              f"in {attempts} tentativi (film corto o pochi turni &gt;300s di distanza)")

    clips_dir = work / 'gold_clips'
    clips_dir.mkdir(exist_ok=True)
    pairs_out = []
    pid = 0
    clip_failures = 0

    for a, b, gap, kind, idx_a, idx_b in chosen_local:
        pid += 1
        mb_a, ma_a = _safe_margins(turns_sorted, idx_a, margin_s)
        mb_b, ma_b = _safe_margins(turns_sorted, idx_b, margin_s)
        ok_a = _clip_ok(a[0], a[1], manifest['audio_vocals'], clips_dir / f"pair_{pid:03d}_a.wav", mb_a, ma_a)
        ok_b = _clip_ok(b[0], b[1], manifest['audio_vocals'], clips_dir / f"pair_{pid:03d}_b.wav", mb_b, ma_b)
        clip_failures += (not ok_a) + (not ok_b)
        pairs_out.append({'id': pid, 'kind': kind, 'a': [a[0], a[1]], 'b': [b[0], b[1]],
                           'a_text': '', 'b_text': '', 'same_speaker': None,
                           'confidence': '', 'note': f"gap={gap:.2f}s pred_same={a[2] == b[2]}"})

    for a, b, idx_a, idx_b in chosen_longrange:
        pid += 1
        mb_a, ma_a = _safe_margins(turns_sorted, idx_a, margin_s)
        mb_b, ma_b = _safe_margins(turns_sorted, idx_b, margin_s)
        ok_a = _clip_ok(a[0], a[1], manifest['audio_vocals'], clips_dir / f"pair_{pid:03d}_a.wav", mb_a, ma_a)
        ok_b = _clip_ok(b[0], b[1], manifest['audio_vocals'], clips_dir / f"pair_{pid:03d}_b.wav", mb_b, ma_b)
        clip_failures += (not ok_a) + (not ok_b)
        pairs_out.append({'id': pid, 'kind': 'longrange', 'a': [a[0], a[1]], 'b': [b[0], b[1]],
                           'a_text': '', 'b_text': '', 'same_speaker': None,
                           'confidence': '', 'note': f"pred_same={a[2] == b[2]} (dist={b[0]-a[1]:.0f}s)"})

    if clip_failures:
        _emit(f"  ⚠️ {clip_failures} clip non estratte (FFmpeg fallito o file audio mancante) — "
              f"verifica {manifest['audio_vocals']}")

    gold_path = work / 'gold_pairs.json'
    _write_json(gold_path, {'schema': SCHEMA_GOLD, 'media': manifest['audio_vocals'],
                             'built_from_run': from_run, 'pairs': pairs_out})

    csv_path = work / 'gold_pairs.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['id', 'kind', 'clip_a', 'clip_b', 'note', 'same (S/N/?)'])
        for p in pairs_out:
            w.writerow([p['id'], p['kind'], f"pair_{p['id']:03d}_a.wav",
                        f"pair_{p['id']:03d}_b.wav", p['note'], ''])

    _emit(f"✅ {len(pairs_out)} coppie oro estratte in {clips_dir}")
    _emit(f"   Ascolta le clip e compila la colonna 'same (S/N/?)' in {csv_path}, "
          f"poi lancia 'gold-score' (che la rilegge e aggiorna gold_pairs.json).")
    return gold_path


def _sync_gold_csv_into_json(work: Path) -> List[Dict]:
    """Rilegge gold_pairs.csv (etichettato a mano) e aggiorna same_speaker
    in gold_pairs.json. S/N/vuoto -> rispettivamente True/False/None; ogni
    altro valore genera un avviso invece di sparire in silenzio (bug-check
    Opus, M3a: un refuso su 50 etichette a mano altrimenti passa inosservato).

    Parsing a TOKEN via regex, non csv.DictReader (trovato dall'utente):
    Excel in locale italiano risalva il file mischiando ',' (contenuto
    originale) e ';' (il suo separatore nativo) nella STESSA riga —
    es. 'id,kind,...,note,;;;;;;;n' — nessun dialect CSV standard
    interpreta correttamente questo ibrido. re.split su una RUN di ,/;
    consecutivi come un unico separatore recupera comunque i campi
    originali: le colonne vuote che Excel inserisce in mezzo (','+';;;;;;'
    consecutivi) collassano in un solo split-point, e l'etichetta
    digitata resta l'ultimo token reale della riga."""
    work = Path(work)
    gold = json.loads((work / 'gold_pairs.json').read_text(encoding='utf-8'))
    by_id = {p['id']: p for p in gold['pairs']}
    csv_path = work / 'gold_pairs.csv'

    with open(csv_path, encoding='utf-8-sig') as f:
        raw_lines = f.readlines()

    data_lines = [ln.rstrip('\r\n') for ln in raw_lines[1:] if ln.strip()]  # salta l'header
    if not data_lines:
        _emit(f"  ⚠️ {csv_path.name} vuoto o illeggibile — nessuna etichetta applicata")
        return gold['pairs']

    n_unrecognized = 0
    parsed_rows = []  # per il conteggio n_labeled_csv sotto
    for line in data_lines:
        tokens = re.split(r'[,;]+', line)
        while tokens and tokens[-1] == '':
            tokens.pop()
        if len(tokens) < 5:
            continue  # riga troncata/illeggibile, salta senza sollevare
        try:
            pid = int(tokens[0].strip())
        except ValueError:
            continue
        raw = tokens[5].strip() if len(tokens) >= 6 else ''
        parsed_rows.append(raw)
        label = raw.upper()
        if label == 'S':
            same = True
        elif label == 'N':
            same = False
        elif label in ('', '?'):
            same = None
        else:
            same = None
            n_unrecognized += 1
            _emit(f"  ⚠️ id={pid}: etichetta {raw!r} non riconosciuta (attese S/N/vuoto/?) — esclusa dal punteggio")
        if pid in by_id:
            by_id[pid]['same_speaker'] = same

    n_labeled_csv = sum(1 for r in parsed_rows if r)
    n_labeled_json_before = sum(1 for p in gold['pairs'] if p.get('same_speaker') is not None)
    if n_labeled_csv == 0 and n_labeled_json_before > 0:
        _emit(f"  ⚠️ {csv_path.name} non ha etichette ma gold_pairs.json ne aveva "
              f"{n_labeled_json_before} — stanno per essere azzerate. Se le etichette sono "
              f"nel JSON (editate a mano lì), non rilanciare questa sincronizzazione dal CSV.")

    _write_json(work / 'gold_pairs.json', gold)
    return gold['pairs']


def gold_score(work: Path, run_id: Optional[str] = None) -> None:
    work = Path(work)
    pairs = _sync_gold_csv_into_json(work)
    labeled = sum(1 for p in pairs if p['same_speaker'] is not None)
    _emit(f"  {labeled}/{len(pairs)} coppie etichettate")
    if labeled == 0:
        _emit("  ⚠️ Nessuna coppia etichettata in gold_pairs.csv — niente da valutare")
        return

    run_ids = [run_id] if run_id else sorted(
        p.name for p in (work / 'runs').iterdir() if (p / 'turns.json').exists())
    for rid in run_ids:
        turns_path = work / 'runs' / rid / 'turns.json'
        if not turns_path.exists():
            continue
        turns = [(float(a), float(b), s) for a, b, s in json.loads(turns_path.read_text(encoding='utf-8'))]
        score = m.score_gold(pairs, turns)
        _emit(f"  {rid}: recall_same={score['recall_same']} spec_diff={score['spec_diff']} "
              f"balanced_acc={score['balanced_acc']} (tp={score['tp']} fp={score['fp']} "
              f"tn={score['tn']} fn={score['fn']} sbagliate={score['wrong_ids']})")
        if score['n_unmatched']:
            # Nessun parlato rilevato su un lato della coppia (v. metrics.py,
            # bug-check Opus): confrontare balanced_acc fra due modelli con
            # n_unmatched diverso da zero su uno solo dei due non è onesto.
            _emit(f"  ⚠️ {rid}: {score['n_unmatched']} coppie senza speaker rilevato su "
                  f"un lato — balanced_acc confrontabile con un altro run solo se anche "
                  f"lì n_unmatched è vicino a questo valore")
        # aggiorna la riga già scritta in runs.csv/metrics.json con i punteggi oro
        metrics_path = work / 'runs' / rid / 'metrics.json'
        if metrics_path.exists():
            row = json.loads(metrics_path.read_text(encoding='utf-8'))
            row.update(gold_recall_same=score['recall_same'], gold_spec_diff=score['spec_diff'],
                       gold_balanced_acc=score['balanced_acc'])
            _write_json(metrics_path, row)

    _rewrite_csv_from_metrics(work)  # bug-check Opus, B2: senza, runs.csv non vede mai i punteggi oro
    _emit(f"  ✅ runs.csv aggiornato con i punteggi oro")


# ── sweep-c: stage 3, nessuna GPU ─────────────────────────────────────────

def sweep_c(work: Path, from_run: str, *, thresholds: Optional[List[float]] = None,
            v2_params: Optional[Dict] = None) -> None:
    from utils.config import get_config
    from core.diarizer import Diarizer
    from core.subtitle_formatter import SubtitleFormatter

    work = Path(work)
    thresholds = thresholds or [round(x * 0.05, 2) for x in range(19)]  # 0.00..0.90
    turns = json.loads((work / 'runs' / from_run / 'turns.json').read_text(encoding='utf-8'))
    turns = [(float(a), float(b), s) for a, b, s in turns]

    config = get_config()
    diar = Diarizer(config.get_huggingface_token(), _emit)
    # NIENTE diar.load(): assign_speakers non usa il modello pyannote. Se un
    # giorno dovesse servirlo, questo va in eccezione subito — non produce
    # numeri sbagliati in silenzio.

    results = {}
    for algo, word_vote in (('v1', False), ('v2', True)):
        segments = load_segments(work / 'segments.json')
        annotated = diar.assign_speakers(segments, turns, word_vote=word_vote,
                                          tolerance_ms=None, v2_params=v2_params)
        confidences = [s.get('speaker_confidence') for s in annotated if s.get('speaker') is not None]
        n_dash = {}
        for thr in thresholds:
            fmt = SubtitleFormatter(dash_confidence_min=thr, log_callback=lambda _m: None)
            srt = fmt.format_srt([dict(s) for s in annotated])
            # Blocchi dialogo, non righe con trattino (bug-check Opus, M2):
            # un blocco a due voci produce 2 righe "- ", contarle raddoppia
            # il numero rispetto a n_dialogue_blocks di run_combo. Nota:
            # qui si misura sull'SRT FORMATTATO, run_combo su quello
            # ripulito da SubtitleCleaner — i due conteggi non sono
            # incrociabili 1:1, coerente col fatto che sweep-c isola la
            # sola scelta della soglia, non l'intera pipeline di output.
            n_dash[thr] = m.count_dialogue_blocks(m.parse_srt_text(srt))
        results[algo] = {'confidences': confidences, 'n_dash': n_dash, 'n_subsegments': len(annotated)}

    n0 = results['v1']['n_dash'].get(0.0, 0) or 1
    _emit(f"\nCoppie ammissibili (thr=0.00): v1={results['v1']['n_dash'].get(0.0)}  "
          f"v2={results['v2']['n_dash'].get(0.0)}")
    _emit(f"{'thr':>6} | {'v1:dash':>8} {'%acc':>6} | {'v2:dash':>8} {'%acc':>6}")
    for thr in thresholds:
        v1n = results['v1']['n_dash'][thr]
        v2n = results['v2']['n_dash'][thr]
        v1_0 = results['v1']['n_dash'].get(0.0) or 1
        v2_0 = results['v2']['n_dash'].get(0.0) or 1
        _emit(f"{thr:>6.2f} | {v1n:>8} {100*v1n/v1_0:>5.1f}% | {v2n:>8} {100*v2n/v2_0:>5.1f}%")

    for algo in ('v1', 'v2'):
        bins = m.histogram([c for c in results[algo]['confidences'] if c is not None])
        _emit(m.render_histogram(bins, algo))

    _write_json(work / 'sweep_c.json', {
        'from_run': from_run, 'thresholds': thresholds,
        'v1': {'n_dash': results['v1']['n_dash'], 'n_subsegments': results['v1']['n_subsegments']},
        'v2': {'n_dash': results['v2']['n_dash'], 'n_subsegments': results['v2']['n_subsegments']},
    })
    with open(work / 'sweep_c.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['thr', 'v1_dash', 'v2_dash'])
        for thr in thresholds:
            w.writerow([thr, results['v1']['n_dash'][thr], results['v2']['n_dash'][thr]])
    _emit(f"✅ sweep-c scritto in {work / 'sweep_c.csv'}")


# ── report ─────────────────────────────────────────────────────────────────

def report(work: Path) -> None:
    csv_path = Path(work) / 'runs.csv'
    if not csv_path.exists():
        _emit("Nessun run.csv trovato — lancia 'run' prima.")
        return
    with open(csv_path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    # 'model' in tabella (bug-check Opus #3): senza, due arm dello stesso
    # thr su modelli diversi sono indistinguibili proprio nel confronto per
    # cui la colonna è stata aggiunta. Cella vuota = riga pre-refactoring,
    # cioè pyannote/speaker-diarization-3.1.
    cols = ['run_id', 'model', 'source', 'thr', 'mcs', 'max_spk', 'word_vote', 'speakers', 'turns',
            'tail_lt2pct', 'n_subsegments', 'n_dialogue_blocks_cleaned',
            'gold_balanced_acc', 'elapsed_s']
    # r.get(c, '') non basta: DictReader mette la chiave con valore None
    # (non '') per le colonne mancanti su una riga più corta dell'header
    # (bug-check Opus, M1a) -> len(None) solleverebbe TypeError.
    widths = {c: max(len(c), max((len(str(r.get(c) or '')) for r in rows), default=0)) for c in cols}
    _emit(' | '.join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        # `r.get(c) or ''` come nel calcolo di widths sopra: r.get(c, '')
        # stamperebbe la stringa 'None' (4 caratteri) là dove la larghezza
        # è stata calcolata su '' (0), sfasando la tabella.
        _emit(' | '.join(str(r.get(c) or '').ljust(widths[c]) for c in cols))


# ── CLI ──────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('prepare')
    sp.add_argument('--video', required=True, type=Path)
    sp.add_argument('--work', required=True, type=Path)
    sp.add_argument('--force', action='store_true')
    sp.add_argument('--keep-chunks', action='store_true')

    sr = sub.add_parser('run')
    sr.add_argument('--work', required=True, type=Path)
    sr.add_argument('--run-id', required=True)
    sr.add_argument('--source', choices=['vocals', 'original'], default='vocals')
    sr.add_argument('--threshold', type=float, default=-1.0,
                     help="<0 o omesso: da config globale; 0: DEFAULT DI FABBRICA "
                          "del modello (0.7046 su 3.1, 0.6 su community-1); >0: quel valore")
    sr.add_argument('--min-cluster-size', type=int, default=-1,
                     help="<0 o omesso: da config globale; 0: default di fabbrica "
                          "del modello (12 su 3.1; non esiste su community-1); >0: quel valore")
    sr.add_argument('--min-speakers', type=int, default=0)
    sr.add_argument('--max-speakers', type=int, default=0)
    sr.add_argument('--dash-confidence-min', type=float, default=0.55)
    sr.add_argument('--word-vote', action='store_true')
    sr.add_argument('--v2-param', action='append', default=[], metavar='KEY=VALUE',
                     help="parametro di _split_at_speaker_changes_v2, ripetibile "
                          "(es. --v2-param short_run_margin_keep=0.5). Solo con --word-vote.")
    sr.add_argument('--model', default=None,
                     help="pipeline pyannote da usare (default: da config, "
                          "pyannote/speaker-diarization-3.1)")

    sg = sub.add_parser('gold-make')
    sg.add_argument('--work', required=True, type=Path)
    sg.add_argument('--from-run', default='R0')
    sg.add_argument('--n-local', type=int, default=30)
    sg.add_argument('--n-longrange', type=int, default=20)

    sc = sub.add_parser('gold-score')
    sc.add_argument('--work', required=True, type=Path)
    sc.add_argument('--run-id', default=None)

    sw = sub.add_parser('sweep-c')
    sw.add_argument('--work', required=True, type=Path)
    sw.add_argument('--from-run', required=True)
    sw.add_argument('--v2-param', action='append', default=[], metavar='KEY=VALUE')

    rp = sub.add_parser('report')
    rp.add_argument('--work', required=True, type=Path)

    args = p.parse_args(argv[1:])

    if args.cmd == 'prepare':
        prepare(args.video, args.work, force=args.force, keep_chunks=args.keep_chunks)
    elif args.cmd == 'run':
        v2_params = _parse_v2_params(args.v2_param)
        run_combo(args.work, args.run_id, source=args.source, threshold=args.threshold,
                  min_cluster_size=args.min_cluster_size, min_speakers=args.min_speakers,
                  max_speakers=args.max_speakers, dash_confidence_min=args.dash_confidence_min,
                  word_vote=args.word_vote, v2_params=v2_params, model=args.model)
    elif args.cmd == 'gold-make':
        gold_make(args.work, from_run=args.from_run, n_local=args.n_local, n_longrange=args.n_longrange)
    elif args.cmd == 'gold-score':
        gold_score(args.work, run_id=args.run_id)
    elif args.cmd == 'sweep-c':
        v2_params = _parse_v2_params(args.v2_param)
        sweep_c(args.work, args.from_run, v2_params=v2_params)
    elif args.cmd == 'report':
        report(args.work)
    return 0


def _parse_v2_params(pairs: List[str]) -> Optional[Dict]:
    """'k=v' ripetuti -> dict con v castato a float/int/bool quando possibile."""
    if not pairs:
        return None
    out = {}
    for item in pairs:
        k, _, v = item.partition('=')
        if v.lower() in ('true', 'false'):
            out[k] = v.lower() == 'true'
        else:
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main(sys.argv))
