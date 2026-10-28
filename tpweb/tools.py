# -*- coding: utf-8 -*-
"""Strumenti con un run lungo (Glossario, Sincronizzazione): lo stato del run vive sul SERVER, non nella pagina. Ricaricare la scheda non
interrompe nulla e riaprendo il dialogo si vede lo stato attuale; chiudere il dialogo (come la GUI) annulla il run. Un run alla volta,
prenotato su `ToolGate` (mutua esclusione con la coda), e il flag lo libera il thread del run nel suo `finally`.

Gli eventi sul bus sono 'glossary_state' (tutto tranne il log), 'glossary_log' (una riga) e analoghi per la sincronizzazione; lo stato
completo e' anche nello snapshot di /api/state, cosi' una riconnessione dopo un buco di eventi ripristina il dialogo."""
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.jobs.glossary_run import GlossaryListener, GlossaryRunEngine, venv_glossary_available
from core.jobs.sync_batch import SyncBatchEngine, SyncBatchListener
from core.jobs.sync_single import SyncListener, SyncRunner
from core.services.progress_log import ProgressLog
from core.services.sync_batch_plan import SyncBatchPlan
from core.services import glossary_service as GS
from core.services.tool_gate import ToolGate

LOG_KEEP = 300                                  # righe di log che il server tiene per chi si collega a run avviato


class GlossaryManager:
    def __init__(self, bus, gate: ToolGate, config, engine_factory: Optional[Callable] = None,
                 available: Optional[Callable[[], bool]] = None):
        self.bus, self.gate, self.config = bus, gate, config
        # Le predefinite si risolvono ORA (non come argomento di default): i test sostituiscono i simboli del modulo prima di costruire.
        self._engine_factory = engine_factory or (lambda payload, work, listener: GlossaryRunEngine(payload, work, listener))
        self._available = available or venv_glossary_available
        self._lock = threading.Lock()
        self._engine = None
        self._thread: Optional[threading.Thread] = None
        self._reset_state()

    def _reset_state(self) -> None:
        self.status = 'idle'                     # idle | running | done | failed
        self.phase, self.done, self.total, self.msg = '', 0, 0, ''
        self.gate_info: Optional[dict] = None
        self.log: List[str] = []
        self.report: Optional[dict] = None
        self.error: Optional[dict] = None        # {'key': chiave o None, 'msg': testo}
        self.run_info: Optional[dict] = None     # {'show_dir', 'name', 'tmdb_id'}

    # ------------------------------------------------------------------------------------------------------------------ stato
    def state(self, with_log: bool = True) -> dict:
        with self._lock:
            s = {'status': self.status, 'venv_available': self._available(), 'phase': self.phase, 'done': self.done, 'total': self.total,
                 'msg': self.msg, 'gate': self.gate_info, 'report': self.report, 'error': self.error, 'run_info': self.run_info}
            if with_log:
                s['log'] = list(self.log)
            return s

    def _publish_state(self) -> None:
        self.bus.publish('glossary_state', self.state(with_log=False))

    # ----------------------------------------------------------------------------------------------------------------- comandi
    def start(self, show_dir: str, name_text: str, tmdb_id, candidates) -> Optional[str]:
        """None = avviato; altrimenti la chiave del messaggio del rifiuto."""
        reason = self.gate.begin_tool('glossary')
        if reason is not None:
            return reason
        try:
            req = GS.build_run_request(show_dir, name_text, tmdb_id, candidates, self.config)
            with self._lock:
                self._reset_state()
                self.status = 'running'
                self.run_info = {'show_dir': show_dir, 'name': req.args_payload['name'], 'tmdb_id': tmdb_id}
            listener = _Listener(self)
            engine = self._engine_factory(req.args_payload, req.work_dir, listener)
            self._engine = engine
            self._thread = threading.Thread(target=self._run, args=(engine,), name='tpweb-glossary', daemon=True)
        except Exception:
            self.gate.end_tool('glossary')
            with self._lock:
                self._reset_state()
            raise
        self._publish_state()
        self._thread.start()
        return None

    def _run(self, engine) -> None:
        try:
            engine.run()
        except Exception as e:                    # il motore non dovrebbe sollevare: se succede il run si chiude con un errore
            self._failed(f'{e}')
        finally:
            with self._lock:
                if self.status == 'running':      # il motore e' tornato senza dire come e' andata
                    self.status = 'failed'
                    self.error = self.error or {'key': None, 'msg': ''}
            self.gate.end_tool('glossary')
            self._publish_state()

    def cancel(self) -> bool:
        """Torna subito (il motore fa solo `terminate()`; il reap e' del thread del run)."""
        engine = self._engine
        if self.status != 'running' or engine is None:
            return False
        engine.cancel()
        return True

    def reset(self) -> bool:
        """Chiude il dialogo: azzera l'esito di un run finito. Rifiutato mentre il run e' in corso."""
        with self._lock:
            if self.status == 'running':
                return False
            self._reset_state()
        self._publish_state()
        return True

    def shutdown(self, timeout: float = 8.0) -> None:
        """Chiusura del server: annulla e attende il thread, cosi' non resta un sottoprocesso di venv_glossary orfano."""
        self.cancel()
        t = self._thread
        if t is not None:
            t.join(timeout)

    def join(self, timeout: Optional[float] = None) -> None:
        t = self._thread
        if t is not None:
            t.join(timeout)

    def save(self, rows, fallback_tmdb_id=None) -> dict:
        """Salva i termini approvati. I termini vengono SOLO dal report tenuto qui: una riga con un termine che il report non ha e' ignorata."""
        with self._lock:
            report = self.report
            run_tmdb = (self.run_info or {}).get('tmdb_id')
        if not report:
            return {'ok': False, 'reason': 'no_report'}
        tmdb_id = report.get('tmdb_id') or fallback_tmdb_id or run_tmdb
        if tmdb_id is None:
            return {'ok': False, 'reason': 'no_tmdb'}
        known = {c['term'] for c in report.get('candidates', [])}
        new_terms = GS.approved_terms([(r['term'], bool(r['approved']), r.get('rendering', '')) for r in rows if r['term'] in known])
        if not new_terms:
            return {'ok': False, 'reason': 'no_terms'}
        path = GS.save_terms(tmdb_id, new_terms, report.get('episodes_used', []))
        return {'ok': True, 'saved': len(new_terms), 'path': str(path)}

    # ------------------------------------------------------------------------------------------------- ganci del motore (thread del run)
    def _gate_event(self, gate: dict) -> None:
        with self._lock:
            self.gate_info = gate
        self._publish_state()

    def _progress(self, phase, done, total, msg) -> None:
        with self._lock:
            self.phase, self.done, self.total, self.msg = phase, done, total, msg
        self._publish_state()

    def _log(self, msg: str) -> None:
        with self._lock:
            self.log.append(msg)
            del self.log[:-LOG_KEEP]
        self.bus.publish('glossary_log', {'line': msg})

    def _failed(self, msg: str, key: Optional[str] = None) -> None:
        with self._lock:
            self.status, self.error = 'failed', {'key': key, 'msg': msg}
        self._publish_state()

    def _finished_ok(self, report_path: str) -> None:
        try:
            report = GS.load_report(report_path)
        except Exception as e:
            self._failed(str(e), key='glossary_report_unreadable')
            return
        for c in report.get('candidates', []):
            c['qwen_coverage_text'] = format(c.get('qwen_coverage', 0), '.0%')      # come l'etichetta della GUI (arrotondamento di Python)
        with self._lock:
            self.status, self.report = 'done', report
            self.gate_info = report.get('gate', self.gate_info)
        self._publish_state()


