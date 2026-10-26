# -*- coding: utf-8 -*-
"""Avanzamento della diarizzazione: dai passi di pyannote a una frazione 0..1 monotona.

Modulo puro (solo stdlib: nessun torch/onnxruntime/PyQt6, v. regola import di `utils`).

pyannote (4.0.x) chiama l'hook di `SpeakerDiarization.apply` cosi':
  - "segmentation"          con completed/total (a passi, per finestre scorrevoli) e una chiamata finale senza conteggi
  - "speaker_counting"      una volta
  - "embeddings"            con completed/total (a passi) e una chiamata finale senza conteggi
  - "discrete_diarization"  una volta, vicino alla fine
Il clustering e la costruzione dei turni non emettono nulla: sono ~6% del tempo.

Misura del 25/10/2026 (X Factor S20E07, 165 min, RTX 3060): segmentazione 4%, impronte vocali 90%, clustering 3%,
finalizzazione 3% del tempo; completed/total e tempo trascorso restano entro ~4 punti: una stima lineare e' affidabile.
"""
from __future__ import annotations

from typing import Callable, Optional

# Peso dei passi sulla barra (frazione cumulata alla loro fine)
SEG_END = 0.04          # segmentazione
EMB_END = 0.94          # impronte vocali (la parte lunga)
DISCRETE = 0.97         # ultima tappa annunciata da pyannote; il resto (clustering, turni) arriva a 1.0 con `finish()`


class DiarProgress:
    """Hook da passare a pyannote (`pipeline(audio, hook=DiarProgress(cb))`). `cb(frazione)` riceve valori monotoni in [0, 1]."""

    def __init__(self, on_fraction: Callable[[float], None]):
        self._cb = on_fraction
        self._last = -1.0

    def _emit(self, fraction: float) -> None:
        f = max(0.0, min(float(fraction), 1.0))
        if f > self._last:
            self._last = f
            try:
                self._cb(f)
            except Exception:
                pass          # l'avanzamento non deve mai far fallire la diarizzazione

    def __call__(self, step_name, step_artifact=None, file=None, total: Optional[int] = None,
                 completed: Optional[int] = None, **_ignored) -> None:         # argomenti nuovi di versioni future di pyannote: ignorati
        def frac(c, t) -> float:
            if c is None or not t:
                return 1.0        # chiamata finale del passo (senza conteggi): passo concluso
            return max(0.0, min(float(c) / float(t), 1.0))

        if step_name == 'segmentation':
            self._emit(SEG_END * frac(completed, total))
        elif step_name == 'speaker_counting':
            self._emit(SEG_END)
        elif step_name == 'embeddings':
            self._emit(SEG_END + (EMB_END - SEG_END) * frac(completed, total))
        elif step_name == 'discrete_diarization':
            self._emit(DISCRETE)

    def finish(self) -> None:
        """Diarizzazione conclusa (dopo il clustering e la costruzione dei turni): 100%."""
        self._emit(1.0)
