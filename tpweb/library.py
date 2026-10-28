# -*- coding: utf-8 -*-
"""Library Scanner nella pagina (fase 5a): elenco dei video senza sottotitoli italiani, filtri, import in coda, conversione ASS/SSA e
notifica del server quando la coda crea un sottotitolo. Le regole sono quelle della GUI (core/services/library_rows.py e
library_actions.py, gia' estratte); qui c'e' solo la colla: credenziali dalla configurazione, rete fuori dal ciclo degli eventi, e la
cache dell'ultimo elenco, cosi' i filtri locali (giorni, formato) non ricaricano dal server come nella GUI."""
import threading
from typing import Callable, Dict, List, Optional

from core.services import library_actions as LA
from core.services import library_rows as LR
from core.services.library_scanner_client import LibraryScannerClient, call_api
from core.services.settings_service import SettingsService
from utils.path_map import parse_map, to_local, to_server
from utils.translations import tr


class LibraryManager:
    def __init__(self, bus, config, queue, client_factory: Optional[Callable] = None, api: Optional[Callable] = None):
        self.bus, self.config, self.queue = bus, config, queue
        # Le predefinite si risolvono ORA, non come argomento di default (i test sostituiscono i simboli del modulo prima di costruire).
        self._client_factory = client_factory or (lambda url, key: LibraryScannerClient(url, key))
        self._api = api or call_api
        self.loaded = False                       # come la GUI: si notifica il server solo dopo il primo caricamento dell'elenco
        self.batch_active = False                 # impostato dall'OCR in batch (5b): durante un batch non si ricarica a ogni file
        self._lock = threading.Lock()
        self._videos: List[dict] = []
        self._stats: Optional[dict] = None
        self._connected = False
        self._error = ''
        self._notifiers: List[threading.Thread] = []

    # ------------------------------------------------------------------------------------------------------------- configurazione
    def _creds(self):
        return LA.clean_credentials(self.config.get('library_scanner_url', ''), self.config.get('library_scanner_api_key', ''))

    def _rules(self):
        return parse_map(self.config.get('library_scanner_path_map', ''))

    def card_state(self) -> dict:
        return {'enabled': bool(self.config.get('library_scanner_enabled', True)), 'open': SettingsService(self.config).scanner_card_open()}

    def set_card_open(self, opened: bool) -> None:
        SettingsService(self.config).set_scanner_card_open(bool(opened))

    # ------------------------------------------------------------------------------------------------------------------ elenco
    def fetch(self, search: str, media_type: str, fmt: Optional[str], min_days: int) -> dict:
        """Carica statistiche ed elenco dal server (bloccante: chiamare fuori dal ciclo degli eventi). Il formato ASS/SSA usa un altro
        endpoint, gia' scelto dal client."""
        self.loaded = True
        url = (self.config.get('library_scanner_url') or '')
        key = (self.config.get('library_scanner_api_key') or '')
        if not url or not key:
            with self._lock:
                self._videos, self._stats, self._connected, self._error = [], None, False, 'config_missing'
            return self.view(min_days, fmt)
        try:
            client = self._client_factory(url, key)
            stats = client.stats()
            data = client.videos(search.strip(), media_type, fmt or '')
            with self._lock:
                self._stats, self._videos, self._connected, self._error = stats, data.get('videos', []), True, ''
        except Exception as e:
            with self._lock:
                self._connected, self._error = False, str(e)
        return self.view(min_days, fmt)

    def view(self, min_days: int, fmt: Optional[str]) -> dict:
        """L'ultimo elenco con le righe nascoste dai filtri giorni/formato (stessa regola della GUI) e i contatori."""
        queued = set(self.queue.queue.snapshot())
        rules = self._rules()
        with self._lock:
            videos, stats, connected, error = list(self._videos), self._stats, self._connected, self._error
        rows, visible = [], 0
        for v in videos:
            wp = v.get('windows_path', '')
            days = v.get('days_without_subs', 0)
            hidden = LR.is_row_hidden(days, min_days, fmt, v.get('bitmap_format'), bool(v.get('has_italian_convertible_subs', False)),
                                      bool(v.get('has_only_bitmap_subs', False)))
            visible += 0 if hidden else 1
            label, ocr_kind = LR.badge_label_kind(v.get('bitmap_format'))
            rows.append({'id': v.get('id'), 'filename': v.get('filename', ''), 'windows_path': wp, 'media_type': v.get('media_type', ''),
                         'days': days, 'days_class': LR.days_class(days), 'audio_ita': LR.detect_italian(v.get('filename', '')) == 'ita',
                         'badge': LR.badge_kind(v), 'badge_label': label, 'ocr_kind': ocr_kind,
                         'ass_done': v.get('conversion_status') == 'done', 'queued': to_local(wp, rules) in queued, 'hidden': hidden})
        text, without = LR.stats_text(stats) if stats is not None else ('', 0)
        return {'connected': connected, 'error': error, 'stats_text': text, 'without': without, 'visible': visible, 'rows': rows,
                'import_enabled': visible > 0, 'import_is_ass': fmt == LR.FORMAT_ASS}

    # ----------------------------------------------------------------------------------------------------------------- azioni
    def import_paths(self, paths: List[str], log: bool = False) -> int:
        """Aggiunge alla coda i percorsi del server (mappati sul computer), saltando file gia' in coda o in lavorazione."""
        planned = LA.plan_import(paths, self._rules(), lambda p: self.queue.queue.contains(p), self.queue.is_active)
        added = self.queue.add(planned)
        if added and log:
            self.queue.log_message(tr('files_imported_log').format(added=len(added)))
        return len(added)

    def convert_ass(self, video_ids: List[int]) -> dict:
        url, key = self._creds()
        if not url or not key:
            return {'level': 'warning', 'title_key': 'ls_ass_title', 'message': tr('ls_not_configured')}
        endpoint, body = LA.ass_start_request(url, video_ids)
        status, text = self._api('post', endpoint, key, json_body=body, timeout=10)
        reply = LA.ass_reply(status, text, video_ids)
        self.queue.log_message(reply.log)
        return {'level': reply.level, 'title_key': 'ls_ass_title', 'message': reply.message}

    def notify_subtitle_created(self, video_path: str) -> None:
        """Chiamato quando la coda completa un file: avvisa il server (in un thread) e fa ricaricare l'elenco alla pagina."""
        if not self.loaded:
            return
        url, key = self._creds()
        if not url or not key:
            return

        def work():
            ok = self._client_factory(url, key).notify_subtitle(to_server(str(video_path), self._rules()))
            if ok and not self.batch_active:
                self.bus.publish('library_changed', {})
        t = threading.Thread(target=work, name='tpweb-library-notify', daemon=True)
        self._notifiers = [x for x in self._notifiers if x.is_alive()] + [t]
        t.start()

    def join(self, timeout: Optional[float] = None) -> None:
        for t in list(self._notifiers):
            t.join(timeout)
