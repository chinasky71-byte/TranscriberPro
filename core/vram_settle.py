# -*- coding: utf-8 -*-
"""Attesa che la VRAM liberata dagli ASR sia davvero tornata libera, prima che parta la traduzione.

Su Windows (WDDM) `cudaFree` / `empty_cache()` ritornano prima che il video memory manager abbia restituito le pagine: per
qualche secondo `mem_get_info()` mostra ancora occupata la memoria di Whisper/Demucs/pyannote. Se in quel momento parte il
caricamento del traduttore (GGUF nel sottoprocesso) la somma eccede la VRAM e il driver sconfina in RAM
condivisa. `wait_vram_settled` legge la VRAM libera a intervalli e rientra quando e' stabile.

Nessun import di torch (ne' di altri moduli pesanti): la lettura arriva da `read_free_bytes`, cosi' la funzione si prova senza GPU.
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Tuple

STABLE_DELTA_BYTES = 64 * 1024 ** 2     # variazione sotto la quale due letture consecutive valgono "ferma"
STABLE_READS = 3                        # letture ferme consecutive per considerarla assestata
POLL_S = 0.25
TIMEOUT_S = 8.0


def wait_vram_settled(read_free_bytes: Callable[[], Optional[int]], *,
                      timeout_s: float = TIMEOUT_S, poll_s: float = POLL_S,
                      stable_reads: int = STABLE_READS, stable_delta: int = STABLE_DELTA_BYTES,
                      cancelled: Callable[[], bool] = lambda: False,
                      sleep: Callable[[float], None] = time.sleep,
                      clock: Callable[[], float] = time.monotonic) -> Tuple[Optional[int], Optional[int], bool]:
    """(VRAM libera iniziale, VRAM libera finale, assestata) in byte. Se la lettura non e' disponibile (nessuna GPU, errore)
    rientra subito con (None, None, True). Allo scadere di `timeout_s` o su annullo rientra con l'ultima lettura e
    assestata=False: la traduzione parte comunque, la decisione sulla quantizzazione la prende chi legge la VRAM dopo."""
    def read() -> Optional[int]:
        try:
            v = read_free_bytes()
            return None if v is None else int(v)
        except Exception:
            return None

    first = last = read()
    if first is None:
        return None, None, True
    deadline = clock() + timeout_s
    stable = 0
    while stable < stable_reads:
        if cancelled() or clock() >= deadline:
            return first, last, False
        sleep(poll_s)
        cur = read()
        if cur is None:
            return first, last, True
        stable = stable + 1 if abs(cur - last) < stable_delta else 0
        last = cur
    return first, last, True