class _Listener(GlossaryListener):
    def __init__(self, mgr: GlossaryManager):
        self.mgr = mgr

    def on_gate(self, gate): self.mgr._gate_event(gate)

    def on_progress(self, phase, done, total, msg): self.mgr._progress(phase, done, total, msg)

    def on_log(self, msg): self.mgr._log(msg)

    def on_finished_ok(self, report_path): self.mgr._finished_ok(report_path)

    def on_failed(self, message): self.mgr._failed(message)


class SyncManager:
    """Sincronizzazione SRT (singola o coda di coppie). Lo stato del run e la tabella delle coppie vivono qui; un solo run alla volta."""

    def __init__(self, bus, gate: ToolGate, single_factory: Optional[Callable] = None, batch_factory: Optional[Callable] = None):
        self.bus, self.gate = bus, gate
        # Le predefinite si risolvono ORA (non come argomento di default): i test sostituiscono i simboli del modulo prima di costruire.
        self._single_factory = single_factory or (lambda video, srt, listener: SyncRunner(video, srt, None, listener))
        self._batch_factory = batch_factory or (lambda pairs, listener: SyncBatchEngine(pairs, listener))
        self._lock = threading.Lock()
        self._engine = None
        self._thread: Optional[threading.Thread] = None
        self.plan = SyncBatchPlan()
        self.dirs = {'video_dir': '', 'srt_dir': '', 'recursive': False}
        self._reset_state()

    def _reset_state(self) -> None:
        self.status = 'idle'                      # idle | running | finished
        self.mode: Optional[str] = None           # single | batch
        self.progress = 0
        self.log = ProgressLog()
        self.rows_rt: Dict[int, dict] = {}        # riga della tabella -> {'kind': ready|running|pct|ok|failed|skipped, 'pct': n}
        self.outcome: Optional[dict] = None       # {'kind': completed|error|cancelled|batch_done, ...}
        self.output_path: Optional[str] = None
        self.errors: List[str] = []
        self._batch_rows: Dict[int, int] = {}
        self._batch_done = self._batch_total = 0

    # ------------------------------------------------------------------------------------------------------------------ stato
    def plan_view(self) -> dict:
        with self._lock:
            pairs = self.plan.pairs
            summary = self.plan.refresh()
            files = [{'value': str(f), 'label': SyncBatchPlan.srt_label(f, self.dirs['srt_dir'])} for f in self.plan.srt_files]
            rows = [{'idx': i, 'checked': self.plan.is_checked(p), 'video_name': Path(p.video).name, 'video': str(p.video),
                     'srt': str(p.srt) if p.srt is not None else None, 'output': str(p.output) if p.output else '',
                     'state': SyncBatchPlan.state_of(p)} for i, p in enumerate(pairs)]
            return {'rows': rows, 'srt_files': files, 'runnable': len(self.plan.runnable()),
                    'summary': {'ready': summary.ready, 'check': summary.check, 'nosrt': summary.nosrt, 'left': summary.left}, 'dirs': dict(self.dirs)}

    def state(self, with_log: bool = True) -> dict:
        view = self.plan_view()
        with self._lock:
            s = {'status': self.status, 'mode': self.mode, 'progress': self.progress, 'rows_rt': {str(k): v for k, v in self.rows_rt.items()},
                 'outcome': self.outcome, 'output_path': self.output_path, 'errors': list(self.errors), 'plan': view}
            if with_log:
                s['log'] = list(self.log.lines)
            return s

    def _publish_state(self) -> None:
        self.bus.publish('sync_state', self.state(with_log=False))

    def _log(self, msg: str) -> None:
        with self._lock:
            op = self.log.append(msg)
        self.bus.publish('sync_log', op)

    # ------------------------------------------------------------------------------------------------------------------- piano
    def scan(self, video_dir: str, srt_dir: str, recursive: bool) -> bool:
        with self._lock:
            if self.status == 'running':
                return False
            ok = self.plan.scan(video_dir, srt_dir, recursive)
            if ok:
                self.dirs = {'video_dir': video_dir, 'srt_dir': srt_dir, 'recursive': recursive}
        self._publish_state()
        return ok

    def choose_srt(self, row: int, value: Optional[str]) -> bool:
        with self._lock:
            if self.status == 'running' or not 0 <= row < len(self.plan.pairs):
                return False
            self.plan.choose_srt(row, value)
        self._publish_state()
        return True

    def set_include(self, row: int, include: bool) -> bool:
        with self._lock:
            if self.status == 'running' or not 0 <= row < len(self.plan.pairs):
                return False
            self.plan.set_include(row, include)
        self._publish_state()
        return True

    # ----------------------------------------------------------------------------------------------------------------- comandi
    def _begin(self, mode: str) -> Optional[str]:
        reason = self.gate.begin_tool('sync')
        if reason is not None:
            return reason
        with self._lock:
            self._reset_state()
            self.status, self.mode = 'running', mode
        return None

    def start_single(self, video: str, srt: str) -> Optional[str]:
        reason = self._begin('single')
        if reason is not None:
            return reason
        try:
            engine = self._single_factory(video, srt, _SingleListener(self))
            self._engine = engine
            self._thread = threading.Thread(target=self._run, args=(engine,), name='tpweb-sync', daemon=True)
        except Exception:
            self._abort_start()
            raise
        self._publish_state()
        self._thread.start()
        return None

    def start_batch(self) -> Optional[str]:
        """None = avviata; 'nothing' (niente da eseguire, senza prenotare nulla) o la chiave del rifiuto."""
        with self._lock:
            run = self.plan.runnable()
        if not run:
            return 'nothing'
        reason = self._begin('batch')
        if reason is not None:
            return reason
        try:
            with self._lock:
                self._batch_total = len(run)
                self._batch_rows = {i: self.plan.pairs.index(p) for i, p in enumerate(run)}
                self.rows_rt = {r: ({'kind': 'ready'} if self.plan.pairs[r] in run else {'kind': ''}) for r in range(len(self.plan.pairs))}
            engine = self._batch_factory(run, _BatchListener(self))
            self._engine = engine
            self._thread = threading.Thread(target=self._run, args=(engine,), name='tpweb-sync', daemon=True)
        except Exception:
            self._abort_start()
            raise
        self._publish_state()
        self._thread.start()
        return None

    def _abort_start(self) -> None:
        self.gate.end_tool('sync')
        with self._lock:
            self._reset_state()

    def _run(self, engine) -> None:
        try:
            engine.run()
        except Exception as e:
            with self._lock:
                self.errors.append(str(e))
        finally:
            with self._lock:
                self.status = 'finished'
                if self.outcome is None:
                    self.outcome = {'kind': 'error' if self.errors else 'cancelled'}
            self.gate.end_tool('sync')
            self._publish_state()

    def cancel(self) -> bool:
        """Torna subito: il motore singolo ferma il sincronizzatore, quello in coda uccide l'albero del sottoprocesso."""
        engine = self._engine
        if self.status != 'running' or engine is None:
            return False
        from utils.translations import tr
        self._log(tr('sync_cancelling'))
        engine.cancel()
        return True

    def reset(self) -> bool:
        """Chiude il dialogo: azzera l'esito e la tabella. Rifiutato col run in corso."""
        with self._lock:
            if self.status == 'running':
                return False
            self._reset_state()
            self.plan = SyncBatchPlan()
            self.dirs = {'video_dir': '', 'srt_dir': '', 'recursive': False}
        self._publish_state()
        return True

    def shutdown(self, timeout: float = 35.0) -> None:
        """Una inferenza Qwen puo' durare ~55 s: si attende il thread (come la GUI, fino a 30 s) perche' non resti VRAM occupata."""
        self.cancel()
        t = self._thread
        if t is not None:
            t.join(timeout)

    def join(self, timeout: Optional[float] = None) -> None:
        t = self._thread
        if t is not None:
            t.join(timeout)

    # -------------------------------------------------------------------------------------------- ganci dei motori (thread del run)
    def _set_progress(self, pct: int) -> None:
        with self._lock:
            self.progress = pct
        self._publish_state()


