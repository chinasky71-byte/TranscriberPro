"""
Audio processing: vocal separation and chunking - PIPELINE INTELLIGENTE v3
File: core/audio_processor.py

PRIORITÀ:
1. QUALITÀ (massima accuratezza)
2. AFFIDABILITÀ (zero crash)
3. VELOCITÀ (ottimizzata)

PIPELINE INTELLIGENTE:
- File ≤ 5 min:   Processing diretto (veloce)
- File 5-60 min:  Split automatico (standard)
- File > 60 min:  Chunking manuale (robusto)

CHUNKS AUDIO:
- Target: 15-20 secondi
- Minimo: 10 secondi
- Massimo: 25 secondi (split forzato)
"""
import warnings
import torch
import torchaudio
warnings.filterwarnings('ignore', category=UserWarning, module='torchaudio')
import numpy as np
from pathlib import Path
import logging
import subprocess
import os
import time
import contextlib
from typing import List, Tuple, Optional, Callable

# NON logging.getLogger(__name__): il root logger non e' configurato in esecuzione normale e
# ogni logger.info() verrebbe scartato (v. utils/adaptive_batch_manager.py): le righe nascoste
# a schermo (Overlap, Merge, Chunking robusto...) non finirebbero nemmeno nel file di log.
from utils.logger import setup_logger
from utils.translations import tr

logger = setup_logger(__name__)

# Durata massima per chunk accettata dall'engine (v. piano_fix_
# pipeline_trascrizione punto B.5). Cappa i valori di config.
#   - qwen3: ForcedAligner MAX_FORCE_ALIGN_INPUT_SECONDS=180 (17% di margine)
# Canary (~35 s) e Whisper (~30 s) sono usciti con ADR-008: qui resta solo
# l'engine che esiste, e `min()` sul dizionario e' il ripiego prudente per chi
# non dichiara l'engine.
ENGINE_CHUNK_CAP_S = {
    'qwen3': 150.0,
}


