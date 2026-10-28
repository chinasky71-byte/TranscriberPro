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


class ToolRuns:
    """I run degli strumenti di un server. `engines`: fabbriche di motori sostituibili nei test ({'glossary': callable})."""

    def __init__(self, bus, gate: ToolGate, config, engines: Optional[Dict[str, Callable]] = None, available: Optional[Dict[str, Callable]] = None):
        engines, available = engines or {}, available or {}
        self.glossary = GlossaryManager(bus, gate, config, engines.get('glossary'), available.get('glossary'))

    def state(self) -> dict:
        return {'glossary': self.glossary.state()}

    def shutdown(self) -> None:
        self.glossary.shutdown()
