"""
Adaptive Batch Size Manager
File: utils/adaptive_batch_manager.py

Gestione dinamica del batch size per traduzione e trascrizione,
con riduzione automatica in caso di OOM e aumento progressivo
quando la memoria è disponibile.
"""
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

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

        if self._warmup_count < self.warmup_batches:
            # Fase warm-up: aumenta se la memoria lo consente
            mem = self._get_memory_usage()
            if mem < self.high_threshold:
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
            # Steady-state: adatta in base alla memoria
            mem = self._get_memory_usage()
            if mem > self.high_threshold:
                new_size = max(self.min_size, self.current_batch_size - 2)
                if new_size != self.current_batch_size:
                    self._log(
                        f"  Memoria alta ({mem:.0%}): batch {self.current_batch_size} → {new_size}"
                    )
                    self.current_batch_size = new_size
                    self._adjustments += 1
            elif mem < self.low_threshold and self.current_batch_size < self.max_size:
                new_size = min(self.current_batch_size + 1, self.max_size)
                self._log(
                    f"  Memoria bassa ({mem:.0%}): batch {self.current_batch_size} → {new_size}"
                )
                self.current_batch_size = new_size
                self._adjustments += 1

            # Pulizia periodica cache CUDA
            if self._batch_count % 10 == 0 and self.use_gpu and _TORCH_AVAILABLE:
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

        # 2. torch CUDA
        if _TORCH_AVAILABLE and self.use_gpu:
            try:
                allocated = torch.cuda.memory_allocated(0)
                total = torch.cuda.get_device_properties(0).total_memory
                if total > 0:
                    return allocated / total
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
