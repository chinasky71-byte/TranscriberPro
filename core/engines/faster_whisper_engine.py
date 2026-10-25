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
from utils.eta import EtaEstimator
from utils.transcription_profiles import ProfileConfig, TranscriptionProfile
from utils.cache_bootstrap import HF_HUB_CACHE_DIR
from utils.translations import tr

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
        # Lingua prevista (ISO 639-1): sceglie il modello specializzato gia' al
        # pre-load dello STEP 2.5; loaded_model = modello effettivamente in VRAM.
        self.language_hint: Optional[str] = None
        self.loaded_model: Optional[str] = None
        self._failed_models: set = set()   # modelli per lingua gia' falliti in questo processo

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
    # Modello per lingua (whisper_model_by_language)
    # ------------------------------------------------------------------
    @staticmethod
    def language_model_spec(config, lang_639_1: Optional[str]) -> Optional[str]:
        """Modello specializzato configurato per la lingua, o None."""
        from core.engine_router import normalize_language
        lang_639_1 = normalize_language(lang_639_1)
        if not lang_639_1:
            return None
        table = config.get('whisper_model_by_language', {}) or {}
        spec = table.get(str(lang_639_1).lower().strip()) if isinstance(table, dict) else None
        return str(spec).strip() if spec else None

    def _target_model(self, lang_639_1: Optional[str]) -> str:
        default_model = self.config.get('whisper_model', 'large-v3')
        spec = self.language_model_spec(self.config, lang_639_1)
        return spec if spec and spec not in self._failed_models else default_model

    @staticmethod
    def _resolve_model_path(spec: str) -> str:
        """
        Converte la specifica in qualcosa che WhisperModel sa caricare.

        - cartella locale esistente o nome standard ('large-v3')  -> invariato
        - 'utente/repo'                -> invariato (download nativo di faster-whisper)
        - 'utente/repo/sottocartella'  -> snapshot della sola sottocartella nella
          cache HF, restituisce il percorso locale (faster-whisper cerca i file
          CTranslate2 solo nella radice del repo).
        """
        if Path(spec).exists() or spec.count('/') < 2:
            return spec
        owner, repo, sub = spec.split('/', 2)
        from huggingface_hub import snapshot_download
        repo_id = f"{owner}/{repo}"
        kw = dict(allow_patterns=[f"{sub}/*"], cache_dir=HF_HUB_CACHE_DIR)
        try:
            root = snapshot_download(repo_id, local_files_only=True, **kw)
        except Exception:
            root = snapshot_download(repo_id, **kw)
        path = Path(root) / sub
        if not (path / 'model.bin').exists():
            raise FileNotFoundError(tr('fw_model_bin_missing_in').format(path=path))
        return str(path)

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

            default_model = self.config.get('whisper_model', 'large-v3')
            model_size = self._target_model(self.language_hint)
            specialized = model_size != default_model

            self.log(tr('fw_loading_model').format(model_size=model_size))
            self.log(tr('fw_profile').format(profile_name=self.profile_name))
            self.log(f"  👷 Workers: {self.num_workers} | 🎯 Beam: {self.beam_size}")

            try:
                self.faster_whisper_model = self._create_model(
                    self._resolve_model_path(model_size) if specialized else model_size)
            except Exception as e:
                if not specialized:
                    raise
                # Il modello specializzato non deve MAI far fallire il file:
                # si ripiega sul modello generico configurato.
                self.log(tr('fw_model_cannot_be_loaded_using').format(model_size=model_size, e=e, default_model=default_model))
                logger.warning(f"Modello per lingua '{model_size}' fallito: {e}", exc_info=True)
                self._failed_models.add(model_size)
                self.faster_whisper_model = None
                import gc; gc.collect()
                model_size = default_model
                self.faster_whisper_model = self._create_model(model_size)
            self.loaded_model = model_size
            where = "CUDA" if self.device == "cuda" else "CPU"
            self.log(tr('fw_model_loaded_on_with_workers').format(model_size=model_size, where=where, num_workers=self.num_workers))

            # VAD check sul WhisperModel puro (prima del wrapping)
            self._check_vad_availability()

            # Future-ready: attiva BatchedInferencePipeline se disponibile
            if _batched_available:
                self.faster_whisper_model = BatchedInferencePipeline(self.faster_whisper_model)
                self.batch_size_for_transcription = self.batch_manager.current_batch_size
                self.log(tr('fw_batchedinferencepipeline_active_batch_size').format(batch_size_for_transcription=self.batch_size_for_transcription))
            else:
                self.batch_size_for_transcription = None
                self.log(tr('fw_batchedinferencepipeline_not_available_sequential_processing'))

        except Exception as e:
            error_msg = tr('fw_error_loading_faster_whisper_model').format(e=e)
            self.log(error_msg)
            logger.error(error_msg, exc_info=True)
            raise

    def _create_model(self, model_path: str):
        """WhisperModel con i parametri storici (int8_float16 su CUDA, int8 su CPU)."""
        from faster_whisper import WhisperModel
        if self.device == "cuda":
            # int8_float16: pesi INT8 (~1.5GB vs ~3GB float16), compute FP16.
            # Più robusto dopo Demucs (VRAM frammentata) — qualità identica.
            import gc
            gc.collect()
            return WhisperModel(
                model_path,
                device="cuda",
                device_index=0,
                compute_type="int8_float16",
                num_workers=self.num_workers,
                cpu_threads=self.num_workers,
                download_root=HF_HUB_CACHE_DIR,
            )
        return WhisperModel(
            model_path,
            device="cpu",
            compute_type="int8",
            num_workers=self.num_workers,
            cpu_threads=self.num_workers,
            download_root=HF_HUB_CACHE_DIR,
        )

    def unload(self):
        """Pulizia risorse GPU (identica a cleanup() v3.5)"""
        try:
            if self.faster_whisper_model:
                del self.faster_whisper_model
                self.faster_whisper_model = None
            self.loaded_model = None
            import gc; gc.collect()
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()

            logger.info("✅ FasterWhisperEngine unload completato")
        except Exception as e:
            logger.error(f"Errore durante unload: {e}")

    def _vote_language(self, audio_chunks: List[tuple]) -> Optional[str]:
        """Lingua del file votata su chunk sparsi con detect_language di Whisper; None se inconcludente."""
        from core import lang_vote as LV
        try:
            import numpy as np
            import soundfile as sf
            from core import qwen3_lang_retry as LR
            # BatchedInferencePipeline.model è il WhisperModel (ha a sua volta .model = ct2); un
            # WhisperModel puro ha .model = ct2 (detect_language diverso, vuole features): niente salto.
            inner = getattr(self.faster_whisper_model, 'model', None)
            m = inner if inner is not None and hasattr(inner, 'model') else self.faster_whisper_model
            if not hasattr(m, 'detect_language'):
                return None
            paths = [str(c[0]) for c in audio_chunks]
            samples = []
            for idx in LV.select_probe_chunks(paths, voice_s_fn=lambda p: LR.voice_stats(p)['voice_s']):
                try:
                    x, sr = sf.read(paths[idx], dtype='float32', always_2d=True)
                    x = x.mean(axis=1)[:sr * 30]
                    if sr != 16000 and len(x):
                        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * 16000 / sr)),
                                      np.arange(len(x)), x).astype('float32')
                    lang, prob = m.detect_language(audio=x)[:2]
                    logger.info(f"[whisper-lid] chunk {idx + 1}: '{lang}' p={prob:.2f}")
                    samples.append((lang, float(prob)))
                except Exception as e:
                    logger.debug(f"[whisper-lid] chunk {idx + 1}: sonda fallita: {e}")
            iso, share = LV.vote(samples)
            logger.info(f"[whisper-lid] voto: {iso} (quota {share:.2f}) su {len(samples)} sonde")
            return iso
        except Exception as e:
            logger.warning(f"[whisper-lid] voto lingua non disponibile: {e}")
            return None

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
            self.log(tr('fw_vad_voice_activity_detection_available'))
            logger.info("VAD test successful - enabled")

        except Exception as e:
            self.vad_available = False
            self.log(tr('fw_vad_not_available_using_standard'))
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

        # Modello specializzato per la lingua (whisper_model_by_language): se in
        # VRAM c'e' un modello diverso (pre-load senza lingua, fallback da un
        # altro engine, lingua corretta a valle) si ricarica quello giusto.
        want = self._target_model(language)
        if self.faster_whisper_model is not None and self.loaded_model not in (None, want):
            self.log(tr('fw_switching_whisper_model_for_language').format(language=language, loaded_model=self.loaded_model, want=want))
            self.unload()
        self.language_hint = language
        if self.faster_whisper_model is None:
            self.load()
        # Modello effettivamente in uso (letto dalla GUI: tessera "Modello"); vale l'ultima
        # riga ricevuta, quindi corregge quella anticipata dalla pianificazione della pipeline
        # (ripiego da Qwen3/Canary, lingua rilevata dopo, modello specializzato caduto su large-v3).
        try:
            from utils.engine_labels import whisper_label
            self.log(tr('pl_transcription_model').format(model=whisper_label(self.loaded_model)))
        except Exception:
            pass

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
            self.log(tr('fw_batchedinferencepipeline_single_file_s_batch').format(total_duration=total_duration, bs=bs))
            self.log(tr('fw_profile_beam').format(profile_name=self.profile_name, beam_size=self.beam_size))
            if auto_detect:
                self.log(tr('fw_language_auto_detect'))
            else:
                self.log(tr('fw_language').format(whisper_language=whisper_language))

            # BatchedInferencePipeline richiede vad_filter=True obbligatoriamente
            # word_timestamps=True per splitting preciso dei segmenti lunghi
            transcribe_kwargs = dict(
                language=whisper_language,
                beam_size=self.beam_size,
                batch_size=bs,
                word_timestamps=True,
            )
            try:
                t0_transcribe = time.time()
                segments, info = self.faster_whisper_model.transcribe(
                    str(chunk_path),
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500, threshold=0.5),
                    **transcribe_kwargs
                )

                detected_language = info.language if hasattr(info, 'language') else None
                if detected_language and auto_detect:
                    self.log(tr('fw_language_detected_automatically').format(detected_language=detected_language))

                # `segments` e' un generatore pigro: e' QUI che avviene la trascrizione. Si consuma con barra
                # ed ETA reali (prima `list()` la nascondeva e la barra saltava da 0 a 99% in un istante).
                _seg_list = []
                _live_pct = -1
                _live_eta = EtaEstimator()
                for _seg in segments:
                    if self._cancelled:
                        break
                    _seg_list.append(_seg)
                    if total_duration > 0:
                        _f = min(_seg.end / total_duration, 0.99)
                        _txt = _live_eta.update(_f)
                        if int(_f * 100) != _live_pct:
                            _live_pct = int(_f * 100)
                            _bar = '█' * (_live_pct // 10) + '░' * (10 - _live_pct // 10)
                            from utils.events import emit as _tp_emit
                            _tp_emit('bar', phase='asr', pct=_live_pct, eta_s=_live_eta.eta_seconds())
                            self.log(tr('fw_transcription').format(bar=_bar, live_pct=_live_pct, txt=_txt))
                segments = _seg_list
                # v1.30.0 (core/whisper_lang_retry.py, trovato su X Factor): SOLO con lingua forzata (mai in
                # auto-detect, che sceglie già liberamente) i segmenti/vuoti sospetti vengono ritrascritti con
                # rilevamento lingua e sostituiti solo se la lingua rilevata è accettata (default solo 'en').
                if (not auto_detect and not self._cancelled
                        and self.config.get('whisper_lang_retry_enabled', True)):
                    try:
                        import soundfile as sf
                        x, sr_wav = sf.read(str(chunk_path), dtype='float32', always_2d=True)
                        x = x.mean(axis=1)
                        from core.whisper_lang_retry import apply as lang_retry_apply
                        accept = frozenset(self.config.get('whisper_lang_retry_accept_langs', ['en']))
                        segments = lang_retry_apply(
                            self.faster_whisper_model.transcribe, segments, x, sr_wav, whisper_language,
                            accept, self.beam_size, log=self.log)
                    except Exception as e:
                        logger.warning(f"[whisper-lang-retry] disattivato per questo file: {e}", exc_info=True)

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

                elapsed = time.time() - t0_transcribe
                mins, secs = divmod(int(elapsed), 60)
                time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
                from utils.events import emit as _tp_emit
                _tp_emit('bar', phase='asr', pct=100)
                self.log(tr('fw_transcription_100').format(time_str=time_str))

                # Suddividi segmenti lunghi usando i word timestamps
                raw_count = len(all_segments)
                # lingua del file: serve allo split per frasi (misurato solo sull'inglese)
                self._split_lang = detected_language or whisper_language
                split_segments = []
                for seg in all_segments:
                    split_segments.extend(self._split_segment_by_words(seg))
                all_segments = split_segments
                self.log(tr('fw_splitting_segments').format(raw_count=raw_count, n=len(all_segments)))
                self._last_segments = all_segments   # esposto per diarization in pipeline

            except Exception as e:
                logger.error(f"❌ Errore BatchedInferencePipeline: {e}", exc_info=True)
                self.log(tr('fw_transcription_error').format(error=str(e)))

        else:
            # ── Modalità classica: N chunk sequenziali ──
            failed_chunks = 0
            last_progress_pct = -1
            eta = EtaEstimator()
            t0_transcribe = time.time()

            self.log(tr('fw_transcribing_audio_chunks').format(total_chunks=total_chunks))
            self.log(tr('fw_profile_beam_workers').format(profile_name=self.profile_name, beam_size=self.beam_size, num_workers=self.num_workers))
            if auto_detect:
                self.log(tr('fw_language_auto_detect_automatic_detection'))
            else:
                self.log(tr('fw_language').format(whisper_language=whisper_language))

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

            # v1.30.1 (core/whisper_lang_retry.py): stessa correzione del percorso file-unico, applicata
            # PEZZO PER PEZZO (questo percorso riceve chunk già tagliati da un altro motore, es. il fallback
            # dopo un errore di Qwen3/Canary a metà file). Gate su tre condizioni: mai in auto-detect (lingua
            # già libera), serve il VAD (il ramo senza VAD sotto usa vad_filter=False, ma apply() ritenta
            # sempre con vad_filter=True), e la chiave di config. Log accorpato a fine ciclo, non per chunk
            # (su un film sarebbe una riga per ogni pezzo).
            lang_retry_on = (not auto_detect and self.vad_available
                            and self.config.get('whisper_lang_retry_enabled', True))
            lang_retry_accept = frozenset(self.config.get('whisper_lang_retry_accept_langs', ['en']))
            lang_retry_records: list = []

            # Auto-detect: UNA lingua per tutto il file, votata su più chunk sparsi (prima ogni chunk
            # decideva da solo e si loggava solo il primo: un intro di musica poteva dare 'nn').
            if auto_detect:
                voted = self._vote_language(audio_chunks)
                if voted:
                    whisper_language = voted
                    detected_language = voted
                    self.log(tr('fw_language_detected_automatically').format(detected_language=voted))

            def _retry_transcribe(*a, **k):
                # alcuni modelli (WhisperModel puro, senza BatchedInferencePipeline) non accettano
                # 'batch_size': fallback silenzioso, stesso risultato senza il parametro.
                try:
                    return self.faster_whisper_model.transcribe(*a, **k)
                except TypeError:
                    k.pop('batch_size', None)
                    return self.faster_whisper_model.transcribe(*a, **k)

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
                            self.log(tr('fw_language_detected_automatically').format(detected_language=detected_language))

                    segments = list(segments)
                    if lang_retry_on:
                        try:
                            import soundfile as sf
                            cx, csr = sf.read(str(chunk_path), dtype='float32', always_2d=True)
                            cx = cx.mean(axis=1)
                            from core.whisper_lang_retry import apply as lang_retry_apply
                            segments = lang_retry_apply(
                                _retry_transcribe, segments, cx, csr, whisper_language, lang_retry_accept,
                                self.beam_size, log=None, records=lang_retry_records)
                        except Exception as e:
                            logger.warning(f"[whisper-lang-retry] chunk {chunk_num} disattivato: {e}",
                                          exc_info=True)

                    for segment in segments:
                        all_segments.append({
                            'start': segment.start + start_time,
                            'end': segment.end + start_time,
                            'text': segment.text.strip()
                        })

                    pct = int((chunk_num / total_chunks) * 100)
                    eta_txt = eta.update(chunk_num / total_chunks)
                    if pct != last_progress_pct:
                        bars = int(pct / 10)
                        bar = '█' * bars + '░' * (10 - bars)
                        from utils.events import emit as _tp_emit
                        _tp_emit('bar', phase='asr', pct=pct, eta_s=eta.eta_seconds())
                        self.log(tr('fw_transcription_2').format(bar=bar, pct=pct, chunk_num=chunk_num, total_chunks=total_chunks, eta_txt=eta_txt))
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
                self.log(tr('fw_completed_with_failed_chunks_out').format(failed_chunks=failed_chunks, total_chunks=total_chunks))
            from utils.events import emit as _tp_emit
            _tp_emit('bar', phase='asr', pct=100)
            self.log(tr('fw_transcription_100_2').format(total_chunks=total_chunks, time_str=time_str))
            n_retried = sum(r.get('decision') == 'ritrascritto' for r in lang_retry_records)
            if lang_retry_records:
                self.log(tr('fw_suspicious_segments_empties_re_transcribed').format(n=len(lang_retry_records), n_retried=n_retried))
            self._last_segments = all_segments   # esposto per diarization in pipeline

        self.log(tr('fw_total_segments_transcribed').format(n=len(all_segments)))

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
        # codici a 3 lettere: 'ger'[:2] sarebbe 'ge' (tedesco mai attivo) -> mappa esplicita
        _ss3 = {'eng': 'en', 'ita': 'it', 'fre': 'fr', 'fra': 'fr', 'ger': 'de', 'deu': 'de', 'spa': 'es'}
        _ss_norm = lambda x: _ss3.get(str(x).strip().lower(), str(x).strip().lower()[:2])
        _ss_lang = _ss_norm(getattr(self, '_split_lang', '') or '')
        if self.config.get('whisper_split_sentence_aware', False) and _ss_lang:
            _ss_langs = self.config.get('whisper_split_sentence_langs', ['en'])
            if _ss_langs is None:
                _ss_langs = ['en']
            elif isinstance(_ss_langs, str):
                _ss_langs = [x for x in _ss_langs.replace(';', ',').replace(' ', ',').split(',') if x]
            elif not isinstance(_ss_langs, (list, tuple, set, frozenset)):
                _ss_langs = []
            _ss_on = _ss_lang in {_ss_norm(x) for x in (_ss_langs or ())}
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