class AudioProcessor:
    def __init__(self):
        self.logger = logger
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.demucs_model = None
        self.log_callback: Optional[Callable] = None
        self._cancelled: bool = False
        self._active_proc: Optional[subprocess.Popen] = None

        # Parametri chunk audio (v. piano_fix_pipeline_trascrizione punto B):
        # configurabili per permettere un A/B senza modificare codice. Default
        # = comportamento storico (20/10/25s). Cappati per engine in
        # process_for_transcription, non qui: qui sono i valori "richiesti".
        from utils.config import get_config
        _cfg = get_config()
        target = int(_cfg.get('asr_chunk_target_duration', 20))
        min_d  = int(_cfg.get('asr_chunk_min_duration', 10))
        max_d  = int(_cfg.get('asr_chunk_max_duration', 25))
        if not (0 < min_d < target <= max_d):
            self.logger.warning(
                f"Config chunk audio incoerente (min={min_d}, target={target}, "
                f"max={max_d}) — richiesto 0<min<target<=max: ricado sui default 10/20/25")
            target, min_d, max_d = 20, 10, 25
        self.CHUNK_TARGET_DURATION = target
        self.CHUNK_MIN_DURATION = min_d
        self.CHUNK_MAX_DURATION = max_d
        self.CHUNK_MIN_KEEP = 0.05       # Sotto 50ms il chunk non contiene parlato

        # Soglie pipeline intelligente
        self.FAST_PATH_THRESHOLD = 300    # 5 minuti
        self.STANDARD_PATH_THRESHOLD = 3600  # 60 minuti (era 90: lo standard path tiene in RAM 4 sorgenti, picco 23-25 GB)

        # Parametri Demucs chunking manuale
        self.DEMUCS_CHUNK_DURATION = 300  # 5 minuti per chunk Demucs
        self.DEMUCS_OVERLAP = 10          # 10 secondi overlap

    def cancel(self):
        """Segnala cancellazione e termina il sottoprocesso FFmpeg attivo."""
        self._cancelled = True
        if self._active_proc:
            try:
                self._active_proc.kill()
            except Exception:
                pass

    def set_log_callback(self, callback: Callable[[str], None]):
        """Imposta callback per logging verso GUI"""
        self.log_callback = callback
    
    def _log(self, message: str):
        """Log messaggio (console + GUI)"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def process_for_transcription(
        self,
        audio_path: Path,
        output_dir: Path,
        max_chunk_duration: int = 30,  # Deprecato, ora usa self.CHUNK_TARGET_DURATION
        min_chunk_duration: int = 5,   # Deprecato, ora usa self.CHUNK_MIN_DURATION
        use_batched_pipeline: bool = False,
        engine: Optional[str] = None
    ) -> List[Tuple[Path, float, float]]:
        """
        Processo completo audio per trascrizione con pipeline intelligente

        Args:
            audio_path: Path audio grezzo estratto dal video
            output_dir: Directory per file temporanei
            max_chunk_duration: DEPRECATO (usa self.CHUNK_TARGET_DURATION)
            min_chunk_duration: DEPRECATO (usa self.CHUNK_MIN_DURATION)
            use_batched_pipeline: Se True, salta il chunking e restituisce il file
                                   vocals intero (ottimizzato per BatchedInferencePipeline)
            engine: nome engine pianificato (oggi sempre 'qwen3', ADR-008).
                    Cappa la durata massima dei chunk richiesta in config
                    (v. ENGINE_CHUNK_CAP_S). None (nessun chiamante lo
                    specifica, es. subtitle_synchronizer) usa il cap PIÙ
                    prudente del dizionario invece di nessun cap — un
                    engine sconosciuto non deve tradursi in nessuna
                    protezione (bug-check Opus, v. piano_fix_pipeline_
                    trascrizione punto B).

        Returns:
            Lista di (chunk_path, start_time, end_time)
        """
        # Salvati per il ripristino a fine funzione (finally sotto): il cap
        # muta self.CHUNK_* per la durata di QUESTA chiamata soltanto —
        # senza ripristino, un'istanza AudioProcessor riusata fra due file
        # con engine diversi resterebbe cappata sul valore più basso visto
        # finora, in silenzio (bug-check Opus).
        _orig_target = self.CHUNK_TARGET_DURATION
        _orig_min = self.CHUNK_MIN_DURATION
        _orig_max = self.CHUNK_MAX_DURATION
        _capped = False

        if not use_batched_pipeline:
            if engine:
                cap = ENGINE_CHUNK_CAP_S.get(engine)
                if cap is None:
                    self.logger.debug(
                        f"Nessun cap chunk noto per engine '{engine}' — "
                        f"valori di config usati tali e quali")
            else:
                cap = min(ENGINE_CHUNK_CAP_S.values())
            if cap is not None and self.CHUNK_MAX_DURATION > cap:
                effective_max = cap
                effective_target = min(self.CHUNK_TARGET_DURATION, effective_max * 0.8)
                effective_min = min(self.CHUNK_MIN_DURATION, effective_target * 0.5)
                self._log(
                    tr('ap_chunk_max_s_over_the').format(CHUNK_MAX_DURATION=self.CHUNK_MAX_DURATION, engine_name=engine or tr('ap_unknown'), cap=cap, effective_max=effective_max, effective_target=effective_target, effective_min=effective_min))
                self.CHUNK_MAX_DURATION = effective_max
                self.CHUNK_TARGET_DURATION = effective_target
                self.CHUNK_MIN_DURATION = effective_min
                _capped = True
        try:
            self._log(f"🎬 Audio: {audio_path.name}")
            self._log(tr('ap_demucs_vocal_separation'))

            t0 = time.time()
            vocals_path = self.separate_vocals(audio_path)

            if not vocals_path or not vocals_path.exists():
                self._log(tr('ap_vocal_separation_failed_using_original'))
                vocals_path = audio_path
            else:
                elapsed = time.time() - t0
                mins, secs = divmod(int(elapsed), 60)
                time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
                self._log(tr('ap_vocals_separated_in').format(time_str=time_str, name=vocals_path.name))

            # BatchedInferencePipeline mode — salta chunking
            if use_batched_pipeline:
                self._log(tr('ap_batched_mode_chunking_skipped'))
                # torchaudio.info e' stato rimosso in torchaudio 2.9/2.10
                # (requirements-rocm.txt pinna 2.10.0+rocm7.0): usiamo
                # soundfile, gia' dipendenza del progetto, che legge i WAV
                # (qui vocals_path e' sempre un WAV).
                import soundfile as _sf
                _wav_info = _sf.info(str(vocals_path))
                total_duration = _wav_info.frames / _wav_info.samplerate
                self._log(tr('ap_audio_processing_completed_single_file').format(total_duration=total_duration))
                return [(vocals_path, 0.0, total_duration)]

            chunk_times = self.chunk_audio_intelligent(vocals_path)

            if not chunk_times:
                self.logger.error("Chunking fallito")
                return []

            chunk_files = self._create_physical_chunks(
                vocals_path,
                chunk_times,
                output_dir
            )

            elapsed_total = time.time() - t0
            mins, secs = divmod(int(elapsed_total), 60)
            time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
            self._log(tr('ap_audio_processing_completed_chunks_ready').format(n=len(chunk_files), time_str=time_str))
            return chunk_files

        except Exception as e:
            self.logger.error(f"Errore audio processing: {e}", exc_info=True)
            return []
        finally:
            if _capped:
                self.CHUNK_TARGET_DURATION = _orig_target
                self.CHUNK_MIN_DURATION = _orig_min
                self.CHUNK_MAX_DURATION = _orig_max

    def separate_vocals(self, audio_path: Path) -> Optional[Path]:
        """
        Separazione vocale con PIPELINE INTELLIGENTE basata su durata
        
        Pipeline:
        - File ≤ 5 min:   Processing diretto (veloce e sicuro)
        - File 5-60 min:  Split automatico Demucs (standard)
        - File > 60 min:  Chunking manuale 5min (robusto)
        """
        try:
            from demucs.pretrained import get_model
            from demucs.apply import apply_model
            
            # Carica modello se necessario
            if self.demucs_model is None:
                # Pulisci VRAM prima di caricare Demucs (run precedenti potrebbero
                # aver lasciato frammenti di altri modelli, es. pyannote)
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                self._log(tr('ap_loading_demucs_htdemucs_model'))
                self.demucs_model = get_model('htdemucs')
                self.demucs_model.to(self.device)
                self.demucs_model.eval()
                self._log(tr('ap_model_loaded_on').format(device=self.device))
            
            # Carica audio e calcola durata
            self._log(tr('ap_loading_audio'))
            wav, sr = torchaudio.load(str(audio_path))
            
            duration_seconds = wav.shape[1] / sr
            duration_minutes = duration_seconds / 60
            self._log(tr('ap_duration_minutes_s').format(duration_minutes=duration_minutes, duration_seconds=duration_seconds))
            
            # SELEZIONE PIPELINE INTELLIGENTE
            if duration_seconds <= self.FAST_PATH_THRESHOLD:
                # FAST PATH: File brevi (≤5 min)
                self._log(tr('ap_pipeline_fast_path_short_file'))
                vocals = self._separate_fast_path(wav, sr)
                
            elif duration_seconds <= self.STANDARD_PATH_THRESHOLD:
                # STANDARD PATH: File medi (5-60 min)
                self._log(tr('ap_pipeline_standard_path_automatic_split'))
                vocals = self._separate_standard_path(wav, sr, duration_seconds)
                
            else:
                # ROBUST PATH: File lunghi (>60 min)
                self._log(tr('ap_pipeline_robust_path_manual_chunking'))
                vocals = self._separate_robust_path(wav, sr, duration_seconds)
            
            if vocals is None:
                self._log(tr('ap_vocal_separation_failed'))
                return None
            
            # Salva vocals processati
            output_path = self._save_vocals(vocals, audio_path)
            
            if output_path:
                self._log(tr('ap_separation_completed').format(name=output_path.name))
            
            return output_path
            
        except ImportError:
            self.logger.error("Demucs non installato! pip install demucs")
            self._log(tr('ap_demucs_not_installed'))
            return None
        except Exception as e:
            self.logger.error(f"Errore Demucs: {e}", exc_info=True)
            self._log(tr('ap_demucs_error').format(error=str(e)))
            return None
    
    def _separate_fast_path(self, wav: torch.Tensor, sr: int) -> Optional[torch.Tensor]:
        """
        FAST PATH: Processing diretto per file brevi (≤5 min)
        Ottimizzato per velocità mantenendo qualità
        """
        try:
            from demucs.apply import apply_model
            
            self._log(tr('ap_direct_processing'))
            
            # Prepare audio
            wav = self._prepare_audio_for_demucs(wav, sr)
            
            # Separazione
            with torch.no_grad():
                sources = apply_model(
                    self.demucs_model,
                    wav.unsqueeze(0),
                    device=self.device
                )[0]
            
            vocals = sources[3].cpu()
            self._log(tr('ap_fast_path_completed'))
            
            # Cleanup
            del sources
            self._cleanup_gpu_memory()
            
            return vocals
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                self._log(tr('ap_oom_on_fast_path_fallback'))
                self._cleanup_gpu_memory()
                # Retry con standard path
                duration = wav.shape[1] / sr
                return self._separate_standard_path(wav.cpu(), sr, duration)
            else:
                raise
    
    def _separate_standard_path(self, wav: torch.Tensor, sr: int, duration: float) -> Optional[torch.Tensor]:
        """
        STANDARD PATH: Split automatico Demucs per file medi (5-60 min)
        Usa il sistema di split integrato di Demucs

        MEMORIA: input e output restano su CPU (keep_on_cpu=True) — con
        device diverso da mix.device, apply_model sposta su GPU solo il
        segmento (~8s) in lavorazione e accumula il risultato su CPU.
        Il picco VRAM è così indipendente dalla durata del file (misurato:
        prima 21,8 GB GPU committed su 83 min, con l'intero wav su GPU).
        """
        try:
            from demucs.apply import apply_model

            self._log(tr('ap_processing_with_automatic_split'))

            # Prepare audio (residente su CPU: la GPU vede solo i segmenti)
            wav = self._prepare_audio_for_demucs(wav, sr, keep_on_cpu=True)

            # Separazione con split automatico (barra reale: v. `_demucs_progress`)
            with torch.no_grad(), self._demucs_progress():
                sources = apply_model(
                    self.demucs_model,
                    wav.unsqueeze(0),
                    device=self.device,
                    split=True,        # ✅ Split automatico
                    overlap=0.25,      # 25% overlap per continuità
                    progress=True      # itera i segmenti con tqdm: lo sostituiamo con la nostra barra
                )[0]

            # clone(): stacca i vocals dallo storage a 4 sorgenti (~7 GB su
            # 83 min) così del sources libera davvero la RAM
            vocals = sources[3].clone()
            self._log(tr('ap_standard_path_completed'))

            # Cleanup
            del sources
            self._cleanup_gpu_memory()

            return vocals
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                self._log(tr('ap_oom_on_standard_path_fallback'))
                self._cleanup_gpu_memory()
                # Retry con robust path
                return self._separate_robust_path(wav.cpu(), sr, duration)
            else:
                raise
    
    @contextlib.contextmanager
    def _demucs_progress(self):
        """Barra reale (percentuale + ETA) per il percorso standard di Demucs.

        `apply_model(progress=True)` itera i segmenti con `tqdm.tqdm(...)` (modulo `demucs.apply`); solo durante la
        chiamata quel `tqdm` e' sostituito da un iteratore che riporta l'avanzamento come la barra del percorso a
        chunk (evento `bar demucs` con `eta_s` + riga di log). Nessuna stima: ogni passo e' un segmento finito."""
        import demucs.apply as _da
        from utils.eta import EtaEstimator
        from utils.events import emit as _tp_emit
        eta = EtaEstimator()
        last = [-1]
        log = self._log

        def _report(k, n):
            pct = int(k * 100 / max(n, 1))
            if pct == last[0]:
                return
            last[0] = pct
            txt = eta.update(k / max(n, 1))
            bars = pct // 10
            _tp_emit('bar', phase='demucs', pct=pct, eta_s=eta.eta_seconds())
            log(f"    📦 Demucs: [{'█' * bars}{'░' * (10 - bars)}] {pct:3d}%{txt}")

        class _Tqdm:
            @staticmethod
            def tqdm(iterable, *args, **kwargs):
                items = list(iterable)

                def gen():
                    for k, item in enumerate(items, 1):
                        if self._cancelled:
                            raise InterruptedError(tr('ap_demucs_cancelled'))
                        yield item
                        _report(k, len(items))      # eseguito quando il ciclo ha finito il segmento
                return gen()

        orig = getattr(_da, 'tqdm', None)
        import types
        if not isinstance(orig, types.ModuleType):
            yield                       # demucs diverso da quello atteso (`import tqdm`): nessuna barra, nessun patch
            return
        _tp_emit('bar', phase='demucs', pct=0)
        log("    📦 Demucs: [░░░░░░░░░░]   0%")
        _da.tqdm = _Tqdm
        try:
            yield
        finally:
            _da.tqdm = orig

    def _separate_robust_path(self, wav: torch.Tensor, sr: int, duration: float) -> Optional[torch.Tensor]:
        """
        ROBUST PATH: Chunking manuale per file lunghi (>60 min)
        Massima affidabilità con chunks da 5 minuti e overlap 10s
        """
        try:
            from demucs.apply import apply_model
            
            chunk_samples = int(self.DEMUCS_CHUNK_DURATION * sr)
            overlap_samples = int(self.DEMUCS_OVERLAP * sr)
            
            num_chunks = int(np.ceil(duration / self.DEMUCS_CHUNK_DURATION))
            
            self._log(tr('ap_robust_chunking_chunks_of_min').format(num_chunks=num_chunks, minutes=self.DEMUCS_CHUNK_DURATION/60))
            self._log(tr('ap_overlap_s_for_seamless_continuity').format(DEMUCS_OVERLAP=self.DEMUCS_OVERLAP))
            
            vocal_chunks = []
            failed_chunks = 0
            chunk_start_time = time.time()
            from utils.eta import EtaEstimator
            _eta = EtaEstimator()      # ETA dal ritmo recente dei chunk (come trascrizione/traduzione)

            # Barra di progresso iniziale
            self._log(f"    📦 Demucs: [░░░░░░░░░░] 0/{num_chunks} (0%)")

            # Processa ogni chunk
            for i in range(num_chunks):
                if self._cancelled:
                    raise InterruptedError(tr('ap_demucs_cancelled'))
                chunk_num = i + 1

                # Calcola range con overlap
                start = max(0, i * chunk_samples - overlap_samples)
                end = min(wav.shape[1], (i + 1) * chunk_samples + overlap_samples)

                chunk_wav = wav[:, start:end].clone()

                try:
                    # Prepare chunk (residente su CPU — vedi standard path)
                    chunk_wav = self._prepare_audio_for_demucs(chunk_wav, sr, keep_on_cpu=True)

                    # Separazione chunk: split=True come lo standard path —
                    # la GPU lavora un segmento (~8s) per volta anche qui
                    with torch.no_grad():
                        sources = apply_model(
                            self.demucs_model,
                            chunk_wav.unsqueeze(0),
                            device=self.device,
                            split=True,
                            overlap=0.25
                        )[0]

                    # clone(): stacca dallo storage a 4 sorgenti (libera RAM)
                    chunk_vocals = sources[3].clone()

                    # Rimuovi overlap (tranne primo e ultimo)
                    if i > 0:
                        overlap_demucs = int(overlap_samples * self.demucs_model.samplerate / sr)
                        chunk_vocals = chunk_vocals[:, overlap_demucs:]

                    if i < num_chunks - 1:
                        overlap_demucs = int(overlap_samples * self.demucs_model.samplerate / sr)
                        chunk_vocals = chunk_vocals[:, :-overlap_demucs]

                    vocal_chunks.append(chunk_vocals)

                    # Aggiorna barra progresso
                    bars = int((chunk_num / num_chunks) * 10)
                    pct = int((chunk_num / num_chunks) * 100)
                    bar = '█' * bars + '░' * (10 - bars)
                    from utils.events import emit as _tp_emit
                    _eta_txt = _eta.update(chunk_num / num_chunks)
                    _tp_emit('bar', phase='demucs', pct=pct, eta_s=_eta.eta_seconds())
                    self._log(f"    📦 Demucs: [{bar}] {chunk_num}/{num_chunks} ({pct}%){_eta_txt}")

                    # Cleanup immediato
                    del sources, chunk_wav
                    self._cleanup_gpu_memory()

                except RuntimeError as e:
                    if "out of memory" in str(e).lower():
                        self._log(tr('ap_oom_chunk_fallback_to_original').format(chunk_num=chunk_num))
                        failed_chunks += 1

                        # Fallback: audio originale per questo chunk
                        chunk_start = i * chunk_samples
                        chunk_end = min(wav.shape[1], (i + 1) * chunk_samples)
                        fallback_chunk = wav[:, chunk_start:chunk_end].clone()

                        # Resample se necessario
                        if sr != self.demucs_model.samplerate:
                            resampler = torchaudio.transforms.Resample(sr, self.demucs_model.samplerate)
                            fallback_chunk = resampler(fallback_chunk)

                        vocal_chunks.append(fallback_chunk)
                        self._cleanup_gpu_memory()

                        # Aggiorna barra progresso anche dopo OOM
                        bars = int((chunk_num / num_chunks) * 10)
                        pct = int((chunk_num / num_chunks) * 100)
                        bar = '█' * bars + '░' * (10 - bars)
                        from utils.events import emit as _tp_emit
                        _eta_txt = _eta.update(chunk_num / num_chunks)
                        _tp_emit('bar', phase='demucs', pct=pct, eta_s=_eta.eta_seconds())
                        self._log(f"    📦 Demucs: [{bar}] {chunk_num}/{num_chunks} ({pct}%){_eta_txt}")
                    else:
                        raise

            # Riga finale con elapsed time
            elapsed = time.time() - chunk_start_time
            mins, secs = divmod(int(elapsed), 60)
            time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
            self._log(tr('ap_demucs_completed_chunks_in').format(num_chunks=num_chunks, time_str=time_str))

            # Merge chunks
            self._log("    🔗 Merge chunks...")
            vocals_full = torch.cat(vocal_chunks, dim=1)
            
            if failed_chunks > 0:
                self._log(tr('ap_chunks_use_original_audio').format(failed_chunks=failed_chunks, num_chunks=num_chunks))
            
            return vocals_full
            
        except Exception as e:
            self.logger.error(f"Errore robust path: {e}", exc_info=True)
            self._log(tr('ap_robust_path_failed').format(error=str(e)))
            return None
    
    def _prepare_audio_for_demucs(self, wav: torch.Tensor, sr: int,
                                  keep_on_cpu: bool = False) -> torch.Tensor:
        """
        Prepara audio per Demucs (resample + stereo + device)

        keep_on_cpu=True: il tensore NON viene spostato su GPU — apply_model
        (chiamato con device='cuda' su input CPU) trasferisce da solo i
        segmenti in lavorazione e tiene il resto in RAM. Usato da standard
        e robust path per avere un picco VRAM indipendente dalla durata.
        """
        # Resample se necessario
        if sr != self.demucs_model.samplerate:
            resampler = torchaudio.transforms.Resample(sr, self.demucs_model.samplerate)
            if self.device == 'cuda' and not keep_on_cpu:
                resampler = resampler.to(self.device)
                wav = wav.to(self.device)
            wav = resampler(wav)
        else:
            if self.device == 'cuda' and not keep_on_cpu:
                wav = wav.to(self.device)

        # Ensure stereo
        if wav.shape[0] == 1:
            wav = wav.repeat(2, 1)

        return wav
    
    def _save_vocals(self, vocals: torch.Tensor, audio_path: Path) -> Optional[Path]:
        """Converte vocals in mono 16kHz e salva"""
        try:
            self._log(tr('ap_converting_to_mono_16khz'))
            
            # Convert to mono
            vocals_mono = torch.mean(vocals, dim=0, keepdim=True)
            
            # Resample to 16kHz for Whisper
            current_sr = self.demucs_model.samplerate
            resampler = torchaudio.transforms.Resample(current_sr, 16000)
            vocals_16k = resampler(vocals_mono)
            
            # Save
            output_path = audio_path.parent / f"{audio_path.stem}_vocals.wav"
            torchaudio.save(str(output_path), vocals_16k, 16000)
            
            file_size_mb = output_path.stat().st_size / (1024 * 1024)
            self._log(tr('ap_vocals_saved_mb').format(name=output_path.name, file_size_mb=file_size_mb))
            
            # Cleanup finale
            self._cleanup_gpu_memory()
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Errore salvataggio vocals: {e}")
            self._log(tr('ap_save_error').format(error=str(e)))
            return None
    
    def chunk_audio_intelligent(self, audio_path: Path) -> List[Tuple[float, float]]:
        """
        Chunking INTELLIGENTE con target 15-20 secondi
        
        Strategia per QUALITÀ MASSIMA:
        1. Rilevamento silenzio aggressivo (threshold -35dB)
        2. Target chunks 20 secondi
        3. Range accettabile: 10-25 secondi
        4. Split forzato se >25 secondi (evita allucinazioni Whisper)
        5. Merge se <10 secondi (evita troppa frammentazione)
        
        Returns:
            Lista di (start_time, end_time) in secondi
        """
        try:
            import librosa
            
            self._log(tr('ap_audio_analysis').format(name=audio_path.name))
            
            # Carica audio
            y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
            total_duration = len(y) / sr
            
            self._log(tr('ap_total_duration_s_min').format(total_duration=total_duration, minutes=total_duration/60))
            
            # Parametri ottimizzati per QUALITÀ
            silence_threshold_db = -35  # Più sensibile (era -40)
            min_silence_duration_ms = 300  # 300ms silenzio minimo
            
            # Rileva intervalli non-silenziosi con parametri aggressivi
            non_silent_intervals = librosa.effects.split(
                y,
                top_db=-silence_threshold_db,
                frame_length=2048,
                hop_length=512
            )
            
            self._log(tr('ap_found_audio_intervals').format(n=len(non_silent_intervals)))
            
            # Costruisci chunks intelligenti
            chunks = []
            current_chunk_start = 0.0
            current_chunk_end = 0.0
            
            for interval_start, interval_end in non_silent_intervals:
                interval_start_sec = interval_start / sr
                interval_end_sec = interval_end / sr
                interval_duration = interval_end_sec - interval_start_sec
                
                # Se primo intervallo
                if current_chunk_end == 0.0:
                    current_chunk_start = interval_start_sec
                    current_chunk_end = interval_end_sec
                    continue
                
                # Calcola durata se aggiungiamo questo intervallo
                potential_duration = interval_end_sec - current_chunk_start
                
                # DECISIONE: Aggiungi o chiudi chunk?
                if potential_duration <= self.CHUNK_MAX_DURATION:
                    # Possiamo aggiungere: estendi chunk
                    current_chunk_end = interval_end_sec
                else:
                    # Troppo lungo: chiudi chunk corrente
                    current_duration = current_chunk_end - current_chunk_start
                    
                    if current_duration >= self.CHUNK_MIN_DURATION:
                        # Chunk valido: aggiungi
                        chunks.append((current_chunk_start, current_chunk_end))
                    else:
                        # Chunk troppo corto: forza estensione fino a minimo,
                        # MAI oltre l'inizio del prossimo intervallo — altrimenti
                        # il chunk successivo (che parte da interval_start_sec)
                        # si sovrappone fisicamente a questo. Bug storico: audio
                        # duplicato tra due chunk → stessa battuta trascritta
                        # due volte con timestamp leggermente diversi.
                        if current_chunk_end + 5 <= interval_end_sec:
                            current_chunk_end = min(
                                current_chunk_start + self.CHUNK_MIN_DURATION,
                                interval_start_sec
                            )
                        chunks.append((current_chunk_start, current_chunk_end))
                    
                    # Inizia nuovo chunk
                    current_chunk_start = interval_start_sec
                    current_chunk_end = interval_end_sec
            
            # Gestisci ultimo chunk
            if current_chunk_end > 0:
                current_duration = current_chunk_end - current_chunk_start
                
                if current_duration >= self.CHUNK_MIN_DURATION:
                    chunks.append((current_chunk_start, current_chunk_end))
                elif chunks:
                    # Merge con ultimo chunk
                    last_start, _ = chunks[-1]
                    chunks[-1] = (last_start, current_chunk_end)
                else:
                    # File molto corto: usa tutto
                    chunks.append((0.0, total_duration))
            
            # POST-PROCESSING: Split forzato chunks troppo lunghi
            final_chunks = []
            split_count = 0
            
            for start, end in chunks:
                duration = end - start
                
                if duration > self.CHUNK_MAX_DURATION:
                    # Split forzato in chunk più piccoli
                    num_splits = int(np.ceil(duration / self.CHUNK_TARGET_DURATION))
                    split_duration = duration / num_splits
                    
                    for i in range(num_splits):
                        split_start = start + (i * split_duration)
                        split_end = start + ((i + 1) * split_duration)
                        final_chunks.append((split_start, split_end))
                        split_count += 1
                else:
                    final_chunks.append((start, end))
            
            # Rete di sicurezza: garantisce chunk[i].end <= chunk[i+1].start
            # per costruzione, qualunque euristica sopra li abbia generati.
            # Chunk fisicamente sovrapposti vengono trascritti due volte
            # dall'engine ASR (stessa battuta, timestamp leggermente diversi).
            # Il clamp può ridurre un chunk a durata nulla (overlap lungo
            # quanto il chunk stesso): va scartato qui, non passato a FFmpeg —
            # con -t <= 0 produce un WAV vuoto che l'engine ASR tenta comunque
            # di trascrivere.
            safe_chunks: List[Tuple[float, float]] = []
            overlap_fixed = 0
            degenerate = 0
            for i, (start_i, end_i) in enumerate(final_chunks):
                if i + 1 < len(final_chunks):
                    start_next = final_chunks[i + 1][0]
                    if end_i > start_next:
                        end_i = start_next
                        overlap_fixed += 1
                if end_i - start_i < self.CHUNK_MIN_KEEP:
                    degenerate += 1
                    continue
                safe_chunks.append((start_i, end_i))
            final_chunks = safe_chunks

            if overlap_fixed:
                self._log(tr('ap_physical_overlaps_between_chunks_fixed').format(overlap_fixed=overlap_fixed))
            if degenerate:
                self._log(tr('ap_zero_duration_chunks_discarded').format(degenerate=degenerate))

            if not final_chunks:
                self.logger.error("Chunking: nessun chunk valido dopo la normalizzazione")
                self._log(tr('ap_no_valid_chunk_produced'))
                return []

            # Statistiche (dopo la normalizzazione: riflettono i chunk reali)
            durations = [end - start for start, end in final_chunks]
            avg_duration = np.mean(durations)
            min_duration = np.min(durations)
            max_duration = np.max(durations)

            self._log(tr('ap_chunks_created').format(n=len(final_chunks)))
            self._log(tr('ap_average_duration_s_min_s').format(avg_duration=avg_duration, min_duration=min_duration, max_duration=max_duration))
            if split_count > 0:
                self._log(tr('ap_forced_splits_chunks').format(split_count=split_count))

            # Log dettagliato primi 5 e ultimi 5 chunks
            self.logger.debug("  Primi 5 chunks:")
            for idx, (start, end) in enumerate(final_chunks[:5]):
                self.logger.debug(f"    Chunk {idx+1}: {start:.1f}s → {end:.1f}s ({end-start:.1f}s)")
            
            if len(final_chunks) > 10:
                self.logger.debug("  ...")
                self.logger.debug("  Ultimi 5 chunks:")
                for idx, (start, end) in enumerate(final_chunks[-5:], len(final_chunks)-4):
                    self.logger.debug(f"    Chunk {idx}: {start:.1f}s → {end:.1f}s ({end-start:.1f}s)")
            
            return final_chunks
            
        except ImportError:
            self.logger.error("librosa non installato! pip install librosa")
            self._log(tr('ap_librosa_not_available'))
            return []
        except Exception as e:
            self.logger.error(f"Errore chunking: {e}", exc_info=True)
            self._log(tr('ap_chunking_error').format(error=str(e)))
            return []
    
    def _create_physical_chunks(
        self,
        audio_path: Path,
        chunk_times: List[Tuple[float, float]],
        output_dir: Path
    ) -> List[Tuple[Path, float, float]]:
        """
        Crea file WAV fisici per ogni chunk
        
        Args:
            audio_path: Path audio sorgente
            chunk_times: Lista (start, end) in secondi
            output_dir: Directory output
            
        Returns:
            Lista di (chunk_path, start_time, end_time)
        """
        chunk_files = []
        failed = 0
        
        for idx, (start_time, end_time) in enumerate(chunk_times):
            chunk_num = idx + 1
            duration = end_time - start_time

            # Durata non valida: FFmpeg con -t <= 0 scriverebbe un WAV vuoto
            # (rc 0) che l'engine ASR tenterebbe comunque di trascrivere
            if duration <= 0:
                self.logger.warning(
                    f"    ⚠️ Chunk {chunk_num} saltato: durata non valida ({duration:.3f}s)")
                failed += 1
                continue

            # Nome file chunk
            chunk_filename = f"chunk_{chunk_num:04d}.wav"
            chunk_path = output_dir / chunk_filename
            
            try:
                if self._cancelled:
                    raise InterruptedError(tr('ap_operation_cancelled'))

                # Estrai chunk con FFmpeg
                cmd = [
                    'ffmpeg',
                    '-y',
                    '-ss', str(start_time),
                    '-t', str(duration),
                    '-i', str(audio_path),
                    '-acodec', 'copy',
                    '-loglevel', 'error',
                    str(chunk_path)
                ]

                self._active_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                _stdout, _stderr = self._active_proc.communicate()
                _rc = self._active_proc.returncode
                self._active_proc = None
                if self._cancelled:
                    raise InterruptedError(tr('ap_operation_cancelled'))

                if _rc == 0 and chunk_path.exists():
                    chunk_files.append((chunk_path, start_time, end_time))
                else:
                    self.logger.error(f"    ❌ Chunk {chunk_num} fallito: {_stderr}")
                    failed += 1

            except InterruptedError:
                raise
            except Exception as e:
                self.logger.error(f"    ❌ Errore chunk {chunk_num}: {e}")
                failed += 1
        
        success_rate = (len(chunk_files) / len(chunk_times)) * 100
        self._log(tr('ap_chunks_created_2').format(n=len(chunk_files), n_2=len(chunk_times), success_rate=success_rate))
        
        if failed > 0:
            self._log(tr('ap_failed_chunks').format(failed=failed))
        
        return chunk_files
    
    def _cleanup_gpu_memory(self):
        """Pulizia aggressiva memoria GPU"""
        if self.device == 'cuda':
            import gc
            torch.cuda.synchronize()
            gc.collect()
            torch.cuda.empty_cache()
    
    def cleanup_model(self):
        """Scarica modello Demucs dalla memoria"""
        if self.demucs_model:
            del self.demucs_model
            self.demucs_model = None
            import gc; gc.collect()
            self._cleanup_gpu_memory()
            self.logger.info("🗑️ Modello Demucs scaricato dalla memoria")
