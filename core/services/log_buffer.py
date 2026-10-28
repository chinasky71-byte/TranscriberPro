# -*- coding: utf-8 -*-
"""LogBuffer: il log di elaborazione senza Qt (estratto da MainWindow.log_message / _write_progress_line / _log_color_html).

La decisione (scartare, barra, accodare) resta di `LogFilter`; qui c'e' la SCRITTURA: timestamp, colore per riga e la regola delle
barre di avanzamento «riscritte sul posto»:
  - si cerca all'indietro (al massimo 40 righe) l'ultima riga della STESSA barra (stessa chiave);
  - se e' ancora in corso (senza '✅' e con percentuale non superiore alla nuova) viene tolta e la barra riscritta IN FONDO
    (se era gia' l'ultima riga, si sovrascrive); altrimenti si accoda;
  - una riga di stato senza percentuale si aggiorna solo se e' l'ultima.
Il buffer tiene le ultime 5.000 righe (come `setMaximumBlockCount(5000)`). Ogni riga ha un `id` crescente; ogni scrittura produce
UN'operazione per i client: {'op': 'append'|'update_last'|'replace', 'line': {...}, 'remove_id': n}."""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from core.services.log_filter import LogFilter

MAX_LINES = 5000
PROGRESS_SCAN_LINES = 40

_PCT = re.compile(r'(\d+)%')


def kind_of(text: str) -> str:
    """Colore semantico della riga (stesse regole e stesso ordine di `_log_color_html`): success, danger, warn, info, muted."""
    if any(k in text for k in ('✅', '🎉')):
        return 'success'
    if '❌' in text:
        return 'danger'
    if '⚠' in text:
        return 'warn'
    if any(k in text for k in ('🎬', '⚙️', '➕', '===', '---')):
        return 'info'
    return 'muted'


def pct_of(text: str) -> Optional[int]:
    m = _PCT.search(text)
    return int(m.group(1)) if m else None


@dataclass
class LogResult:
    action: str                          # azione di LogFilter ('drop_ram', 'drop_noise', 'drop_compact', 'progress', 'append')
    op: Optional[dict] = None            # operazione per i client (None se la riga non va a schermo)
    model_name: Optional[str] = None     # 'Modello trascrizione: X' -> tessera «Modello»
    raw: str = ''                        # per 'drop_ram': il testo da scrivere solo sul logger


@dataclass
class LogBuffer:
    max_lines: int = MAX_LINES
    lines: List[dict] = field(default_factory=list)       # {'id', 'text', 'kind'}
    _next_id: int = 1
    _filter: LogFilter = field(default_factory=LogFilter)

    def add(self, message: str, now: Optional[datetime] = None, compact: bool = False, hide_progress: bool = False) -> LogResult:
        decision = self._filter.decide(message, compact, hide_progress=hide_progress)
        if decision.action == 'drop_ram':
            return LogResult('drop_ram', raw=message)
        if decision.action == 'drop_noise':
            return LogResult('drop_noise', model_name=decision.model_name)
        # il timestamp si prende anche per le righe che la modalita' compatta scarta (come la GUI: non ha effetti)
        text = f"[{(now or datetime.now()).strftime('%H:%M:%S')}] {decision.text}"
        if decision.action == 'drop_compact':
            return LogResult('drop_compact', model_name=decision.model_name)
        if decision.action == 'progress':
            return LogResult('progress', self._write_progress(decision.progress_key, decision.text, text), decision.model_name)
        return LogResult('append', self._append(text), decision.model_name)

    # ------------------------------------------------------------------------------------------------------------------ scrittura
    def _new_line(self, text: str) -> dict:
        line = {'id': self._next_id, 'text': text, 'kind': kind_of(text)}
        self._next_id += 1
        return line

    def _append(self, text: str) -> dict:
        line = self._new_line(text)
        self.lines.append(line)
        if len(self.lines) > self.max_lines:
            del self.lines[:len(self.lines) - self.max_lines]
        return {'op': 'append', 'line': line}

    def _write_progress(self, key: str, message: str, text: str) -> dict:
        new_pct = pct_of(message)
        last = self.lines[-1] if self.lines else None
        target = None
        for line in reversed(self.lines[-PROGRESS_SCAN_LINES:]):
            if key in line['text']:
                old_pct = pct_of(line['text'])
                if '✅' not in line['text'] and (new_pct is None or old_pct is None or old_pct <= new_pct):
                    target = line
                break
        target_is_last = target is not None and target is last
        if target is not None and not target_is_last and new_pct is None:
            target = None                      # righe di stato senza % (es. '⚙️ OCR'): si aggiornano solo se sono l'ultima
        if target_is_last:
            line = {'id': target['id'], 'text': text, 'kind': kind_of(text)}     # la riga e' la stessa, con testo nuovo
            self.lines[-1] = line
            return {'op': 'update_last', 'line': line}
        remove_id = None
        if target is not None:
            remove_id = target['id']
            self.lines.remove(target)
        op = self._append(text)
        if remove_id is not None:
            return {'op': 'replace', 'line': op['line'], 'remove_id': remove_id}
        return op
