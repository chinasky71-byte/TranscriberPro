# -*- coding: utf-8 -*-
"""Piano della coda del Subtitle Sync (tabella delle coppie video <-> SRT), senza Qt.

Trasposizione fedele della logica di gui/sync_dialog.py: abbinamento delle cartelle, scelta manuale dell'SRT, spunte, stato di ogni riga e
riepilogo. L'abbinamento vero e proprio e' in core/sync_pairing.py; qui c'e' lo stato che la tabella modifica. La vista resta il dialogo."""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from core import sync_pairing as SP

# Chiavi di stato (la vista le traduce con tr('sync_batch_state_<chiave>'))
NOSRT, DUP, CHECK, READY = 'nosrt', 'dup', 'check', 'ready'


@dataclass(frozen=True)
class PlanSummary:
    ready: int
    check: int
    nosrt: int
    left: int


class SyncBatchPlan:
    def __init__(self):
        self.pairs: List[SP.Pair] = []
        self.srt_files: List[Path] = []
        self.left_srts: List[Path] = []

    # ---------------------------------------------------------------------------------------------------------- abbinamento
    def scan(self, video_dir: str, srt_dir: str, recursive: bool) -> bool:
        """Abbina le due cartelle. False, senza toccare nulla, se una delle due e' vuota."""
        vd, sd = video_dir.strip(), srt_dir.strip()
        if not vd or not sd:
            return False
        videos = SP.list_files(vd, SP.VIDEO_EXT, recursive)
        self.srt_files = SP.list_files(sd, ('.srt',), recursive)
        self.pairs, self.left_srts = SP.pair_files(videos, self.srt_files)
        return True

    @staticmethod
    def srt_label(srt, base_dir: str) -> str:
        """Nome dell'SRT nella tendina: relativo alla cartella degli SRT, altrimenti il solo nome."""
        try:
            return str(Path(srt).relative_to(base_dir.strip()))
        except Exception:
            return Path(srt).name

    # ------------------------------------------------------------------------------------------------------------- modifiche
    def choose_srt(self, row: int, value: Optional[str]) -> None:
        """Scelta manuale dell'SRT per una riga (value vuoto/None = nessuno)."""
        p = self.pairs[row]
        p.srt = Path(value) if value else None
        p.score = 1.0 if value else 0.0          # scelta manuale dell'utente
        p.note = ''
        p.include = bool(value)
        p.refresh_output()

    def set_include(self, row: int, include: bool) -> None:
        self.pairs[row].include = include

    # ------------------------------------------------------------------------------------------------------------ stato/righe
    @staticmethod
    def state_of(p: SP.Pair) -> str:
        if p.srt is None:
            return NOSRT
        if p.duplicate:
            return DUP
        if p.note:
            return CHECK
        return READY

    def refresh(self) -> PlanSummary:
        """Ricalcola i duplicati e il riepilogo (pronte / da controllare / senza SRT / SRT non abbinati)."""
        SP.mark_duplicates(self.pairs)
        ready = check = nosrt = 0
        for p in self.pairs:
            if p.srt is None:
                nosrt += 1
            elif not p.duplicate and p.note:
                check += 1 if p.include else 0
            if p.include and p.srt is not None and not p.duplicate:
                ready += 1
        return PlanSummary(ready, check, nosrt, len(self.left_srts))

    def is_checked(self, p: SP.Pair) -> bool:
        return bool(p.include and p.srt is not None)

    def runnable(self) -> List[SP.Pair]:
        SP.mark_duplicates(self.pairs)
        return SP.runnable(self.pairs)
