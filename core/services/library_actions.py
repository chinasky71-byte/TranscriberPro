# -*- coding: utf-8 -*-
"""Azioni del Library Scanner (import in coda, conversione ASS/SSA, Superpower, OCR), senza Qt.

Trasposizione fedele della logica di decisione di gui/library_scanner_widget.py: quali percorsi entrano in coda, la richiesta e la risposta
della conversione ASS/SSA, la richiesta e l'esito del Superpower, la strategia dell'OCR e il testo dell'avanzamento. Il widget resta la
vista (dialoghi, log, pulsanti, worker)."""
import json
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from core.pgs_types import STRATEGY_AUTO
from utils.path_map import to_local
from utils.translations import tr


# ---------------------------------------------------------------------------------------------------------- import in coda
def plan_import(paths: List[str], rules, in_queue: Callable[[str], bool], is_active: Optional[Callable[[str], bool]] = None) -> List[str]:
    """Percorsi LOCALI da aggiungere alla coda, nell'ordine: mappa server->locale, scarta vuoti, file gia' in lavorazione, file gia' in
    coda (anche aggiunti in questa stessa chiamata)."""
    out: List[str] = []
    seen = set()
    for path in paths:
        path = to_local(path, rules)
        if is_active is not None and path and is_active(path):
            continue
        if path and not in_queue(path) and path not in seen:
            seen.add(path)
            out.append(path)
    return out


# ------------------------------------------------------------------------------------------------------------ credenziali
def clean_credentials(url: str, api_key: str) -> Tuple[str, str]:
    """(URL senza spazi e senza '/' finale, chiave senza spazi)."""
    return (url or '').strip().rstrip('/'), (api_key or '').strip()


# ---------------------------------------------------------------------------------------------------------------- ASS/SSA
def ass_start_request(url: str, video_ids: list) -> Tuple[str, dict]:
    """(URL, corpo): corpo vuoto = il server converte tutti i pending; ID specifici = solo quei file."""
    return f"{url}/api/subtitles/convert/start", ({"video_ids": video_ids} if video_ids else {})


@dataclass(frozen=True)
class AssReply:
    log: str
    level: str        # 'information' | 'warning'
    message: str


def ass_reply(status: int, text: str, video_ids: list) -> AssReply:
    if status == 200:
        if video_ids:
            desc = tr('ls_n_files').format(n=len(video_ids))
            log = tr('ls_ass_log_started').format(desc=desc)
        else:
            desc = tr('ls_all_pending')
            log = tr('ls_ass_log_started_all')
        return AssReply(log, 'information', tr('ls_ass_started_body').format(desc=desc))
    if status == 0:
        return AssReply(tr('ls_ass_log_conn_err').format(text=text), 'warning', tr('ls_conn_err').format(text=text))
    return AssReply(tr('ls_ass_log_srv_err').format(status=status), 'warning', tr('ls_srv_err').format(status=status, text=text[:200]))


# -------------------------------------------------------------------------------------------------------------- Superpower
SUPERPOWER_LIST_PARAMS = {"issue_type": "bitmap", "limit": 500}
SUPERPOWER_LIST_TIMEOUT = 15


def superpower_request(url: str) -> Tuple[str, dict, int]:
    return f"{url}/api/subtitles/list", dict(SUPERPOWER_LIST_PARAMS), SUPERPOWER_LIST_TIMEOUT


@dataclass(frozen=True)
class SuperpowerResult:
    kind: str                       # 'error' | 'bad_reply' | 'none' | 'ok'
    message: str = ''               # per error / bad_reply: il testo gia' tradotto
    items: tuple = ()               # [(windows_path, kind)] per 'ok'


def parse_superpower_reply(status: int, text: str, kind_of: Callable[[Optional[str]], Tuple[str, str]]) -> SuperpowerResult:
    if status != 200:
        err = text if status == 0 else f"HTTP {status}: {text[:200]}"
        return SuperpowerResult('error', tr('ls_sp_list_err').format(err=err))
    try:
        data = json.loads(text)
    except Exception as e:
        return SuperpowerResult('bad_reply', tr('ls_sp_bad_reply').format(err=e))
    items = []
    for v in data.get("videos", []):
        fmt = v.get("bitmap_format")
        if not fmt:
            continue
        wp = v.get("windows_path", "")
        if not wp:
            continue
        _, kind = kind_of(fmt)
        items.append((wp, kind))
    if not items:
        return SuperpowerResult('none')
    return SuperpowerResult('ok', items=tuple(items))


# ------------------------------------------------------------------------------------------------------------------- OCR
def job_kind_label(kind: str) -> str:
    return 'VOBSUB' if kind == 'vobsub' else 'PGS'


def resolve_strategy(force_auto: bool, configured: str, override: Optional[str]) -> str:
    """Strategia dell'OCR: automatica se forzata (batch), altrimenti quella configurata; la scelta per file ('review'|'auto') prevale."""
    strategy = STRATEGY_AUTO if force_auto else configured
    if override in ('review', 'auto'):
        strategy = override
    return strategy


def progress_text(name: str, label: str, percent: int, batch_active: bool, ok: int, fail: int, total: int) -> str:
    if batch_active:
        done = ok + fail
        prefix = f"OCR batch {min(done + 1, total)}/{total} · "
    else:
        prefix = "OCR · "
    return f"{prefix}{name} — {label} {percent}%"
