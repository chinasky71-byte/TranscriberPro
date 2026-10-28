# -*- coding: utf-8 -*-
"""ToolGate: mutua esclusione tra la coda di elaborazione e gli strumenti (Glossario, Sincronizzazione, conversione OCR), senza Qt.

Le regole sono quelle della GUI (`QueueService.can_start`, `MainWindow._open_glossary_dialog` / `_open_sync_dialog`): glossario e
sincronizzazione caricano gli stessi modelli sulla stessa GPU della coda, farli girare insieme e' contesa di VRAM silenziosa. Nella GUI i
pulsanti disattivati e il dialogo modale facevano da guardia; sul server ogni controllo e' atomico (un solo lucchetto per coda e strumenti,
perche' due schede del browser possono premere insieme), e i flag li azzera il thread del run nel suo `finally`, mai la pagina.
"""
import threading
from typing import Callable, Optional

OK, EMPTY, OCR, GLOSSARY, SYNC = 'ok', 'empty', 'ocr', 'glossary', 'sync'     # stessi valori di StartVerdict (gui/services/queue_service.py)
TOOLS = ('glossary', 'sync')

# Chiavi dei messaggi che la pagina mostra quando l'avvio e' rifiutato (le stesse della GUI).
START_BLOCKED_KEYS = {OCR: ('mw_start_blocked_title', 'mw_start_blocked_ocr'),
                      GLOSSARY: ('tools_glossary', 'glossary_running_blocks_processing'),
                      SYNC: ('sync_dialog_title', 'sync_running_blocks_processing')}
TOOL_BLOCKED_KEYS = {('glossary', 'processing'): 'glossary_blocked_processing', ('glossary', 'sync'): 'glossary_blocked_sync',
                     ('sync', 'processing'): 'sync_blocked_processing', ('sync', 'glossary'): 'sync_blocked_glossary',
                     ('sync', 'sync'): 'sync_already_running'}
TOOL_TITLE_KEYS = {'glossary': 'tools_glossary', 'sync': 'sync_dialog_title'}


class ToolGate:
    def __init__(self, processing: Optional[Callable[[], bool]] = None):
        self.lock = threading.RLock()
        self.processing = processing or (lambda: False)     # lo imposta la coda: «sta elaborando?»
        self.glossary_active = False
        self.sync_active = False
        self.ocr_running = False

    def queue_verdict(self, has_items: bool) -> str:
        """Precedenza: coda vuota (silenziosa) > OCR > Glossario > Sincronizzazione. Chiamare con `lock` preso."""
        if not has_items:
            return EMPTY
        if self.ocr_running:
            return OCR
        if self.glossary_active:
            return GLOSSARY
        if self.sync_active:
            return SYNC
        return OK

    def begin_tool(self, tool: str) -> Optional[str]:
        """Prenota lo strumento. None = prenotato; altrimenti la chiave del messaggio (nessun flag e' cambiato). Atomico rispetto a
        `WebQueue.start`, che prende lo stesso `lock`."""
        if tool not in TOOLS:
            raise ValueError(tool)
        with self.lock:
            if self.processing():
                return TOOL_BLOCKED_KEYS[(tool, 'processing')]
            if tool == 'glossary':
                if self.sync_active:
                    return TOOL_BLOCKED_KEYS[('glossary', 'sync')]
                if self.glossary_active:
                    return 'running'                      # un solo run di glossario (come il dialogo a istanza singola)
                self.glossary_active = True
            else:
                if self.glossary_active:
                    return TOOL_BLOCKED_KEYS[('sync', 'glossary')]
                if self.sync_active:
                    return TOOL_BLOCKED_KEYS[('sync', 'sync')]
                self.sync_active = True
            return None

    def end_tool(self, tool: str) -> None:
        with self.lock:
            setattr(self, f'{tool}_active', False)

    def snapshot(self) -> dict:
        with self.lock:
            return {'glossary': self.glossary_active, 'sync': self.sync_active, 'ocr': self.ocr_running}
