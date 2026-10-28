# -*- coding: utf-8 -*-
"""Conversione OCR dei sottotitoli bitmap dal Library Scanner (fase 5b): un job alla volta, revisione mirata sul server, write-back,
batch e coda differita. Porta fedelmente la macchina a stati di `LibraryScannerWidget` (gui/library_scanner_widget.py): le decisioni sono
quelle di core/services/library_actions.py e ocr_review_service.py, il motore e' `OcrRunEngine`. La revisione tiene gli eventi (con le
immagini) SUL SERVER: la pagina riceve solo etichette e testi, e le immagini una alla volta.

Differenza voluta: finche' la revisione e' aperta il lavoro conta come «OCR in corso» (la GUI, col dialogo modale, non poteva avviare altro;
sul web serve dirlo esplicitamente per non far partire la coda o un altro OCR in mezzo)."""
import io
import re
import threading
from typing import Callable, List, Optional

from core.jobs.ocr_run import OcrListener, OcrRunEngine
from core.pgs_types import CFG_STRATEGY, DEFAULT_STRATEGY, events_to_srt
from core.services import library_actions as LA
from core.services import ocr_review_service as RS
from utils.path_map import parse_map, to_local
from utils.translations import tr


def base_name(path: str) -> str:
    """Nome del file da un percorso del server (di Windows o locale): sul computer del server `Path` non conosce i `\\`."""
    return re.split(r'[\\/]', path)[-1]


