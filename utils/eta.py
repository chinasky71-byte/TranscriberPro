# -*- coding: utf-8 -*-
"""
Stima del tempo rimanente (ETA) per le barre di avanzamento della trascrizione.

Un `EtaEstimator` per ogni fase: a ogni avanzamento si chiama `update(frazione)` (0..1; chunk
completati / totali, oppure posizione audio / durata) e si accoda il suffisso restituito alla
riga della barra, nello stesso formato della traduzione: ` │ ~12m` / ` │ ~40s`.

Il ritmo non e' costante (chunk di parlato costano piu' di musica e silenzio), quindi si usa il
ritmo recente (ultimo 15% del lavoro) e non la media dall'inizio; finche' il campione e' troppo
piccolo non si mostra nulla, per non dare un numero rumoroso (il primo chunk paga anche il
warm-up dei kernel).
"""
import time
from typing import List, Optional, Tuple


class EtaEstimator:
    MIN_FRACTION = 0.03        # sotto questo avanzamento non si stima
    MIN_ELAPSED_S = 20.0       # ...ne' prima di questo tempo dall'inizio
    RECENT_SPAN = 0.15         # finestra di ritmo recente, come frazione del lavoro
    MIN_RECENT_SPAN = 0.02     # sotto questa ampiezza la finestra recente non e' affidabile
    MIN_RECENT_SECONDS = 5.0   # ...ne' sotto questo tempo reale (aggiornamenti a raffica, come Canary)

    def __init__(self, clock=time.time):
        self._clock = clock
        self._t0 = clock()
        self._samples: List[Tuple[float, float]] = []   # (tempo, frazione), frazione crescente

    def update(self, fraction: float) -> str:
        """Registra l'avanzamento e ritorna il suffisso ` │ ~Nm` (stringa vuota se non stimabile)."""
        try:
            f = max(0.0, min(float(fraction), 1.0))
            now = self._clock()
            if self._samples and f < self._samples[-1][1]:
                return ""                      # avanzamento non monotono: non e' una stima affidabile
            self._samples.append((now, f))
            # tiene solo la finestra recente (+ un campione fuori): costo costante per aggiornamento
            while len(self._samples) > 2 and f - self._samples[1][1] > self.RECENT_SPAN:
                self._samples.pop(0)
            remaining = self.remaining_seconds(now, f)
            if remaining is None:
                return ""
            if remaining < 60:
                return f" │ ~{max(1, int(remaining))}s"
            return f" │ ~{int(remaining / 60 + 0.5)}m"       # minuto piu' vicino: il troncamento sottostimava
        except Exception:
            return ""

    def remaining_seconds(self, now: Optional[float] = None, f: Optional[float] = None) -> Optional[float]:
        if not self._samples:
            return None
        now = self._samples[-1][0] if now is None else now
        f = self._samples[-1][1] if f is None else f
        if f >= 1.0 or f < self.MIN_FRACTION or (now - self._t0) < self.MIN_ELAPSED_S:
            return None
        # ritmo recente: dal campione piu' vecchio entro RECENT_SPAN dall'avanzamento attuale
        old = next((s for s in self._samples if f - s[1] <= self.RECENT_SPAN), None)   # <= 2 elementi fuori finestra
        rate = None
        if (old is not None and (f - old[1]) >= self.MIN_RECENT_SPAN
                and (now - old[0]) >= self.MIN_RECENT_SECONDS):
            rate = (f - old[1]) / (now - old[0])
        if rate is None:                       # ripiego: media dall'inizio
            elapsed = now - self._t0
            rate = f / elapsed if elapsed > 0 else None
        if not rate or rate <= 0:
            return None
        return (1.0 - f) / rate
