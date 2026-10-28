# -*- coding: utf-8 -*-
"""Monitor delle risorse (fetta 1e): CPU, RAM, GPU, VRAM, rete, con lo stesso campionatore della GUI. La pagina interroga
`/api/resources` circa una volta al secondo; la velocita' di rete e' quella fra due richieste consecutive."""
import asyncio
import threading
import time
from typing import Optional

from fastapi import FastAPI

from core.services.resource_sampler import ResourceSampler


def make_default_sampler() -> ResourceSampler:
    """Campionatore vero. NVML (non CUDA) e' facoltativo: senza, la pagina nasconde GPU e VRAM."""
    import psutil
    nvml, handle = None, None
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        nvml = pynvml
    except Exception:
        nvml, handle = None, None
    sampler = ResourceSampler(psutil, nvml, handle, time.time)
    sampler.start()
    return sampler


def add_resource_routes(app: FastAPI, sampler: Optional[ResourceSampler] = None) -> None:
    holder = {'s': sampler}
    lock = threading.Lock()

    def sample_now() -> dict:
        with lock:
            if holder['s'] is None:
                holder['s'] = make_default_sampler()
            sm = holder['s']
            s = sm.sample()
            gpu_available = bool(sm._gpu)
        pair = lambda t: None if t is None else {'text': t[0], 'active': t[1]}      # noqa: E731
        return {'cpu': s.cpu, 'ram': s.ram, 'gpu_available': gpu_available, 'gpu': s.gpu, 'vram_percent': s.vram_percent,
                'vram_used_gb': s.vram_used_gb, 'down': pair(s.down), 'up': pair(s.up)}

    @app.get('/api/resources')
    async def resources():
        return await asyncio.get_running_loop().run_in_executor(None, sample_now)    # cpu_percent(interval=0.1) blocca 0,1 s