class OcrManager:
    def __init__(self, bus, config, queue, library, engine_factory: Optional[Callable] = None):
        self.bus, self.config, self.queue, self.library = bus, config, queue, library
        # Le predefinite si risolvono ORA, non come argomento di default (i test sostituiscono i simboli del modulo prima di costruire).
        self._engine_factory = engine_factory or (lambda *a, **k: OcrRunEngine(*a, **k))
        self._lock = threading.RLock()
        self._busy = False
        self._engine = None
        self._thread: Optional[threading.Thread] = None
        self.video_path = ''
        self.kind = 'pgs'
        self.name = ''
        self.strategy_used: Optional[str] = None
        self.progress_text = ''
        self.deferred: List[tuple] = []                    # (path, kind, force_auto)
        self.mode_override = {}                            # path -> 'review' | 'auto'
        self.batch_active = False
        self.batch_queue: List[tuple] = []
        self.batch_total = self.batch_ok = self.batch_fail = 0
        self.superpower_active = False
        self.review: Optional[dict] = None                 # {'events', 'language'}
        queue.finished_hooks.append(self.drain_deferred)

    # ------------------------------------------------------------------------------------------------------------------ stato
    def _rules(self):
        return parse_map(self.config.get('library_scanner_path_map', ''))

    def _sync_gate(self) -> None:
        self.queue.gate.ocr_running = self._busy or self.review is not None

    def state(self) -> dict:
        with self._lock:
            return {'busy': self._busy, 'progress_text': self.progress_text, 'name': self.name, 'review': self.review is not None,
                    'batch': {'active': self.batch_active, 'ok': self.batch_ok, 'fail': self.batch_fail, 'total': self.batch_total},
                    'superpower': self.superpower_active, 'deferred': [d[0] for d in self.deferred]}

    def _publish(self) -> None:
        self.bus.publish('ocr_state', self.state())

    def _message(self, kind: str, title: str, text: str) -> None:
        self.bus.publish('ocr_message', {'kind': kind, 'title': title, 'text': text})

    def _log(self, msg: str) -> None:
        self.queue.log_message(msg)

    def _set_progress_text(self, text: str) -> None:
        with self._lock:
            self.progress_text = text
        self._publish()

    # ------------------------------------------------------------------------------------------------------------------- avvio
    def is_deferred(self, path: str) -> bool:
        with self._lock:
            return any(t[0] == path for t in self.deferred)

    def set_deferred_mode(self, paths: List[str], mode: Optional[str]) -> List[str]:
        """Revisione per file dei job OCR ancora in attesa: mode 'review' | 'auto' | None (= predefinita). Restituisce i path cambiati."""
        changed = []
        with self._lock:
            for p in paths:
                if not self.is_deferred(p):
                    continue
                if mode in ('review', 'auto'):
                    self.mode_override[p] = mode
                else:
                    self.mode_override.pop(p, None)
                changed.append(p)
        label = {'review': tr('job_ov_ocr_targeted_short'), 'auto': tr('job_ov_ocr_auto_short')}.get(mode, '')
        for p in changed:
            self.queue.set_ocr_badge(p, label)
        if len(changed) < len(paths):
            self._log(tr('job_ov_skipped_log').format(n=len(paths) - len(changed)))
        self._publish()
        return changed

    def start(self, windows_path: str, kind: str, force_auto: bool = False, strategy_override: Optional[str] = None) -> str:
        """'started' | 'deferred' | 'busy' | 'ignored'. Con la coda al lavoro il job aspetta (evita OOM)."""
        if not windows_path:
            return 'ignored'
        with self.queue.gate.lock:                         # atomico rispetto all'avvio della coda
            with self._lock:
                if self.queue.is_processing:
                    self.deferred.append((windows_path, kind, force_auto))
                    kind_label = LA.job_kind_label(kind)
                    self.queue.add_ocr_job(windows_path, kind_label)
                    self.queue.set_ocr_status(windows_path, 'queued', 0)
                    self._log(tr('ls_ocr_queued_log').format(name=base_name(windows_path)))
                    self._publish()
                    return 'deferred'
                if self._busy or self.review is not None:
                    return 'busy'
                strategy = LA.resolve_strategy(force_auto, self.config.get(CFG_STRATEGY, DEFAULT_STRATEGY), strategy_override)
                self.strategy_used = strategy
                self.video_path, self.kind, self.name = windows_path, kind, base_name(windows_path)
                self._busy = True
                self._sync_gate()
        self._log(tr('ls_ocr_started_log').format(kind=kind, strategy=strategy, name=self.name))
        self.queue.add_ocr_job(windows_path, LA.job_kind_label(kind))
        self.queue.set_ocr_status(windows_path, 'processing', 0)
        self._launch('ocr', strategy)
        return 'started'

    def _launch(self, mode: str, strategy: str, srt_text: str = '', language: str = 'ita') -> None:
        listener = _Listener(self)
        engine = self._engine_factory(to_local(self.video_path, self._rules()), self.config, strategy, mode=mode, srt_text=srt_text,
                                      language=language, kind=self.kind, listener=listener)
        self._engine = engine
        self._thread = threading.Thread(target=engine.run, name='tpweb-ocr', daemon=True)
        self._publish()
        self._thread.start()

    def cancel(self) -> bool:
        engine = self._engine
        if not self._busy or engine is None:
            return False
        engine.cancel()
        return True

    def shutdown(self, timeout: float = 10.0) -> None:
        """Chiusura del server: annulla l'OCR in corso e lo attende."""
        self.cancel()
        t = self._thread
        if t is not None:
            t.join(timeout)

    def join(self, timeout: Optional[float] = None) -> None:
        t = self._thread
        if t is not None:
            t.join(timeout)

    # ----------------------------------------------------------------------------------------------- ganci del motore (thread del run)
    def _on_progress(self, percent: int, label: str) -> None:
        with self._lock:
            text = LA.progress_text(self.name, label, percent, self.batch_active, self.batch_ok, self.batch_fail, self.batch_total)
        self._set_progress_text(text)
        self.queue.set_ocr_status(self.video_path, 'processing', percent)

    def _on_events_ready(self, events, language: str) -> None:
        with self._lock:
            self.review = {'events': list(events), 'language': language}
            self._sync_gate()
        self._publish()

    def _on_auto_done(self, ok: bool) -> None:
        self.queue.set_ocr_status(self.video_path, 'completed' if ok else 'failed', 100)
        if ok:
            self.library.notify_subtitle_created(self.video_path)
        with self._lock:
            if self.batch_active:
                self.batch_ok += 1 if ok else 0
                self.batch_fail += 0 if ok else 1
                return
        self._set_progress_text('')
        if ok:
            self._message('info', tr('ocr_section_title'), tr('ls_conv_done').format(name=self.name))
            self.bus.publish('library_changed', {})
        else:
            self._message('warning', tr('ocr_section_title'), tr('ls_conv_failed').format(name=self.name))

    def _on_writeback_done(self, ok: bool) -> None:
        self._set_progress_text('')
        self.queue.set_ocr_status(self.video_path, 'completed' if ok else 'failed', 100)
        if ok:
            self.library.notify_subtitle_created(self.video_path)
            self._message('info', tr('ocr_section_title'), tr('ls_srt_written').format(name=self.name))
            self.bus.publish('library_changed', {})
        else:
            self._message('warning', tr('ocr_section_title'), tr('ls_srt_write_failed').format(name=self.name))

    def _on_unsupported(self, msg: str) -> None:
        self.queue.set_ocr_status(self.video_path, 'failed', 0)
        with self._lock:
            if self.batch_active:
                self.batch_fail += 1
                return
        self._message('info', tr('ocr_section_title'), f"{self.name}\n\n{msg}")

    def _on_lang_unsupported(self, msg: str) -> None:
        """Lingua senza traineddata: file saltato e marcato completato (in batch non e' un fallimento)."""
        self.queue.set_ocr_status(self.video_path, 'completed', 100)
        with self._lock:
            if self.batch_active:
                return
        self._set_progress_text('')
        self._message('info', tr('ocr_section_title'), tr('ls_lang_skipped').format(name=self.name, msg=msg))

    def _on_error(self, msg: str) -> None:
        self.queue.set_ocr_status(self.video_path, 'failed', 0)
        with self._lock:
            if self.batch_active:
                self.batch_fail += 1
                return
        self._message('warning', tr('ocr_section_title'), tr('ls_ocr_error').format(name=self.name, msg=msg))

    def _on_phase_finished(self) -> None:
        """Fine di una fase (OCR o write-back): libera il lavoro e, a revisione chiusa, passa al successivo."""
        with self.queue.gate.lock:
            with self._lock:
                self._busy = False
                self._engine = None
                self._sync_gate()
                review_open = self.review is not None
        self._publish()
        if review_open:
            return                                         # la persona sta rivedendo: si prosegue quando conferma o annulla
        if self.batch_active:
            self._batch_advance()
        else:
            self.drain_deferred()

    # ----------------------------------------------------------------------------------------------------------------- revisione
    def review_done(self, accept: bool) -> bool:
        with self._lock:
            rv = self.review
            if rv is None:
                return False
        if accept:
            srt = events_to_srt(rv['events'])
            self._log(tr('ls_srt_write_log').format(name=self.name))
            with self.queue.gate.lock:
                with self._lock:
                    self.review = None
                    self._busy = True
                    self._sync_gate()
            strategy = self.strategy_used or self.config.get(CFG_STRATEGY, DEFAULT_STRATEGY)
            self._launch('writeback', strategy, srt_text=srt, language=rv['language'])
        else:
            self._log(tr('ls_ocr_cancel_log').format(name=self.name))
            self._set_progress_text('')
            self.queue.set_ocr_status(self.video_path, 'failed', 0)
            with self.queue.gate.lock:
                with self._lock:
                    self.review = None
                    self._sync_gate()
            self._publish()
            self.drain_deferred()
        return True

    def _events(self):
        with self._lock:
            return self.review['events'] if self.review else None

    def review_list(self, only_flagged: bool) -> Optional[dict]:
        events = self._events()
        if events is None:
            return None
        first = RS.next_flagged_from(events, -1)
        if first is None and events:
            first = 0
        return {'items': [{'i': i, 'label': RS.item_label(events[i])} for i in RS.visible_indices(events, only_flagged)],
                'counter': RS.counter_text(events), 'first': first, 'total': len(events)}

    def review_event(self, i: int) -> Optional[dict]:
        events = self._events()
        if events is None or not 0 <= i < len(events):
            return None
        ev = events[i]
        return {'i': i, 'text': ev.text or '', 'info': RS.event_info(ev), 'has_image': ev.image is not None, 'can_prev': i > 0,
                'can_next': i < len(events) - 1, 'label': RS.item_label(ev), 'counter': RS.counter_text(events)}

    def review_text(self, i: int, text: str) -> Optional[dict]:
        events = self._events()
        if events is None or not 0 <= i < len(events):
            return None
        RS.apply_text(events[i], text)
        return {'label': RS.item_label(events[i]), 'counter': RS.counter_text(events)}

    def review_verify(self, i: int, text: str) -> Optional[dict]:
        events = self._events()
        if events is None or not 0 <= i < len(events):
            return None
        RS.mark_verified(events[i], text)
        return {'label': RS.item_label(events[i]), 'counter': RS.counter_text(events), 'next': RS.next_flagged_from(events, i)}

    def review_next_flagged(self, i: int) -> Optional[int]:
        events = self._events()
        return RS.next_flagged_from(events, i) if events is not None else None

    @staticmethod
    def italic(full: str, sel) -> dict:
        new_full, new_sel = RS.toggle_italic(full, tuple(sel) if sel else None)
        return {'text': new_full, 'sel': list(new_sel) if new_sel is not None else None}

    def review_image(self, i: int) -> Optional[bytes]:
        events = self._events()
        if events is None or not 0 <= i < len(events) or events[i].image is None:
            return None
        buf = io.BytesIO()
        events[i].image.convert('RGBA').save(buf, format='PNG')
        return buf.getvalue()

    # ------------------------------------------------------------------------------------------------------------------- batch
    def start_batch(self, items: List[tuple]) -> str:
        """items: (percorso del server, kind). Converte tutti in AUTOMATICO, in sequenza."""
        with self._lock:
            if self._busy or self.review is not None:
                return 'busy'
            if not items:
                return 'ignored'
            self.batch_active = True
            self.batch_queue = list(items)
            self.batch_total, self.batch_ok, self.batch_fail = len(items), 0, 0
        for path, kind in items:                          # pre-popola la coda con tutti i job (stato «in coda»)
            self.queue.add_ocr_job(path, LA.job_kind_label(kind))
        self._log(tr('ls_batch_started_log').format(n=self.batch_total))
        self._batch_advance()
        return 'started'

    def _batch_advance(self) -> None:
        with self._lock:
            if self.batch_queue:
                path, kind = self.batch_queue.pop(0)
                done = False
            else:
                done = True
        if not done:
            self.start(path, kind, force_auto=True)
            return
        with self._lock:
            self.batch_active = False
            was_superpower, self.superpower_active = self.superpower_active, False
            ok, fail, total = self.batch_ok, self.batch_fail, self.batch_total
        self._set_progress_text('')
        if was_superpower:
            self._log(tr('ls_sp_done_log'))
        if self.queue.shutdown_wanted():                  # «Spegni al termine»: prima del messaggio, che non blocca ma resta cio' che fa la GUI
            self.queue.schedule_shutdown(5)
        self._message('info', tr('ocr_section_title'), tr('ls_batch_done').format(ok=ok, fail=fail, total=total))
        self.bus.publish('library_changed', {})
        self.drain_deferred()

    def drain_deferred(self) -> None:
        """Avvia il prossimo job OCR dalla coda differita (a coda libera e nessun OCR in corso)."""
        with self._lock:
            if not self.deferred or self._busy or self.review is not None or self.queue.is_processing:
                return
            path, kind, force_auto = self.deferred.pop(0)
            override = self.mode_override.pop(path, None)
        self.start(path, kind, force_auto, override)


class _Listener(OcrListener):
    def __init__(self, mgr: OcrManager):
        self.m = mgr

    def on_log(self, text): self.m._log(text)

    def on_error(self, message): self.m._on_error(message)

    def on_finished(self): self.m._on_phase_finished()

    def on_events_ready(self, events, language): self.m._on_events_ready(events, language)

    def on_auto_done(self, ok): self.m._on_auto_done(ok)

    def on_writeback_done(self, ok): self.m._on_writeback_done(ok)

    def on_unsupported(self, message): self.m._on_unsupported(message)

    def on_lang_unsupported(self, message): self.m._on_lang_unsupported(message)

    def on_progress(self, percent, label): self.m._on_progress(percent, label)
