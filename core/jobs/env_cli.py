# -*- coding: utf-8 -*-
"""EnvCliRunner: esegue `core.env_check_cli <comando>` in un sottoprocesso e inoltra le righe di stato, senza Qt e senza GUI.

Trasposizione fedele di `EnvCliWorker.run()` (gui/translation_model_dialog.py). Il lavoro ML (download del modello LLM, test del
download di pyannote) gira in un processo separato che muore alla fine restituendo RAM/VRAM all'OS; chi chiama non importa mai torch o
transformers. Le righe di stderr (rumore di libreria) vanno solo al logger, mai a chi ascolta. I ganci sono chiamati nel thread che
esegue `run()`."""
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EnvCliListener:
    def on_line(self, line: str) -> None: ...

    def on_finished(self, exit_code: int) -> None:
        """exit code del CLI (0 = ok); 1 anche se il processo non e' partito."""


class EnvCliRunner:
    def __init__(self, command: str, listener: Optional[EnvCliListener] = None):
        self._command = command
        self.listener = listener or EnvCliListener()

    def run(self) -> None:
        L = self.listener
        root = PROJECT_ROOT
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['TP_SUBPROCESS'] = '1'
        env['TQDM_DISABLE'] = '1'
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            proc = subprocess.Popen(
                [sys.executable, '-m', 'core.env_check_cli', self._command],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(root), env=env, text=True, encoding='utf-8',
                errors='replace', bufsize=1, creationflags=flags)
        except Exception as e:
            L.on_line(f"❌ Avvio subprocess fallito: {e}")
            L.on_finished(1)
            return

        def _drain(stream):
            # Rumore librerie: solo nel file di log, mai in GUI
            try:
                for eline in stream:
                    eline = eline.rstrip()
                    if eline:
                        logger.debug(f"[env-cli-stderr] {eline}")
            except Exception:
                pass

        threading.Thread(target=_drain, args=(proc.stderr,),
                         daemon=True).start()
        for line in proc.stdout:
            line = line.strip()
            if line:
                L.on_line(line)
        L.on_finished(proc.wait())
