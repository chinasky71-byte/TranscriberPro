# -*- coding: utf-8 -*-
"""Campionamento delle risorse del sistema (CPU, RAM, GPU, VRAM, rete), senza Qt.

Estratto da gui/widgets.py (`ResourceMonitor.update_resources` e `_update_network_speed`). Stesse regole di prima:
  - ordine CPU -> RAM -> GPU/VRAM -> rete; un errore sulla CPU o sulla RAM salta TUTTO il resto (rete compresa), un errore sulla
    memoria della GPU lascia la GPU aggiornata e la VRAM vuota (None = «non cambia»);
  - la velocita' di rete si calcola fra due campioni consecutivi; senza riferimento precedente (o a tempo fermo) non c'e' valore;
    sotto 0,1 KB/s vale «0.0 KB/s», da 1024 KB/s in su si scrive in MB/s con due decimali.
I moduli `psutil` e `pynvml` e l'orologio si passano da fuori (prove senza hardware)."""
import time
from dataclasses import dataclass
from typing import Callable, Optional


def format_speed(kbs: float) -> tuple:
    """(testo, attivo): «2.00 MB/s» / «1.5 KB/s» / «0.0 KB/s» (non attivo se <= 0.1 KB/s)."""
    if kbs >= 1024:
        return f"{kbs / 1024:.2f} MB/s", True
    if kbs > 0.1:
        return f"{kbs:.1f} KB/s", True
    return "0.0 KB/s", False


@dataclass
class ResourceSample:
    cpu: Optional[float] = None
    ram: Optional[float] = None
    gpu: Optional[int] = None
    vram_percent: Optional[float] = None
    vram_used_gb: Optional[float] = None
    down: Optional[tuple] = None      # (testo, attivo)
    up: Optional[tuple] = None


class ResourceSampler:
    def __init__(self, psutil_mod, nvml_mod=None, gpu_handle=None, clock: Callable[[], float] = time.time):
        self._ps = psutil_mod
        self._nvml = nvml_mod
        self._gpu = gpu_handle
        self._clock = clock
        self.last_net_io = None
        self.last_update_time: Optional[float] = None

    def start(self) -> None:
        """Prende il riferimento della rete (come `start_monitoring`)."""
        self.last_net_io = self._ps.net_io_counters()
        self.last_update_time = self._clock()

    def sample(self) -> ResourceSample:
        s = ResourceSample()
        try:
            s.cpu = self._ps.cpu_percent(interval=0.1)
            s.ram = self._ps.virtual_memory().percent
            if self._gpu:
                try:
                    s.gpu = self._nvml.nvmlDeviceGetUtilizationRates(self._gpu).gpu
                    info = self._nvml.nvmlDeviceGetMemoryInfo(self._gpu)
                    s.vram_percent = (info.used / info.total) * 100
                    s.vram_used_gb = info.used / (1024 ** 3)
                except Exception:
                    pass
            self._net(s)
        except Exception:
            pass
        return s

    def _net(self, s: ResourceSample) -> None:
        try:
            current = self._ps.net_io_counters()
            now = self._clock()
            if self.last_net_io is not None and self.last_update_time is not None:
                dt = now - self.last_update_time
                if dt > 0:
                    s.up = format_speed(((current.bytes_sent - self.last_net_io.bytes_sent) / dt) / 1024)
                    s.down = format_speed(((current.bytes_recv - self.last_net_io.bytes_recv) / dt) / 1024)
            self.last_net_io = current
            self.last_update_time = now
        except Exception:
            pass
