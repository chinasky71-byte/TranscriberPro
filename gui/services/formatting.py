# -*- coding: utf-8 -*-
"""Formattazioni pure (nessun Qt) per ETA e tempo trascorso della coda."""

EN_DASH = "–"   # segnaposto "non disponibile" delle tessere statistiche


def format_eta(elapsed: float, completed: int, remaining: int) -> str:
    """ETA stimata dalla media per file completato: 'Hh MMm' (>= 1 h) oppure 'Mm SSs'.

    `elapsed` = secondi dall'avvio della coda. Segnaposto se non ci sono file completati o
    non resta nulla da fare. Il troncamento a int avviene sul totale (come in origine).
    """
    if completed > 0 and remaining > 0:
        eta_s = int((elapsed / completed) * remaining)
        h, r = divmod(eta_s, 3600)
        m, s = divmod(r, 60)
        return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"
    return EN_DASH


def format_elapsed(elapsed_seconds: int) -> str:
    """Tempo trascorso: 'HH:MM:SS' (>= 1 h) oppure 'MM:SS'. Ingresso gia' troncato a int."""
    h, r = divmod(elapsed_seconds, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
