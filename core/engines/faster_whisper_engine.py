"""
Faster-Whisper Engine - Refactor del transcriber storico nell'interfaccia engine
File: core/engines/faster_whisper_engine.py

VERSIONE: v1.0 - SISTEMA MULTI-ENGINE

MODIFICHE v1.0:
✅ Porting 1:1 del codice faster-whisper da core/transcriber.py v3.5
   (stessi parametri WhisperModel/transcribe, stesso VAD, stessi profili,
   stessa gestione lingua, stesso splitting per word timestamps)
✅ Adattato all'interfaccia TranscriptionEngine (load/unload/transcribe_chunks)
✅ Nessuna modifica comportamentale: con engine 'faster-whisper' l'output è
   INDISTINGUIBILE dalla versione precedente

VINCOLO CRITICO (invariato): NON chiamare torch.cuda.synchronize()/empty_cache()
PRIMA di WhisperModel() — ctranslate2 deve inizializzare il contesto CUDA
per primo (vedi memory/MEMORY.md - Critical Dependency Constraints).
"""
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import torch

from core.engines.base_engine import TranscriptionEngine
from utils.logger import setup_logger
from utils.config import get_config
from utils.transcription_profiles import ProfileConfig, TranscriptionProfile
from utils.cache_bootstrap import HF_HUB_CACHE_DIR

logger = setup_logger()