class _SingleListener(SyncListener):
    def __init__(self, mgr: SyncManager):
        self.m = mgr

    def on_log(self, text): self.m._log(text)

    def on_progress(self, pct): self.m._set_progress(pct)

    def on_output_ready(self, output_path):
        with self.m._lock:
            self.m.output_path = output_path

    def on_completed(self, video):
        with self.m._lock:
            self.m.progress = 100
            self.m.outcome = {'kind': 'completed', 'video': video}

    def on_error(self, message):
        with self.m._lock:
            self.m.errors.append(message)
            self.m.outcome = {'kind': 'error'}


class _BatchListener(SyncBatchListener):
    def __init__(self, mgr: SyncManager):
        self.m = mgr

    def on_log(self, text): self.m._log(text)

    def on_pair_started(self, idx, video):
        with self.m._lock:
            self.m.rows_rt[self.m._batch_rows[idx]] = {'kind': 'running'}
        self.m._publish_state()

    def on_pair_progress(self, idx, pct):
        with self.m._lock:
            m = self.m
            m.rows_rt[m._batch_rows[idx]] = {'kind': 'pct', 'pct': pct}
            if m._batch_total:
                m.progress = int((m._batch_done + pct / 100.0) / m._batch_total * 100)
        self.m._publish_state()

    def on_pair_finished(self, idx, ok, info):
        with self.m._lock:
            m = self.m
            m._batch_done += 1
            m.rows_rt[m._batch_rows[idx]] = {'kind': 'ok' if ok else 'failed'}
            if m._batch_total:
                m.progress = int(m._batch_done / m._batch_total * 100)
        self.m._publish_state()

    def on_all_done(self, ok, fail, skipped):
        from utils.translations import tr
        self.m._log('\n' + tr('sync_batch_done').format(ok=ok, fail=fail, skipped=skipped))      # come il dialogo: il riepilogo chiude il log
        with self.m._lock:
            m = self.m
            for r in m._batch_rows.values():
                if m.rows_rt.get(r, {}).get('kind') in ('', 'ready'):
                    m.rows_rt[r] = {'kind': 'skipped'}
            m.outcome = {'kind': 'batch_done', 'ok': ok, 'fail': fail, 'skipped': skipped}


class ToolRuns:
    """I run degli strumenti di un server. `engines`: fabbriche di motori sostituibili nei test ({'glossary': callable})."""

    def __init__(self, bus, gate: ToolGate, config, engines: Optional[Dict[str, Callable]] = None, available: Optional[Dict[str, Callable]] = None):
        engines, available = engines or {}, available or {}
        self.glossary = GlossaryManager(bus, gate, config, engines.get('glossary'), available.get('glossary'))
        self.sync = SyncManager(bus, gate, engines.get('sync_single'), engines.get('sync_batch'))

    def state(self) -> dict:
        return {'glossary': self.glossary.state(), 'sync': self.sync.state()}

    def shutdown(self) -> None:
        self.glossary.shutdown()
        self.sync.shutdown()
