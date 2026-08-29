"""
Adaptive Batch Size Manager
File: utils/adaptive_batch_manager.py

Gestione dinamica del batch size per traduzione e trascrizione,
con riduzione automatica in caso di OOM e aumento progressivo
quando la memoria è disponibile.
"""
import logging
from typing import Optional, Callable

# NON logging.getLogger(__name__): il root logger non viene mai configurato
# durante l'esecuzione normale (solo nel blocco di test di utils/config.py),
# quindi un logger "nudo" eredita il livello WARNING di default e ogni
# logger.info() qui dentro veniva scartato PRIMA di raggiungere il file
# condiviso — gli aggiustamenti di batch (l'unica traccia di cosa ha fatto
# davvero il gestore adattivo) non finivano mai nel log.
from utils.logger import setup_logger

logger = setup_logger(__name__)

try:
    import pynvml
    _NVML_AVAILABLE = True
except ImportError:
    _NVML_AVAILABLE = False

try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


class AdaptiveBatchSizeManager:
    """
    Gestisce il batch size adattivo durante la traduzione/trascrizione.

    - Warm-up: aumenta gradualmente il batch nelle prime N iterazioni
    - Steady-state: monitora la memoria e aggiusta il batch
    - OOM: dimezza il batch, resetta il warm-up
    """

    def __init__(
        self,
        device: str = 'cpu',
        use_gpu: bool = False,
        initial_size: Optional[int] = None,
        min_size: int = 1,
        max_size: int = 24,
        warmup_batches: int = 5,
        high_threshold: float = 0.85,
        low_threshold: float = 0.60,
        log_callback: Optional[Callable] = None,
    ):
        self.device = device
        self.use_gpu = use_gpu
        self.min_size = min_size
        self.max_size = max_size
        self.warmup_batches = warmup_batches
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold
        self.log_callback = log_callback

        # Inizializza pynvml se disponibile
        self._nvml_handle = None
        if _NVML_AVAILABLE and use_gpu:
            try:
                pynvml.nvmlInit()
                self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            except Exception:
                self._nvml_handle = None

        # Batch size iniziale
        if initial_size is not None:
            self.current_batch_size = max(min_size, min(initial_size, max_size))
        else:
            self.current_batch_size = self._detect_initial_size()

        # Stato
        self._warmup_count = 0
        self._oom_consecutive = 0
        self._batch_count = 0

        # Fatigue tracking (cross-file batch processing)
        self._files_processed = 0

        # Metriche
        self._oom_events = 0
        self._adjustments = 0
        self._total_batches = 0
        self._size_history: list = []

        self._log(
            f"AdaptiveBatchManager avviato: initial={self.current_batch_size}, "
            f"min={min_size}, max={max_size}, warmup={warmup_batches}, "
            f"device={'GPU' if use_gpu else 'CPU'}"
        )

    # ------------------------------------------------------------------
    # Metodi pubblici
    # ------------------------------------------------------------------

    @property
    def is_warming_up(self) -> bool:
        """True durante la fase di warm-up."""
        return self._warmup_count < self.warmup_batches

    def get_batch_size(self) -> int:
        """
        Restituisce il batch size da usare per il prossimo batch.
        Gestisce la fase di warm-up e lo steady-state.
        """
        self._total_batches += 1
        self._size_history.append(self.current_batch_size)

        mem = self._get_memory_usage()
        # Solo file (DEBUG): traccia completa batch-per-batch anche quando
        # la dimensione non cambia — senza, dal log si vedono solo gli
        # aggiustamenti e non si può ricostruire la traiettoria di memoria
        # reale di una run per giudicare se un tetto più alto reggerebbe.
        logger.debug(
            f"  [batch-trace] #{self._total_batches} size={self.current_batch_size} "
            f"mem={mem:.1%} warmup={self.is_warming_up}"
        )

        if self._warmup_count < self.warmup_batches:
            # Fase warm-up: aumenta se la memoria lo consente, riduce se satura.
            # GOTCHA (v1.9.5): prima il warm-up controllava la memoria SOLO per
            # decidere se aumentare — su file con pochi batch totali (es. 9),
            # l'intero file passava dentro il warm-up a batch già troppo alto
            # senza mai reagire, fino a spillover WDDM sostenuto (2,44 GB per
            # 6+ minuti su Petra S02E02). Ora simmetrico allo steady-state.
            if mem > self.high_threshold:
                new_size = max(self.min_size, self.current_batch_size - 2)
                if new_size != self.current_batch_size:
                    logger.info(
                        f"  Memoria alta in warm-up ({mem:.0%}): batch {self.current_batch_size} → {new_size}"
                    )
                    self.current_batch_size = new_size
                    self._adjustments += 1
            elif mem < self.high_threshold:
                new_size = min(self.current_batch_size + 4, self.max_size)
                if new_size != self.current_batch_size:
                    self.current_batch_size = new_size
                    self._adjustments += 1
            # Barra di progresso warm-up (aggiornata in-place nella GUI)
            step = self._warmup_count + 1
            bars = int((step / self.warmup_batches) * 10)
            pct = int((step / self.warmup_batches) * 100)
            bar = '█' * bars + '░' * (10 - bars)
            self._log(f"  Warm-up: [{bar}] {pct}%  (batch={self.current_batch_size}, mem={mem:.0%})")
            self._warmup_count += 1
        else:
            # Steady-state: adatta in base alla memoria.
            # Gli aggiustamenti ±1 vanno SOLO sul file di log: a schermo si
            # intercalerebbero tra gli aggiornamenti della barra di progresso
            # impedendone la sovrascrittura in-place (decine di righe/file).
            # Restano a schermo gli eventi importanti: OOM e riepilogo finale.
            if mem > self.high_threshold:
                new_size = max(self.min_size, self.current_batch_size - 2)
                if new_size != self.current_batch_size:
                    logger.info(
                        f"  Memoria alta ({mem:.0%}): batch {self.current_batch_size} → {new_size}"
                    )
                    self.current_batch_size = new_size
                    self._adjustments += 1
            elif mem < self.low_threshold and self.current_batch_size < self.max_size:
                new_size = min(self.current_batch_size + 1, self.max_size)
                logger.info(
                    f"  Memoria bassa ({mem:.0%}): batch {self.current_batch_size} → {new_size}"
                )
                self.current_batch_size = new_size
                self._adjustments += 1

        # Pulizia cache CUDA: reattiva sulla soglia (non più a cadenza fissa
        # ogni 10 batch). GOTCHA (v1.9.5): la cadenza fissa non scattava mai
        # sui file con pochi batch totali (la maggioranza delle traduzioni
        # notturne ne aveva 8-9) — la cache dell'allocator PyTorch non veniva
        # mai rilasciata, gonfiando mem_get_info indipendentemente dai tensori
        # realmente attivi e contribuendo allo sconfinamento WDDM.
        if mem > self.high_threshold and self.use_gpu and _TORCH_AVAILABLE:
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

        self._batch_count += 1
        return self.current_batch_size

    def record_success(self):
        """Da chiamare dopo ogni batch completato con successo."""
        self._oom_consecutive = 0

    def record_oom(self):
        """
        Da chiamare quando si verifica un OOM.
        Dimezza il batch size e resetta il warm-up.
        """
        self._oom_consecutive += 1
        self._oom_events += 1

        if self._oom_consecutive >= 3:
            # Panic fallback: vai al minimo
            new_size = self.min_size
            self._log(
                f"  OOM critico (×{self._oom_consecutive}): panic fallback → batch={new_size}"
            )
        else:
            new_size = max(self.min_size, self.current_batch_size // 2)
            self._log(
                f"  OOM! batch {self.current_batch_size} → {new_size} "
                f"(OOM consecutivi: {self._oom_consecutive})"
            )

        self.current_batch_size = new_size
        self._adjustments += 1
        self._warmup_count = 0  # Reset warm-up

        if self.use_gpu and _TORCH_AVAILABLE:
            try:
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            except Exception:
                pass

    def reset(self):
        """
        Resetta lo stato per un nuovo file.
        Da chiamare all'inizio di ogni translate_file().
        """
        self._warmup_count = 0
        self._oom_consecutive = 0
        self._batch_count = 0
        self._size_history.clear()
        # Non resettiamo le metriche cumulative (oom_events, adjustments)

    def get_metrics(self) -> dict:
        """Restituisce statistiche sull'utilizzo del manager."""
        sizes = self._size_history
        return {
            'min_batch': min(sizes) if sizes else self.current_batch_size,
            'max_batch': max(sizes) if sizes else self.current_batch_size,
            'avg_batch': sum(sizes) / len(sizes) if sizes else self.current_batch_size,
            'oom_events': self._oom_events,
            'adjustments': self._adjustments,
            'total_batches': self._total_batches,
        }

    def log_summary(self):
        """Stampa statistiche finali via log_callback."""
        m = self.get_metrics()
        self._log(
            f"  Batch manager stats — batch medio: {m['avg_batch']:.1f} "
            f"(min={m['min_batch']}, max={m['max_batch']}), "
            f"OOM: {m['oom_events']}, aggiustamenti: {m['adjustments']}, "
            f"batch totali: {m['total_batches']}"
        )

    # ------------------------------------------------------------------
    # VRAM-aware safe batch (OOM prevention)
    # ------------------------------------------------------------------

    def set_files_processed(self, count: int):
        """Aggiorna il contatore file elaborati per il calcolo fatigue."""
        self._files_processed = count

    def _get_free_vram_gb(self) -> float:
        """
        Restituisce VRAM libera in GB a livello OS.
        pynvml vede TUTTA la VRAM (incluso ctranslate2), torch solo la propria.
        """
        # 1. pynvml — fonte più affidabile (vede allocazioni ctranslate2)
        if self._nvml_handle is not None:
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                return mem.free / (1024 ** 3)
            except Exception:
                pass

        # 2. torch.cuda.mem_get_info — buon fallback
        if _TORCH_AVAILABLE and self.use_gpu:
            try:
                free, total = torch.cuda.mem_get_info(0)
                return free / (1024 ** 3)
            except Exception:
                pass

        return 0.0

    def compute_safe_batch_size(
        self,
        audio_duration_s: float = 0,
        beam_size: int = 5,
        model_vram_gb: float = 1.5,
    ) -> int:
        """
        Calcola batch size massimo sicuro basandosi sulla VRAM libera reale.

        Strategia:
        - Sottrae margine di sicurezza (1.5 GB) dalla VRAM libera
        - Stima costo per elemento batch: beam_size × 0.15 GB (empirico large-v3 int8_float16)
        - Penalità per audio lungo e per fatigue (file consecutivi)
        - Ritorna max(min_size, risultato)
        """
        free_gb = self._get_free_vram_gb()
        total_gb = self._get_total_vram_gb()

        if free_gb <= 0 or total_gb <= 0:
            # Nessuna info VRAM — ritorna max_size (nessun cap)
            return self.max_size

        safety_margin_gb = 1.5
        available_gb = free_gb - model_vram_gb - safety_margin_gb

        if available_gb <= 0:
            self._log(
                f"  ⚠️ VRAM molto bassa: {free_gb:.1f} GB liberi, "
                f"margine={safety_margin_gb} GB → batch={self.min_size}"
            )
            return self.min_size

        # Costo per elemento batch (empirico: large-v3 int8_float16 su RTX 3060)
        cost_per_element_gb = beam_size * 0.15
        if cost_per_element_gb <= 0:
            cost_per_element_gb = 0.3

        max_safe = int(available_gb / cost_per_element_gb)

        # Penalità durata audio
        if audio_duration_s > 7200:
            max_safe -= 2
        elif audio_duration_s > 3600:
            max_safe -= 1

        # Penalità fatigue (frammentazione VRAM dopo molti file)
        if self._files_processed > 20:
            max_safe = min(max_safe, self.min_size + 1)
        elif self._files_processed > 10:
            max_safe -= 2
        elif self._files_processed > 5:
            max_safe -= 1

        result = max(self.min_size, min(max_safe, self.max_size))

        self._log(
            f"  🧮 Safe batch: VRAM {free_gb:.1f}/{total_gb:.1f} GB free, "
            f"available={available_gb:.1f} GB, beam={beam_size}, "
            f"fatigue={self._files_processed} files → safe_ceiling={result}"
        )

        return result

    # ------------------------------------------------------------------
    # Metodi interni
    # ------------------------------------------------------------------

    def _detect_initial_size(self) -> int:
        """Auto-rileva batch size iniziale in base alla VRAM disponibile."""
        if not self.use_gpu:
            return min(4, self.max_size)

        vram_gb = self._get_total_vram_gb()
        if vram_gb >= 24:
            size = 16
        elif vram_gb >= 12:
            size = 8
        elif vram_gb >= 8:
            size = 4
        else:
            size = 2

        return max(self.min_size, min(size, self.max_size))

    def _get_total_vram_gb(self) -> float:
        """Restituisce VRAM totale in GB (0 se non disponibile)."""
        if self._nvml_handle is not None:
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                return mem.total / (1024 ** 3)
            except Exception:
                pass
        if _TORCH_AVAILABLE and self.use_gpu:
            try:
                props = torch.cuda.get_device_properties(0)
                return props.total_memory / (1024 ** 3)
            except Exception:
                pass
        return 0.0

    def _get_memory_usage(self) -> float:
        """
        Restituisce utilizzo memoria corrente come frazione [0,1].
        Cascade: pynvml → torch → psutil RAM.
        """
        # 1. pynvml (VRAM)
        if self._nvml_handle is not None:
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                if mem.total > 0:
                    return mem.used / mem.total
            except Exception:
                pass

        # 2. torch CUDA — mem_get_info è a livello DEVICE (vede anche le
        # allocazioni ctranslate2 e degli altri processi); memory_allocated
        # vedrebbe SOLO i tensori torch del processo → sottostima enorme
        # durante la trascrizione whisper e batch gonfiato fino allo
        # spillover WDDM in RAM condivisa
        if _TORCH_AVAILABLE and self.use_gpu:
            try:
                free_b, total_b = torch.cuda.mem_get_info(0)
                if total_b > 0:
                    return (total_b - free_b) / total_b
            except Exception:
                pass

        # 3. psutil RAM (fallback CPU)
        if _PSUTIL_AVAILABLE:
            try:
                return psutil.virtual_memory().percent / 100.0
            except Exception:
                pass

        return 0.5  # valore neutro se tutto fallisce

    def _log(self, message: str):
        """Helper di logging."""
        logger.info(message)
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                pass

    def __del__(self):
        if _NVML_AVAILABLE and self._nvml_handle is not None:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