class FasterWhisperEngine(TranscriptionEngine):
    """
    Engine faster-whisper (large-v3) con profili dinamici.
    Fallback universale: supporta TUTTE le lingue + auto-detect.
    """

    name = "faster-whisper"

    def __init__(self, log_callback: Optional[Callable] = None):
        super().__init__(log_callback=log_callback)
        self.config = get_config()

        device_config = self.config.get('whisper_device', 'auto')
        if device_config == 'auto':
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device_config

        self.faster_whisper_model = None
        self.vad_available = False

        # Carica parametri profilo (num_workers, beam_size)
        self._load_profile_params()

        # Adaptive batch manager (stesse chiavi config del translator)
        from utils.adaptive_batch_manager import AdaptiveBatchSizeManager
        profile_config = ProfileConfig.get_profile_config(self.profile)
        batch_hint = profile_config.get('batch_size_hint', None)

        cfg = self.config.get_adaptive_batch_config() if self.config else {}
        # Per la trascrizione, cap high_threshold a 0.75 (OOM in ctranslate2 è fatale)
        ht = min(cfg.get('high_threshold', 0.85), 0.75)
        # Cap max_size a 16: la chiave config è condivisa col translator (dove
        # 62 ha senso per frasi NLLB), ma per whisper batch grandi gonfiano i
        # workspace ctranslate2 — che NON vengono mai rilasciati — fino allo
        # spillover WDDM in RAM condivisa (misurati 4,2 GB con batch 62).
        self.batch_manager = AdaptiveBatchSizeManager(
            device=self.device,
            use_gpu=(self.device == 'cuda'),
            initial_size=batch_hint or cfg.get('initial_size'),
            min_size=cfg.get('min_size', 1),
            max_size=min(cfg.get('max_size', 24), 16),
            warmup_batches=cfg.get('warmup_batches', 5),
            high_threshold=ht,
            low_threshold=cfg.get('low_threshold', 0.60),
            log_callback=self.log_callback,
        )
        self.batch_size_for_transcription = None  # None finché BatchedInferencePipeline non disponibile

    # ------------------------------------------------------------------
    # Capability detection
    # ------------------------------------------------------------------
    @classmethod
    def is_available(cls) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    @classmethod
    def supports_language(cls, lang_639_1: Optional[str]) -> bool:
        # Fallback universale: qualsiasi lingua, incluso auto-detect (None)
        return True

    # ------------------------------------------------------------------
    # Profili
    # ------------------------------------------------------------------
    def _load_profile_params(self):
        """Carica parametri dal profilo corrente"""
        profile_str = self.config.get_transcription_profile()

        try:
            self.profile = ProfileConfig.from_string(profile_str)
        except ValueError:
            logger.warning(f"Profilo '{profile_str}' non valido, uso 'balanced'")
            self.profile = TranscriptionProfile.BALANCED

        params = ProfileConfig.get_transcription_params(self.profile)
        profile_config = ProfileConfig.get_profile_config(self.profile)

        self.num_workers = params['num_workers']
        self.beam_size = params['beam_size']
        self.profile_name = profile_config['name']

        logger.info(f"✅ Parametri profilo caricati: {self.profile_name}")
        logger.info(f"   - num_workers: {self.num_workers}")
        logger.info(f"   - beam_size: {self.beam_size}")

    def reload_profile(self):
        """Ricarica parametri profilo dalla config"""
        old_workers = self.num_workers
        old_beam = self.beam_size

        self._load_profile_params()

        if old_workers != self.num_workers:
            logger.info(f"⚠️ num_workers cambiato ({old_workers}→{self.num_workers}), reinizializzo modello...")
            self.unload()
            self.load()

        if old_beam != self.beam_size:
            logger.info(f"✅ beam_size aggiornato ({old_beam}→{self.beam_size})")

    def set_files_processed(self, count: int):
        """Passa il contatore fatigue al batch_manager per riduzione preventiva batch_size."""
        self.batch_manager.set_files_processed(count)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load(self):
        """
        Inizializza modello faster-whisper (identico a _init_faster_whisper v3.5)
        """
        if self.faster_whisper_model is not None:
            return
        try:
            from faster_whisper import WhisperModel
            try:
                from faster_whisper import BatchedInferencePipeline
                _batched_available = True
            except ImportError:
                _batched_available = False

            # NON chiamare torch.cuda.synchronize() / empty_cache() qui.
            # ctranslate2 ≥4.7 usa lazy CUDA init e richiede di essere il
            # primo a inizializzare il contesto CUDA del processo.
            # Se PyTorch chiama cudaDeviceSynchronize() prima (via synchronize()),
            # crea il contesto con i propri flag → ctranslate2 trova un contesto
            # incompatibile e chiama std::abort() silenziosamente.
            # Il cleanup pre-load è gestito da unload() prima del reload.

            model_size = self.config.get('whisper_model', 'large-v3')

            self.log(f"  📦 Caricamento modello {model_size}...")
            self.log(f"  ⚙️ Profilo: {self.profile_name}")
            self.log(f"  👷 Workers: {self.num_workers} | 🎯 Beam: {self.beam_size}")

            if self.device == "cuda":
                # int8_float16: pesi INT8 (~1.5GB vs ~3GB float16), compute FP16.
                # Più robusto dopo Demucs (VRAM frammentata) — qualità identica.
                compute_type = "int8_float16"
                device_index = 0

                import gc
                gc.collect()

                self.faster_whisper_model = WhisperModel(
                    model_size,
                    device="cuda",
                    device_index=device_index,
                    compute_type=compute_type,
                    num_workers=self.num_workers,
                    cpu_threads=self.num_workers,
                    download_root=HF_HUB_CACHE_DIR,
                )

                self.log(f"  ✅ Modello {model_size} caricato su CUDA con {self.num_workers} workers")
            else:
                self.faster_whisper_model = WhisperModel(
                    model_size,
                    device="cpu",
                    compute_type="int8",
                    num_workers=self.num_workers,
                    cpu_threads=self.num_workers,
                    download_root=HF_HUB_CACHE_DIR,
                )

                self.log(f"  ✅ Modello {model_size} caricato su CPU con {self.num_workers} workers")

            # VAD check sul WhisperModel puro (prima del wrapping)
            self._check_vad_availability()

            # Future-ready: attiva BatchedInferencePipeline se disponibile
            if _batched_available:
                self.faster_whisper_model = BatchedInferencePipeline(self.faster_whisper_model)
                self.batch_size_for_transcription = self.batch_manager.current_batch_size
                self.log(f"  BatchedInferencePipeline attivo (batch_size={self.batch_size_for_transcription})")
            else:
                self.batch_size_for_transcription = None
                self.log("  BatchedInferencePipeline non disponibile — elaborazione sequenziale")

        except Exception as e:
            error_msg = f"❌ Errore caricamento modello Faster-Whisper: {e}"
            self.log(error_msg)
            logger.error(error_msg, exc_info=True)
            raise

    def unload(self):
        """Pulizia risorse GPU (identica a cleanup() v3.5)"""
        try:
            if self.faster_whisper_model:
                del self.faster_whisper_model
                self.faster_whisper_model = None
            import gc; gc.collect()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()

            logger.info("✅ FasterWhisperEngine unload completato")
        except Exception as e:
            logger.error(f"Errore durante unload: {e}")

    def _check_vad_availability(self):
        """Verifica se il VAD è disponibile/funzionante"""
        try:
            import numpy as np
            dummy_audio = np.zeros(16000, dtype=np.float32)

            segments, info = self.faster_whisper_model.transcribe(
                dummy_audio,
                language="en",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )

            _ = list(segments)
            self.vad_available = True
            self.log("  ✅ VAD (Voice Activity Detection) disponibile")
            logger.info("VAD test successful - enabled")

        except Exception as e:
            self.vad_available = False
            self.log("  ⚠️ VAD non disponibile, uso modalità standard")
            logger.warning(f"VAD not available: {e}")

    # ------------------------------------------------------------------
    # Trascrizione (identica a transcribe_chunks v3.5)
    # ------------------------------------------------------------------
    def transcribe_chunks(
        self,
        audio_chunks: List[tuple],
        output_path: str,
        language: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Trascrizione usando Faster-Whisper di chunk multipli
        """
        # Import a livello di funzione per evitare dipendenze circolari
        # con la facade core/transcriber.py
        from core.transcriber import save_srt_file

        if self.faster_whisper_model is None:
            self.load()

        whisper_language = language
        total_chunks = len(audio_chunks)

        # Lista di codici lingua invalidi o indefiniti
        invalid_language_codes = ['und', 'unknown', 'undefined', 'n/a', 'none', '']

        # Gestione lingua indefinita: faster-whisper rileverà automaticamente
        auto_detect = False
        if whisper_language is None or whisper_language.lower().strip() in invalid_language_codes:
            whisper_language = None  # None farà rilevare automaticamente la lingua
            auto_detect = True
            logger.info("Codice lingua non specificato, attivo rilevamento automatico")
        else:
            # FIX: Assicuriamo che il codice lingua sia a 2 lettere (ISO 639-1)
            # Faster-Whisper accetta sia 2 che 3 lettere, ma per sicurezza usiamo 2
            if len(whisper_language) == 3:
                 # Mappa inversa (ITA -> IT)
                 lang_map_3_to_2 = {'ita': 'it', 'eng': 'en', 'spa': 'es', 'fre': 'fr', 'deu': 'de', 'por': 'pt', 'rus': 'ru', 'jpn': 'ja'}
                 whisper_language = lang_map_3_to_2.get(whisper_language.lower(), whisper_language)

        all_segments = []
        detected_language = None

        # ── Modalità BatchedInferencePipeline: file unico, nessun chunking ──
        batched_mode = (
            len(audio_chunks) == 1 and self.batch_size_for_transcription is not None
        )

        if batched_mode:
            chunk_path, _, total_duration = audio_chunks[0]

            # VRAM pre-transcription logging
            free_vram = self.batch_manager._get_free_vram_gb()
            total_vram = self.batch_manager._get_total_vram_gb()
            if total_vram > 0:
                used_pct = int(((total_vram - free_vram) / total_vram) * 100)
                self.log(
                    f"  📊 VRAM pre-transcription: {free_vram:.1f}/{total_vram:.1f} GB free "
                    f"({used_pct}% used)"
                )

            # Batch size: min(adaptive, safe ceiling basato su VRAM reale)
            adaptive_bs = self.batch_manager.get_batch_size()
            safe_bs = self.batch_manager.compute_safe_batch_size(
                audio_duration_s=total_duration,
                beam_size=self.beam_size,
            )
            bs = min(adaptive_bs, safe_bs)
            self.log(
                f"  📊 Batch size: adaptive={adaptive_bs}, safe_ceiling={safe_bs}, "
                f"using={bs}"
            )
            self.log(f"  📊 BatchedInferencePipeline — file unico ({total_duration:.0f}s), batch_size={bs}")
            self.log(f"  ⚙️ Profilo: {self.profile_name} (beam={self.beam_size})")
            if auto_detect:
                self.log("  🎯 Lingua: AUTO-DETECT")
            else:
                self.log(f"  🎯 Lingua: {whisper_language}")

            # BatchedInferencePipeline richiede vad_filter=True obbligatoriamente
            # word_timestamps=True per splitting preciso dei segmenti lunghi
            transcribe_kwargs = dict(
                language=whisper_language,
                beam_size=self.beam_size,
                batch_size=bs,
                word_timestamps=True,
            )
            try:
                segments, info = self.faster_whisper_model.transcribe(
                    str(chunk_path),
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500, threshold=0.5),
                    **transcribe_kwargs
                )

                detected_language = info.language if hasattr(info, 'language') else None
                if detected_language and auto_detect:
                    self.log(f"  🔍 Lingua rilevata automaticamente: {detected_language}")

                last_pct = -1
                t0_transcribe = time.time()
                for segment in segments:
                    if self._cancelled:
                        break
                    all_segments.append({
                        'start': segment.start,
                        'end': segment.end,
                        'text': segment.text.strip(),
                        'words': [
                            {'start': w.start, 'end': w.end, 'word': w.word}
                            for w in (segment.words or [])
                        ],
                    })
                    if total_duration > 0:
                        pct = min(int((segment.end / total_duration) * 100), 99)
                        if pct != last_pct:
                            bars = int(pct / 10)
                            bar = '█' * bars + '░' * (10 - bars)
                            self.log(f"  🎙️ Trascrizione: [{bar}] {pct:3d}%")
                            last_pct = pct

                elapsed = time.time() - t0_transcribe
                mins, secs = divmod(int(elapsed), 60)
                time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
                self.log(f"  ✅ Trascrizione: [██████████] 100% │ {time_str}")

                # Suddividi segmenti lunghi usando i word timestamps
                raw_count = len(all_segments)
                # lingua del file: serve allo split per frasi (misurato solo sull'inglese)
                self._split_lang = detected_language or whisper_language
                split_segments = []
                for seg in all_segments:
                    split_segments.extend(self._split_segment_by_words(seg))
                all_segments = split_segments
                self.log(f"  ✂️ Suddivisione: {raw_count} → {len(all_segments)} segmenti")
                self._last_segments = all_segments   # esposto per diarization in pipeline

            except Exception as e:
                logger.error(f"❌ Errore BatchedInferencePipeline: {e}", exc_info=True)
                self.log(f"  ❌ Errore trascrizione: {str(e)}")

        else:
            # ── Modalità classica: N chunk sequenziali ──
            failed_chunks = 0
            last_progress_pct = -1
            t0_transcribe = time.time()

            self.log(f"  📊 Trascrizione di {total_chunks} chunks audio...")
            self.log(f"  ⚙️ Profilo: {self.profile_name} (beam={self.beam_size}, workers={self.num_workers})")
            if auto_detect:
                self.log("  🎯 Lingua: AUTO-DETECT (rilevamento automatico)")
            else:
                self.log(f"  🎯 Lingua: {whisper_language}")

            # Tetto VRAM-aware anche in modalità classica (come nel batched):
            # calcolato UNA volta sulla VRAM libera reale a inizio file — il
            # batch adattivo non può superarlo, qualunque cosa dica la lettura
            # di memoria (i workspace ctranslate2 si materializzano in ritardo
            # e su Windows/WDDM lo sforamento non dà OOM ma spillover in RAM)
            safe_ceiling = None
            if self.batch_size_for_transcription is not None:
                try:
                    total_audio_s = sum(
                        float(c[2]) - float(c[1]) for c in audio_chunks)
                    safe_ceiling = self.batch_manager.compute_safe_batch_size(
                        audio_duration_s=total_audio_s,
                        beam_size=self.beam_size,
                    )
                except Exception:
                    safe_ceiling = None

            for i, (chunk_path, start_time, end_time) in enumerate(audio_chunks):
                if self._cancelled:
                    break
                chunk_num = i + 1
                try:
                    chunk_path_obj = Path(chunk_path)
                    if not chunk_path_obj.exists():
                        logger.error(f"Chunk {chunk_num} non trovato: {chunk_path}")
                        failed_chunks += 1
                        continue

                    transcribe_kwargs = dict(language=whisper_language, beam_size=self.beam_size)
                    if self.batch_size_for_transcription is not None:
                        _bs = self.batch_manager.get_batch_size()
                        if safe_ceiling is not None:
                            _bs = min(_bs, safe_ceiling)
                        transcribe_kwargs['batch_size'] = _bs

                    if self.vad_available:
                        segments, info = self.faster_whisper_model.transcribe(
                            str(chunk_path),
                            vad_filter=True,
                            vad_parameters=dict(min_silence_duration_ms=500, threshold=0.5),
                            **transcribe_kwargs
                        )
                    else:
                        segments, info = self.faster_whisper_model.transcribe(
                            str(chunk_path),
                            vad_filter=False,
                            word_timestamps=False,
                            **transcribe_kwargs
                        )

                    if detected_language is None:
                        detected_language = info.language if hasattr(info, 'language') else None
                        if detected_language and auto_detect:
                            self.log(f"  🔍 Lingua rilevata automaticamente: {detected_language}")

                    for segment in segments:
                        all_segments.append({
                            'start': segment.start + start_time,
                            'end': segment.end + start_time,
                            'text': segment.text.strip()
                        })

                    pct = int((chunk_num / total_chunks) * 100)
                    if pct != last_progress_pct:
                        bars = int(pct / 10)
                        bar = '█' * bars + '░' * (10 - bars)
                        self.log(f"  🎙️ Trascrizione: [{bar}] {pct:3d}% ({chunk_num}/{total_chunks})")
                        last_progress_pct = pct

                except Exception as e:
                    error_msg = f"❌ ERRORE chunk {chunk_num}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    failed_chunks += 1
                    continue

            elapsed = time.time() - t0_transcribe
            mins, secs = divmod(int(elapsed), 60)
            time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
            if failed_chunks > 0:
                self.log(f"  ⚠️ Completato con {failed_chunks} chunks falliti su {total_chunks}")
            self.log(f"  ✅ Trascrizione: [██████████] 100% ({total_chunks}/{total_chunks}) │ {time_str}")
            self._last_segments = all_segments   # esposto per diarization in pipeline

        self.log(f"  📝 Totale segmenti trascritti: {len(all_segments)}")

        # Salva se richiesto
        if output_path and all_segments:
            save_success = save_srt_file(all_segments, Path(output_path))
            return save_success, detected_language

        return len(all_segments) > 0, detected_language

    def _split_segment_by_words(
        self,
        segment: dict,
        max_chars: int = 80,
        max_duration: float = 6.0,
    ) -> list:
        """
        Divide un segmento lungo in sotto-segmenti usando i word timestamps.
        Restituisce una lista di dict {start, end, text} pronti per save_srt_file.
        """
        # ── split per confini di frase (core/whisper_sentence_split.py)
        # Attivo solo per le lingue in 'whisper_split_sentence_langs' (codici a 2
        # lettere, default ['en']: l'inglese e' l'unica lingua misurata; 'it' ha
        # regole proprie). Se solleva o il risultato non e' valido si prosegue
        # con lo split originale qui sotto (intatto). Rimovibile in blocco.
        _ss_lang = str(getattr(self, '_split_lang', '') or '').lower()[:2]
        if self.config.get('whisper_split_sentence_aware', False) and _ss_lang:
            _ss_langs = self.config.get('whisper_split_sentence_langs', ['en'])
            if _ss_langs is None:
                _ss_langs = ['en']
            elif isinstance(_ss_langs, str):
                _ss_langs = [x for x in _ss_langs.replace(';', ',').replace(' ', ',').split(',') if x]
            elif not isinstance(_ss_langs, (list, tuple, set, frozenset)):
                _ss_langs = []
            _ss_on = _ss_lang in {str(x).strip().lower()[:2] for x in (_ss_langs or ())}
        else:
            _ss_on = False
        if _ss_on:
            try:
                from core.whisper_sentence_split import sentence_aware_split, validate_split
                _res = sentence_aware_split(segment, max_chars, max_duration, lang=_ss_lang)
                if _res is not None and validate_split(segment, _res):
                    return _res
            except Exception as _e:
                if not getattr(self, '_sentence_split_warned', False):
                    self._sentence_split_warned = True
                    logger.warning(f"whisper_sentence_split fallito, uso lo split originale: {_e}")
                else:
                    logger.debug(f"whisper_sentence_split fallito, uso lo split originale: {_e}")
        # ── fine blocco opzionale

        words = segment.get('words', [])
        text = segment['text']
        duration = segment['end'] - segment['start']

        # Segmento già corto: nessuno split necessario
        if not words or (len(text) <= max_chars and duration <= max_duration):
            return [{'start': segment['start'], 'end': segment['end'],
                     'text': text, 'words': words}]

        result = []
        current_words = []
        current_start = None
        current_text = ''

        for word in words:
            w_text = word['word']
            if current_start is None:
                current_start = word['start']

            candidate_text = current_text + w_text
            candidate_duration = word['end'] - current_start

            if current_words and (
                len(candidate_text.strip()) > max_chars
                or candidate_duration > max_duration
            ):
                # Chiudi segmento corrente (preserva words per diarization word-level)
                result.append({
                    'start': current_start,
                    'end': current_words[-1]['end'],
                    'text': current_text.strip(),
                    'words': list(current_words),
                })
                # Inizia nuovo segmento
                current_start = word['start']
                current_text = w_text
                current_words = [word]
            else:
                current_text = candidate_text
                current_words.append(word)

        # Ultimo segmento residuo
        if current_words and current_text.strip():
            result.append({
                'start': current_start,
                'end': current_words[-1]['end'],
                'text': current_text.strip(),
                'words': list(current_words),
            })

        # Anti-frammento: se il residuo finale ha < 4 parole, riunirlo al
        # chunk precedente — ma SOLO se è un vero frammento della stessa
        # frase (pausa breve E frase precedente non conclusa). Una battuta
        # autonoma dopo una pausa resta un sottotitolo a sé, ancorato ai
        # suoi timestamp (stessa regola dell'engine Qwen3).
        if len(result) >= 2 and len(result[-1]['words']) < 4:
            tail = result[-1]
            prev = result[-2]
            tail_gap = tail['words'][0]['start'] - prev['words'][-1]['end']
            prev_concluded = prev['text'].rstrip().endswith(
                ('.', '!', '?', '…', '。', '！', '？'))
            if tail_gap <= 0.8 and not prev_concluded:
                result.pop()
                result[-1] = {
                    'start': prev['start'],
                    'end':   tail['end'],
                    'text':  (prev['text'] + ' ' + tail['text']).strip(),
                    'words': prev['words'] + tail['words'],
                }

        return result or [{'start': segment['start'], 'end': segment['end'], 'text': text}]
