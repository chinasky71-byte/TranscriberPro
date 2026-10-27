# -*- coding: utf-8 -*-
"""
Worker QThread per il subprocess "Glossario per show".
File: gui/glossary_worker.py

Adattatore Qt sul motore senza Qt `core/jobs/glossary_run.py` (`GlossaryRunEngine`): resta un QThread con gli stessi 5 segnali, emessi
dal thread del worker nello stesso ordine di prima. Il lancio di core/glossary_builder_cli.py nel venv dedicato venv_glossary/, la
lettura delle righe JSON, l'annullamento e la pulizia dei file temporanei vivono nel motore.
"""
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from core.jobs import glossary_run as _run
from core.jobs.glossary_run import GlossaryListener, GlossaryRunEngine
from utils.platform_compat import kill_tree, venv_python  # noqa: F401  (nomi storici del modulo)

PROJECT_ROOT = _run.PROJECT_ROOT
VENV_GLOSSARY_PYTHON = _run.VENV_GLOSSARY_PYTHON
CLI_SCRIPT = _run.CLI_SCRIPT


def venv_glossary_available() -> bool:
    return VENV_GLOSSARY_PYTHON.exists() and CLI_SCRIPT.exists()


class _SignalListener(GlossaryListener):
    def __init__(self, worker: 'GlossaryBuilderWorker'):
        self._w = worker

    def on_gate(self, gate):
        self._w.gate.emit(gate)

    def on_progress(self, phase, done, total, msg):
        self._w.progress.emit(phase, done, total, msg)

    def on_log(self, msg):
        self._w.log_line.emit(msg)

    def on_finished_ok(self, report_path):
        self._w.finished_ok.emit(report_path)

    def on_failed(self, message):
        self._w.failed.emit(message)


class GlossaryBuilderWorker(QThread):
    """Un run = un show. `args_payload` e' il dict scritto su args.json."""

    gate = pyqtSignal(dict)            # esito gate show
    progress = pyqtSignal(str, int, int, str)  # phase, done, total, msg
    log_line = pyqtSignal(str)
    finished_ok = pyqtSignal(str)      # path del report JSON
    failed = pyqtSignal(str)           # messaggio errore

    def __init__(self, args_payload: dict, work_dir: Path, parent=None):
        super().__init__(parent)
        # Percorsi, disponibilita' del venv e kill_tree si leggono da questo modulo a ogni run/cancel (sostituibili nei test).
        self._engine = GlossaryRunEngine(
            args_payload, work_dir, _SignalListener(self),
            locate=lambda: (VENV_GLOSSARY_PYTHON, CLI_SCRIPT, PROJECT_ROOT),
            available=lambda: venv_glossary_available(),
            kill_tree=lambda pid, wait=None: kill_tree(pid, wait=wait))

    @property
    def _cancelled(self) -> bool:
        return self._engine._cancelled

    def cancel(self):
        """Chiamato dal thread GUI: deve tornare SUBITO (vedi GlossaryRunEngine.cancel)."""
        self._engine.cancel()

    def run(self):
        self._engine.run()
