# -*- coding: utf-8 -*-
"""Revisione mirata dell'OCR dei sottotitoli bitmap: logica senza Qt.

Trasposizione fedele di gui/ocr_review_dialog.py: etichette e pallini di confidenza, contatore, filtro "solo dubbi", ricerca del prossimo
dubbio (con giro completo), salvataggio del testo, "verificato", corsivo e riga di info. Il dialogo resta la vista (lista, immagine,
editor, pulsanti). Contratto dati: core/pgs_types.py (OcrEvent). Nessuna correzione automatica: l'utente e' l'unica fonte di verita'."""
from typing import List, Optional, Tuple

from core.pgs_types import OcrEvent, ms_to_srt_timestamp
from utils.translations import tr

# Soglia colore badge confidenza (puramente visiva; il flag autorevole è is_flagged).
CONF_OK = 85.0
CONF_WARN = 70.0


def conf_dot(ev: OcrEvent) -> str:
    """Pallino colorato (unicode) in base alla confidenza."""
    c = ev.confidence or 0.0
    if c >= CONF_OK:
        return "🟢"
    if c >= CONF_WARN:
        return "🟡"
    return "🔴"


def item_label(ev: OcrEvent) -> str:
    snippet = (ev.text or "").replace("\n", " ").strip()
    if len(snippet) > 40:
        snippet = snippet[:40] + "…"
    if not snippet:
        snippet = tr('ocr_empty_text')
    check = "✓ " if ev.verified else ""
    return f"{conf_dot(ev)} #{ev.index}  {check}{snippet}"


def visible_indices(events: List[OcrEvent], only_flagged: bool) -> List[int]:
    """Indici (nell'elenco degli eventi) da mostrare nella lista, rispettando il filtro "solo dubbi"."""
    return [i for i, ev in enumerate(events) if not only_flagged or ev.is_flagged]


def counter_text(events: List[OcrEvent]) -> str:
    flagged = sum(1 for ev in events if ev.is_flagged)
    return tr('ocr_counter').format(total=len(events), flagged=flagged)


def next_flagged_from(events: List[OcrEvent], idx: int) -> Optional[int]:
    """Primo evento dubbio con indice > idx, con giro completo (None se nessuno)."""
    for i in range(idx + 1, len(events)):
        if events[i].is_flagged:
            return i
    # wrap-around: cerca dall'inizio
    for i in range(0, idx + 1):
        if events[i].is_flagged:
            return i
    return None


def event_info(ev: OcrEvent) -> str:
    state = tr('ocr_state_verified') if ev.verified else (
        tr('ocr_state_flagged') if ev.is_flagged else tr('ocr_state_ok')
    )
    return (
        f"#{ev.index}  "
        f"{ms_to_srt_timestamp(ev.start_ms)} → {ms_to_srt_timestamp(ev.end_ms)}  "
        f"·  {tr('ocr_confidence')}: {ev.confidence:.0f}  ·  {state}"
    )


def apply_text(ev: OcrEvent, new_text: str) -> bool:
    """Scrive il testo dell'editor nell'evento. True se e' cambiato."""
    if ev.text != new_text:
        ev.text = new_text
        return True
    return False


def mark_verified(ev: OcrEvent, new_text: str) -> None:
    """Salva il testo, verified=True e pulisce i flag (non piu' "dubbio")."""
    apply_text(ev, new_text)
    ev.verified = True
    ev.flags = set()


def toggle_italic_on(text: str) -> str:
    s = text.strip()
    if s.startswith("<i>") and s.endswith("</i>"):
        # Rimuove i tag preservando spazi esterni.
        lead = text[:len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        inner = s[3:-4]
        return f"{lead}{inner}{trail}"
    if not s:
        return text
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return f"{lead}<i>{s}</i>{trail}"


def toggle_italic(full: str, sel: Optional[Tuple[int, int]]) -> Tuple[str, Optional[Tuple[int, int]]]:
    """Avvolge/rimuove <i>...</i> sulla selezione (start, end), o sull'intero testo se sel e' None.
    Ritorna (nuovo testo, nuova selezione o None)."""
    if sel is not None:
        start, end = sel
        new_segment = toggle_italic_on(full[start:end])
        return full[:start] + new_segment + full[end:], (start, start + len(new_segment))
    return toggle_italic_on(full), None
