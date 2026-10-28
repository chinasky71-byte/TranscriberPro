# -*- coding: utf-8 -*-
"""ProgressLog: log testuale con barre di avanzamento riscritte sul posto, senza Qt.

Trasposizione fedele di `gui.progress_log.append_log_line` (il log del dialogo Sincronizzazione): una riga con una barra di avanzamento
(Demucs, Traduzione, Trascrizione...) sostituisce la propria barra precedente invece di accodarsi, a meno che quella sia completa ('✅')
o di una fase precedente (percentuale piu' alta). `append` restituisce l'operazione fatta sulle righe, cosi' la pagina la riproduce."""
import re
from typing import List

from core.services.log_filter import UPDATABLE_PATTERNS

SCAN_BLOCKS = 40


def _pct(text: str):
    m = re.search(r'(\d+)%', text)
    return int(m.group(1)) if m else None


class ProgressLog:
    def __init__(self, patterns=UPDATABLE_PATTERNS, keep: int = 2000):
        self.patterns, self.keep = patterns, keep
        self.lines: List[str] = []

    def append(self, msg: str) -> dict:
        """{'op': 'append'|'update_last'|'replace', 'line': testo, 'remove_index': indice della riga tolta (solo 'replace')}."""
        line = msg.rstrip('\n')
        lines = self.lines
        key = next((p for p in self.patterns if p in line), None) if '\n' not in line else None
        target = None
        if key is not None:
            new_pct = _pct(line)
            idx, n = len(lines) - 1, 0
            while idx >= 0 and n < SCAN_BLOCKS:
                text = lines[idx]
                if key in text:
                    old_pct = _pct(text)
                    if '✅' not in text and (new_pct is None or old_pct is None or old_pct <= new_pct):
                        target = idx
                    break
                idx -= 1
                n += 1
            if target is not None and new_pct is None and target != len(lines) - 1:
                target = None                        # righe di stato senza % si aggiornano solo se sono l'ultima
        if target is not None and target == len(lines) - 1:
            lines[-1] = line
            return {'op': 'update_last', 'line': line}
        if target is not None:
            del lines[target]
            lines.append(line)
            self._trim()
            return {'op': 'replace', 'line': line, 'remove_index': target}
        if len(lines) == 1 and lines[0] == '':
            lines[0] = line                              # documento vuoto di Qt: una sola riga vuota, il testo la riempie senza aggiungerne una
            return {'op': 'update_last', 'line': line}
        lines.append(line)
        self._trim()
        return {'op': 'append', 'line': line}

    def _trim(self) -> None:
        if len(lines := self.lines) > self.keep:
            del lines[:len(lines) - self.keep]
