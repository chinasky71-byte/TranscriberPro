"""
Audio processing: vocal separation and chunking - PIPELINE INTELLIGENTE v3
File: core/audio_processor.py

PRIORITÀ:
1. QUALITÀ (massima accuratezza)
2. AFFIDABILITÀ (zero crash)
3. VELOCITÀ (ottimizzata)

PIPELINE INTELLIGENTE:
- File ≤ 5 min:   Processing diretto (veloce)
- File 5-90 min:  Split automatico (standard)
- File > 90 min:  Chunking manuale (robusto)

CHUNKS AUDIO:
- Target: 15-20 secondi
- Minimo: 10 secondi
- Massimo: 25 secondi (split forzato)
"""
import torch
import torchaudio
import numpy as np
from pathlib import Path
import logging
import subprocess
import os
import time
from typing import List, Tuple, Optional, Callable

logger = logging.getLogger(__name__)


class AudioProcessor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.demucs_model = None
        self.log_callback: Optional[Callable] = None
        
        # Parametri ottimizzati per qualità
        self.CHUNK_TARGET_DURATION = 20  # Target 20 secondi
        self.CHUNK_MIN_DURATION = 10     # Minimo 10 secondi
        self.CHUNK_MAX_DURATION = 25     # Massimo 25 secondi (split forzato)
        
        # Soglie pipeline intelligente
        self.FAST_PATH_THRESHOLD = 300    # 5 minuti
        self.STANDARD_PATH_THRESHOLD = 5400  # 90 minuti
        
        # Parametri Demucs chunking manuale
        self.DEMUCS_CHUNK_DURATION = 300  # 5 minuti per chunk Demucs
        self.DEMUCS_OVERLAP = 10          # 10 secondi overlap
        
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
        use_batched_pipeline: bool = False
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

        Returns:
            Lista di (chunk_path, start_time, end_time)
        """
        try:
            self._log(f"🎬 Audio: {audio_path.name}")
            self._log("  🎵 Separazione vocale Demucs...")

            t0 = time.time()
            vocals_path = self.separate_vocals(audio_path)

            if not vocals_path or not vocals_path.exists():
                self._log("  ⚠️ Separazione vocale fallita - Uso audio originale")
                vocals_path = audio_path
            else:
                elapsed = time.time() - t0
                mins, secs = divmod(int(elapsed), 60)
                time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
                self._log(f"  ✅ Vocals separati in {time_str}: {vocals_path.name}")

            # BatchedInferencePipeline mode — salta chunking
            if use_batched_pipeline:
                self._log("  ⚡ Batched mode — chunking saltato")
                wav_info = torchaudio.info(str(vocals_path))
                total_duration = wav_info.num_frames / wav_info.sample_rate
                self._log(f"✅ Audio processing completato: file unico ({total_duration:.1f}s)")
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
            self._log(f"✅ Audio processing completato: {len(chunk_files)} chunks pronti in {time_str}")
            return chunk_files

        except Exception as e:
            self.logger.error(f"Errore audio processing: {e}", exc_info=True)
            return []
    
    def separate_vocals(self, audio_path: Path) -> Optional[Path]:
        """
        Separazione vocale con PIPELINE INTELLIGENTE basata su durata
        
        Pipeline:
        - File ≤ 5 min:   Processing diretto (veloce e sicuro)
        - File 5-90 min:  Split automatico Demucs (standard)
        - File > 90 min:  Chunking manuale 5min (robusto)
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
                self._log("  📦 Caricamento modello Demucs htdemucs...")
                self.demucs_model = get_model('htdemucs')
                self.demucs_model.to(self.device)
                self.demucs_model.eval()
                self._log(f"  ✅ Modello caricato su {self.device}")
            
            # Carica audio e calcola durata
            self._log("  📂 Caricamento audio...")
            wav, sr = torchaudio.load(str(audio_path))
            
            duration_seconds = wav.shape[1] / sr
            duration_minutes = duration_seconds / 60
            self._log(f"  ⏱️ Durata: {duration_minutes:.1f} minuti ({duration_seconds:.0f}s)")
            
            # SELEZIONE PIPELINE INTELLIGENTE
            if duration_seconds <= self.FAST_PATH_THRESHOLD:
                # FAST PATH: File brevi (≤5 min)
                self._log(f"  🚀 Pipeline: FAST PATH (file breve)")
                vocals = self._separate_fast_path(wav, sr)
                
            elif duration_seconds <= self.STANDARD_PATH_THRESHOLD:
                # STANDARD PATH: File medi (5-90 min)
                self._log(f"  ⚙️ Pipeline: STANDARD PATH (split automatico)")
                vocals = self._separate_standard_path(wav, sr, duration_seconds)
                
            else:
                # ROBUST PATH: File lunghi (>90 min)
                self._log(f"  🛡️ Pipeline: ROBUST PATH (chunking manuale)")
                vocals = self._separate_robust_path(wav, sr, duration_seconds)
            
            if vocals is None:
                self._log("  ❌ Separazione vocale fallita")
                return None
            
            # Salva vocals processati
            output_path = self._save_vocals(vocals, audio_path)
            
            if output_path:
                self._log(f"  ✅ Separazione completata: {output_path.name}")
            
            return output_path
            
        except ImportError:
            self.logger.error("Demucs non installato! pip install demucs")
            self._log("  ⚠️ Demucs non installato")
            return None
        except Exception as e:
            self.logger.error(f"Errore Demucs: {e}", exc_info=True)
            self._log(f"  ❌ Errore Demucs: {str(e)}")
            return None
    
    def _separate_fast_path(self, wav: torch.Tensor, sr: int) -> Optional[torch.Tensor]:
        """
        FAST PATH: Processing diretto per file brevi (≤5 min)
        Ottimizzato per velocità mantenendo qualità
        """
        try:
            from demucs.apply import apply_model
            
            self._log("    ⚡ Processing diretto...")
            
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
            self._log("    ✅ Fast path completato")
            
            # Cleanup
            del sources
            self._cleanup_gpu_memory()
            
            return vocals
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                self._log("    ⚠️ OOM su fast path - Fallback standard path")
                self._cleanup_gpu_memory()
                # Retry con standard path
                duration = wav.shape[1] / sr
                return self._separate_standard_path(wav.cpu(), sr, duration)
            else:
                raise
    
    def _separate_standard_path(self, wav: torch.Tensor, sr: int, duration: float) -> Optional[torch.Tensor]:
        """
        STANDARD PATH: Split automatico Demucs per file medi (5-90 min)
        Usa il sistema di split integrato di Demucs
        """
        try:
            from demucs.apply import apply_model
            
            self._log("    ⚙️ Processing con split automatico...")
            
            # Prepare audio
            wav = self._prepare_audio_for_demucs(wav, sr)
            
            # Separazione con split automatico
            with torch.no_grad():
                sources = apply_model(
                    self.demucs_model,
                    wav.unsqueeze(0),
                    device=self.device,
                    split=True,        # ✅ Split automatico
                    overlap=0.25       # 25% overlap per continuità
                )[0]
            
            vocals = sources[3].cpu()
            self._log("    ✅ Standard path completato")
            
            # Cleanup
            del sources
            self._cleanup_gpu_memory()
            
            return vocals
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                self._log("    ⚠️ OOM su standard path - Fallback robust path")
                self._cleanup_gpu_memory()
                # Retry con robust path
                return self._separate_robust_path(wav.cpu(), sr, duration)
            else:
                raise
    
    def _separate_robust_path(self, wav: torch.Tensor, sr: int, duration: float) -> Optional[torch.Tensor]:
        """
        ROBUST PATH: Chunking manuale per file lunghi (>90 min)
        Massima affidabilità con chunks da 5 minuti e overlap 10s
        """
        try:
            from demucs.apply import apply_model
            
            chunk_samples = int(self.DEMUCS_CHUNK_DURATION * sr)
            overlap_samples = int(self.DEMUCS_OVERLAP * sr)
            
            num_chunks = int(np.ceil(duration / self.DEMUCS_CHUNK_DURATION))
            
            self._log(f"    🛡️ Chunking robusto: {num_chunks} chunks da {self.DEMUCS_CHUNK_DURATION/60:.1f}min")
            self._log(f"    📏 Overlap: {self.DEMUCS_OVERLAP}s per continuità seamless")
            
            vocal_chunks = []
            failed_chunks = 0
            chunk_start_time = time.time()

            # Barra di progresso iniziale
            self._log(f"    📦 Demucs: [░░░░░░░░░░] 0/{num_chunks} (0%)")

            # Processa ogni chunk
            for i in range(num_chunks):
                chunk_num = i + 1

                # Calcola range con overlap
                start = max(0, i * chunk_samples - overlap_samples)
                end = min(wav.shape[1], (i + 1) * chunk_samples + overlap_samples)

                chunk_wav = wav[:, start:end].clone()

                try:
                    # Prepare chunk
                    chunk_wav = self._prepare_audio_for_demucs(chunk_wav, sr)

                    # Separazione chunk
                    with torch.no_grad():
                        sources = apply_model(
                            self.demucs_model,
                            chunk_wav.unsqueeze(0),
                            device=self.device
                        )[0]

                    chunk_vocals = sources[3].cpu()

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
                    self._log(f"    📦 Demucs: [{bar}] {chunk_num}/{num_chunks} ({pct}%)")

                    # Cleanup immediato
                    del sources, chunk_wav
                    self._cleanup_gpu_memory()

                except RuntimeError as e:
                    if "out of memory" in str(e).lower():
                        self._log(f"      ⚠️ OOM chunk {chunk_num} - Fallback audio originale")
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
                        self._log(f"    📦 Demucs: [{bar}] {chunk_num}/{num_chunks} ({pct}%)")
                    else:
                        raise

            # Riga finale con elapsed time
            elapsed = time.time() - chunk_start_time
            mins, secs = divmod(int(elapsed), 60)
            time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
            self._log(f"    ✅ Demucs completato: {num_chunks}/{num_chunks} chunks in {time_str}")

            # Merge chunks
            self._log("    🔗 Merge chunks...")
            vocals_full = torch.cat(vocal_chunks, dim=1)
            
            if failed_chunks > 0:
                self._log(f"    ⚠️ {failed_chunks}/{num_chunks} chunks usano audio originale")
            
            return vocals_full
            
        except Exception as e:
            self.logger.error(f"Errore robust path: {e}", exc_info=True)
            self._log(f"    ❌ Robust path fallito: {str(e)}")
            return None
    
    def _prepare_audio_for_demucs(self, wav: torch.Tensor, sr: int) -> torch.Tensor:
        """Prepara audio per Demucs (resample + stereo + device)"""
        # Resample se necessario
        if sr != self.demucs_model.samplerate:
            resampler = torchaudio.transforms.Resample(sr, self.demucs_model.samplerate)
            if self.device == 'cuda':
                resampler = resampler.to(self.device)
                wav = wav.to(self.device)
            wav = resampler(wav)
        else:
            if self.device == 'cuda':
                wav = wav.to(self.device)
        
        # Ensure stereo
        if wav.shape[0] == 1:
            wav = wav.repeat(2, 1)
        
        return wav
    
    def _save_vocals(self, vocals: torch.Tensor, audio_path: Path) -> Optional[Path]:
        """Converte vocals in mono 16kHz e salva"""
        try:
            self._log("    🔄 Conversione a mono 16kHz...")
            
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
            self._log(f"    💾 Vocals salvati: {output_path.name} ({file_size_mb:.1f}MB)")
            
            # Cleanup finale
            self._cleanup_gpu_memory()
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Errore salvataggio vocals: {e}")
            self._log(f"    ❌ Errore salvataggio: {str(e)}")
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
            
            self._log(f"  📊 Analisi audio: {audio_path.name}")
            
            # Carica audio
            y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
            total_duration = len(y) / sr
            
            self._log(f"  ⏱️ Durata totale: {total_duration:.1f}s ({total_duration/60:.1f}min)")
            
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
            
            self._log(f"  🔍 Trovati {len(non_silent_intervals)} intervalli audio")
            
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
                        # Chunk troppo corto: forza estensione fino a minimo
                        if current_chunk_end + 5 <= interval_end_sec:
                            current_chunk_end = current_chunk_start + self.CHUNK_MIN_DURATION
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
            
            # Statistiche
            durations = [end - start for start, end in final_chunks]
            avg_duration = np.mean(durations)
            min_duration = np.min(durations)
            max_duration = np.max(durations)
            
            self._log(f"  ✅ Chunks creati: {len(final_chunks)}")
            self._log(f"  📊 Durata media: {avg_duration:.1f}s (min: {min_duration:.1f}s, max: {max_duration:.1f}s)")
            if split_count > 0:
                self._log(f"  ✂️ Split forzati: {split_count} chunks")
            
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
            self._log("  ❌ librosa non disponibile")
            return []
        except Exception as e:
            self.logger.error(f"Errore chunking: {e}", exc_info=True)
            self._log(f"  ❌ Errore chunking: {str(e)}")
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
            
            # Nome file chunk
            chunk_filename = f"chunk_{chunk_num:04d}.wav"
            chunk_path = output_dir / chunk_filename
            
            try:
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
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                
                if result.returncode == 0 and chunk_path.exists():
                    chunk_files.append((chunk_path, start_time, end_time))
                else:
                    self.logger.error(f"    ❌ Chunk {chunk_num} fallito: {result.stderr}")
                    failed += 1
                    
            except subprocess.TimeoutExpired:
                self.logger.error(f"    ⏱️ Timeout chunk {chunk_num}")
                failed += 1
            except Exception as e:
                self.logger.error(f"    ❌ Errore chunk {chunk_num}: {e}")
                failed += 1
        
        success_rate = (len(chunk_files) / len(chunk_times)) * 100
        self._log(f"  ✅ Chunks creati: {len(chunk_files)}/{len(chunk_times)} ({success_rate:.1f}%)")
        
        if failed > 0:
            self._log(f"  ⚠️ Chunks falliti: {failed}")
        
        return chunk_files
    
    def _cleanup_gpu_memory(self):
        """Pulizia aggressiva memoria GPU"""
        if self.device == 'cuda':
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    
    def cleanup_model(self):
        """Scarica modello Demucs dalla memoria"""
        if self.demucs_model:
            del self.demucs_model
            self.demucs_model = None
            self._cleanup_gpu_memory()
            self.logger.info("🗑️ Modello Demucs scaricato dalla memoria")
