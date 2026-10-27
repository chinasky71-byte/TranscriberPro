# -*- coding: utf-8 -*-
"""GlossaryRunEngine: un run del "Glossario per show", senza Qt e senza GUI.

Trasposizione fedele di `GlossaryBuilderWorker.run()` / `cancel()` (gui/glossary_worker.py): lancia core/glossary_builder_cli.py con
l'interprete del venv dedicato venv_glossary/ (mai torch/simalign/llama-cpp nel processo chiamante, stesso principio di isolamento di
core/gender_corrector.py), legge le righe JSON su stdout e le trasforma nei ganci del `GlossaryListener`; stderr va solo al logger
(rumore di libreria), mai a schermo. I ganci sono chiamati nel thread che esegue `run()`.
"""
import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

from utils.platform_compat import kill_tree as _default_kill_tree, venv_python

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_GLOSSARY_PYTHON = venv_python(PROJECT_ROOT / 'venv_glossary')
CLI_SCRIPT = PROJECT_ROOT / 'core' / 'glossary_builder_cli.py'


def venv_glossary_available() -> bool:
    return VENV_GLOSSARY_PYTHON.exists() and CLI_SCRIPT.exists()


class GlossaryListener:
    """Ganci del run. Tutti facoltativi."""

    def on_gate(self, gate: dict) -> None: ...

    def on_progress(self, phase: str, done: int, total: int, msg: str) -> None: ...

    def on_log(self, msg: str) -> None: ...

    def on_finished_ok(self, report_path: str) -> None: ...

    def on_failed(self, message: str) -> None: ...


class GlossaryRunEngine:
    """Un run = un show. `args_payload` e' il dict scritto su args.json.

    `locate`: callable -> (python del venv, script del CLI, radice del progetto), letta a ogni run; `available`: callable -> bool;
    `kill_tree`: callable(pid, wait=...). Sono sostituibili (i test li puntano a un finto CLI)."""

    def __init__(self, args_payload: dict, work_dir: Path, listener: Optional[GlossaryListener] = None, *,
                 locate: Callable[[], Tuple[Path, Path, Path]] = lambda: (VENV_GLOSSARY_PYTHON, CLI_SCRIPT, PROJECT_ROOT),
                 available: Callable[[], bool] = venv_glossary_available,
                 kill_tree: Callable = _default_kill_tree):
        self._args_payload = args_payload
        self._work_dir = work_dir
        self.listener = listener or GlossaryListener()
        self._locate = locate
        self._available = available
        self._kill_tree = kill_tree
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False

    def cancel(self):
        """Chiamato dal thread GUI: deve tornare SUBITO. Solo `terminate()`
        (non bloccante) — il reap del processo lo fa gia' `run()` nel suo
        `finally` (`proc.wait()`), che gira sul thread del worker. Un
        `proc.wait()` anche qui andrebbe in race con quello, e bloccherebbe
        la GUI fino a 5s (bug reale misurato in revisione)."""
        self._cancelled = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self._kill_qwen_gpu_subprocess()

    def _kill_qwen_gpu_subprocess(self):
        """`terminate()` sopra colpisce solo il processo venv_glossary
        diretto: su Windows non propaga ai discendenti. Se il canale Qwen
        (glossary_qwen_bridge.py) aveva gia' lanciato il subprocess GPU sul
        venv principale, quello resterebbe orfano con ~9GB di modello
        ancora in VRAM — esattamente la contesa che il blocco 'pipeline in
        corso' vuole evitare. kill_tree uccide l'intero albero; senza attesa
        (wait=0) per restare non bloccante come `cancel()`."""
        pid_path = self._work_dir / "glossary_qwen_gpu_pid.txt"
        try:
            pid_text = pid_path.read_text(encoding='utf-8').strip()
        except Exception:
            return
        try:
            self._kill_tree(int(pid_text), wait=0)
        except Exception as e:
            logger.warning(f"Kill subprocess Qwen GPU fallito: {e}")

    def _cleanup_work_dir(self):
        """Un run annullato non deve lasciare args.json/temp che poi
        confondano il run successivo o restino orfani su disco."""
        for filename in ("glossary_builder_args.json",
                          "glossary_qwen_gpu_request.json",
                          "glossary_qwen_gpu_result.json",
                          "glossary_qwen_gpu_pid.txt"):
            try:
                path = self._work_dir / filename
                if path.exists():
                    path.unlink()
            except Exception as e:
                logger.warning(f"Cleanup work_dir dopo cancel fallito ({filename}): {e}")

    def run(self):
        if not self._available():
            self.listener.on_failed(
                "venv_glossary non trovato. Crea il venv dedicato prima "
                "di usare questo strumento (vedi glossary_engine/glossary_align.py).")
            return

        python, script, project_root = self._locate()
        self._work_dir.mkdir(parents=True, exist_ok=True)
        args_path = self._work_dir / "glossary_builder_args.json"
        try:
            args_path.write_text(
                json.dumps(self._args_payload, ensure_ascii=False),
                encoding='utf-8')
        except Exception as e:
            self.listener.on_failed(f"Impossibile scrivere args.json: {e}")
            return

        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'

        try:
            self._proc = subprocess.Popen(
                [str(python), str(script), str(args_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(project_root), env=env, text=True,
                encoding='utf-8', errors='replace', bufsize=1,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except Exception as e:
            self.listener.on_failed(f"Avvio subprocess fallito: {e}")
            return

        def _drain_stderr(stream):
            try:
                for eline in stream:
                    eline = eline.rstrip()
                    if eline:
                        logger.info(f"[glossary-stderr] {eline}")
            except Exception:
                pass

        threading.Thread(target=_drain_stderr, args=(self._proc.stderr,),
                          daemon=True).start()

        report_path = None
        error_msg = None
        try:
            for line in self._proc.stdout:
                if self._cancelled:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    logger.info(f"[glossary] riga non-JSON ignorata: {line}")
                    continue
                ev = event.get('ev')
                if ev == 'gate':
                    self.listener.on_gate(event)
                elif ev == 'progress':
                    self.listener.on_progress(event.get('phase', ''), event.get('done', 0),
                                        event.get('total', 0), event.get('msg', ''))
                elif ev == 'log':
                    self.listener.on_log(event.get('msg', ''))
                elif ev == 'done':
                    report_path = event.get('report')
                elif ev == 'error':
                    error_msg = event.get('msg', 'errore sconosciuto')
        finally:
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc.wait()

        if self._cancelled:
            self._cleanup_work_dir()
            self.listener.on_failed("Annullato dall'utente")
            return
        if error_msg:
            self.listener.on_failed(error_msg)
            return
        if self._proc.returncode != 0 or not report_path:
            self.listener.on_failed(
                f"Il processo e' terminato con codice {self._proc.returncode} "
                f"senza produrre un report")
            return
        self.listener.on_finished_ok(report_path)
