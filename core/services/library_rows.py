# -*- coding: utf-8 -*-
"""Righe, filtri e badge del Library Scanner, senza Qt.

Trasposizione fedele della logica di gui/library_scanner_widget.py: rilevamento della lingua dal nome, testo del tipo, classi di colore dei
giorni, tipo di badge e sua etichetta, regola dei filtri giorni+formato, testo delle statistiche, quando ricaricare dal server cambiando
filtro. La tabella resta la vista (celle, colori, widget)."""
import re
from typing import Optional, Tuple

from utils.translations import tr

# (?<![a-zA-Z]) / (?![a-zA-Z]) gestisce separatori come punto, trattino,
# underscore, parentesi — più robusto di \b che tratta _ come parola
IT_TAGS_RE = re.compile(
    r'(?<![a-zA-Z])(ita|nuita|italian|italiano)(?![a-zA-Z])',
    re.IGNORECASE,
)
FOREIGN_TAGS_RE = re.compile(
    r'(?<![a-zA-Z])(eng|nueng|english|fra|french|fre|spa|spanish|ger|german|deu|'
    r'por|portuguese|rus|russian|jpn|japanese|kor|korean|chi|chinese|nld|dutch)(?![a-zA-Z])',
    re.IGNORECASE,
)

FORMAT_ASS = 'assssa'
FORMAT_NOSRT = 'nosrt'


def detect_italian(filename: str) -> str:
    """Lingua audio dal filename tramite tag espliciti: 'ita' | 'foreign' | 'unknown'."""
    if IT_TAGS_RE.search(filename):
        return 'ita'
    if FOREIGN_TAGS_RE.search(filename):
        return 'foreign'
    return 'unknown'


def type_text(media_type: str) -> str:
    return tr('film_type') if media_type == 'movie' else tr('tv_series_type') if media_type == 'tvshow' else media_type


def days_class(days: int) -> Optional[str]:
    """'danger' oltre 30 giorni, 'warn' oltre 14, altrimenti None."""
    if days > 30:
        return 'danger'
    elif days > 14:
        return 'warn'
    return None


def badge_kind(video: dict) -> Optional[str]:
    """'bitmap' (serve OCR), 'ass' (ASS/SSA convertibile) o None."""
    if video.get('has_only_bitmap_subs', False):
        return 'bitmap'
    if video.get('has_italian_convertible_subs', False):
        return 'ass'
    return None


def badge_label_kind(fmt) -> Tuple[str, str]:
    """bitmap_format -> (etichetta badge, kind per il motore OCR)."""
    if fmt == 'vobsub':
        return "VOB", "vobsub"
    if fmt == 'mixed':
        return "MIX", "pgs"   # default PGS per i misti (la traccia PGS è preferibile)
    return "PGS", "pgs"


def selected_media_type(index: int) -> str:
    if index == 1:
        return 'movie'
    if index == 2:
        return 'tvshow'
    return ''


def is_row_hidden(days: int, min_days: int, fmt: Optional[str], row_fmt, has_ass: bool, only_bitmap: bool) -> bool:
    """Regola dei filtri giorni + formato per una riga."""
    hide = min_days > 0 and days < min_days
    if not hide and fmt:
        if fmt == FORMAT_NOSRT:
            if row_fmt is not None:
                hide = True
        elif fmt == FORMAT_ASS:
            if not has_ass:
                hide = True
        else:
            # Filtri bitmap (pgs/vobsub): mostra SOLO i file che necessitano davvero OCR (has_only_bitmap_subs). Un file con stream
            # PGS ma sub testo ITA presente ha bitmap_format='pgs' ma has_only_bitmap_subs=False -> non e' un job OCR.
            # 'mixed' soddisfa sia PGS sia VOBSUB.
            if not only_bitmap or not (row_fmt == fmt or row_fmt == 'mixed'):
                hide = True
    return hide


def reload_on_format_change(prev: Optional[str], fmt: Optional[str]) -> bool:
    """ASS/SSA usa un endpoint diverso: serve ricaricare dal server, anche tornando da ASS/SSA a un altro filtro."""
    return fmt == FORMAT_ASS or prev == FORMAT_ASS


def stats_text(stats: dict) -> Tuple[str, int]:
    """(testo delle statistiche, numero di file senza sottotitoli)."""
    without = stats.get('without_subs', 0)
    total = stats.get('total_files', 0)
    return tr('files_stats').format(without=without, total=total), without
