# -*- coding: utf-8 -*-
"""Etichetta della scheda video (badge al centro della barra delle schede): rilevamento in un thread (nvidia-smi o il registro possono
impiegare secondi), con un secondo giro dopo 30 s se il primo sembra incompleto: stesse regole di `MainWindow._create_gpu_badge`."""
import threading
from typing import Callable, Optional, Tuple

from tpweb.events import EventBus


def default_detect(first: bool) -> Tuple[str, str, bool]:
    try:
        from utils.gpu_detect import detect_gpus
        from utils.gpu_label import gpu_badge_info, looks_incomplete
        rep = detect_gpus(force=not first)
        text, vendor = gpu_badge_info(rep)
        return text, vendor, bool(first and looks_incomplete(rep))
    except Exception:
        return 'CPU only', 'cpu', False


class GpuBadge:
    def __init__(self, bus: EventBus, detect: Callable[[bool], Tuple[str, str, bool]] = default_detect, retry_s: float = 30.0):
        self.bus, self._detect, self._retry_s = bus, detect, retry_s
        self.value: Optional[dict] = None

    def start(self) -> None:
        threading.Thread(target=self._work, args=(True,), name='tpweb-gpu-badge', daemon=True).start()

    def _work(self, first: bool) -> None:
        text, vendor, retry = self._detect(first)
        self.value = {'text': text, 'vendor': vendor}
        self.bus.publish('gpu_badge', self.value)
        if retry:
            t = threading.Timer(self._retry_s, self._work, args=(False,))
            t.daemon = True
            t.start()
