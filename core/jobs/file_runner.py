# -*- coding: utf-8 -*-
"""FileRunner: l'UNICA copia della logica che elabora un file in un sottoprocesso isolato (`core.pipeline_cli`).

Prima era duplicata in gui/workers.py (ProcessingWorker) e in core/queue_runner.py (run_one): cartella IPC con args.json e
result.json, ambiente del figlio, flag di creazione, lettura di stdout riga per riga con eventi strutturati e percentuale,
lettura dell'esito, pulizia, uccisione dell'albero dei processi. Nessun Qt, nessun import di `gui`.

Le differenze di comportamento fra la GUI e la coda headless NON sono nel motore ma nei ganci (`FileHooks`) e in pochi
parametri dichiarati (vedi `run`). La lettura della pipe avviene in un thread che mette le righe in una coda; le righe si
elaborano nel thread CHIAMANTE (per la GUI: lo stesso thread del QThread di prima, quindi stesso ordine e stesso thread di
emissione dei segnali) e l'attesa e' interrompibile da Ctrl+C anche su Windows (la lettura diretta dalla pipe non lo e').
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from utils import events as _events

_ROOT = Path(__file__).resolve().parent.parent.parent

# Righe che alcune librerie scrivono su STDOUT bypassando il logging (torch.hub: download dei modelli): mai a schermo.
STDOUT_NOISE = ('Downloading:', 'Using cache found in')
POLL_S = 0.2


class FileHooks:
    """Ganci verso chi usa il runner. Tutti facoltativi. Sono chiamati nel thread che esegue `run()`, tranne `on_stderr`
    (thread dedicato a drenare stderr)."""

    def on_spawn(self, proc: subprocess.Popen) -> None:
        """Il figlio e' partito (serve a chi vuole poterlo fermare da un altro thread)."""

    def on_raw(self, line: str) -> None:
        """OGNI riga di stdout, con il suo a capo, prima di qualunque filtro (log completo del file della coda headless)."""

    def on_text(self, line: str) -> None:
        """Riga di testo per l'utente: senza a capo finale, non vuota, non rumore, non evento."""

    def on_noise(self, line: str) -> None:
        """Riga di rumore delle librerie (STDOUT_NOISE): va solo nel log dell'applicazione."""

    def on_event(self, kind: str, fields: dict) -> None:
        """Evento strutturato valido (utils/events.py), gia' passato alla percentuale."""

    def on_progress(self, value: int, phase: str, changed: bool) -> None:
        """Dopo OGNI riga elaborata: percentuale e fase correnti; `changed` = la percentuale e' appena aumentata."""

    def on_stderr(self, line: str) -> None:
        """Riga di stderr del figlio (senza a capo finale)."""


@dataclass
class FileResult:
    success: bool                       # esito: result.json se leggibile, altrimenti exit code == 0
    cancelled: bool = False             # fermato da cancel()/is_cancelled
    returncode: Optional[int] = None
    output: Optional[str] = None        # last_output_path di result.json (None se assente/illeggibile)
    duration: float = 0.0               # secondi dal lancio del figlio alla sua fine
    spawn_error: Optional[str] = None   # il figlio non e' partito (solo con raise_on_spawn_error=False)


def kill_tree(proc: subprocess.Popen, wait: float = 5.0) -> None:
    """Uccide il processo e TUTTI i discendenti (ffmpeg, gender_corrector_cli...). Su Windows terminate() sul figlio Python non
    arriva ai nipoti: serve uccidere l'albero con psutil. Senza psutil: terminate/kill del solo figlio."""
    try:
        import psutil
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        parent.kill()
        try:
            proc.wait(timeout=wait)
        except Exception:
            pass
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=wait)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def child_env() -> dict:
    """Ambiente del figlio. NIENTE PYTHONUTF8 / `-X utf8`: attiverebbe la UTF-8 mode globale cambiando la codifica di default
    delle subprocess annidate (ffmpeg, demucs, pyannote) da cp1252 a UTF-8 strict (UnicodeDecodeError su metadati cp1252)."""
    env = os.environ.copy()
    # RDNA2: HSA_OVERRIDE_GFX_VERSION=10.3.0 solo per il figlio, solo se rilevata e se l'utente non l'ha gia' impostata
    from utils.gpu_detect import apply_subprocess_env
    apply_subprocess_env(env)
    env['PYTHONIOENCODING'] = 'utf-8'    # gli std stream del figlio in UTF-8 (emoji, accenti)
    env['TP_SUBPROCESS'] = '1'           # nel figlio: niente console handler dei logger
    env['TQDM_DISABLE'] = '1'            # niente barre di progresso (download modelli)
    env['TP_EVENTS'] = '1'               # eventi strutturati (utils/events.py): il genitore li toglie dal log
    return env


def creation_flags() -> int:
    flags = 0
    if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP'):
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
        flags |= subprocess.CREATE_NO_WINDOW           # nessuna finestra console per il figlio
    return flags


class FileRunner:
    """Un'istanza per file. `cancel()` si puo' chiamare da un altro thread."""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = Path(project_root) if project_root else _ROOT
        self.proc: Optional[subprocess.Popen] = None
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Richiesta di arresto: segna e uccide l'albero del figlio in corso (se c'e')."""
        self._cancelled = True
        proc = self.proc
        if proc is not None:
            kill_tree(proc)

    def run(self, video_path: str, target_language: str, files_processed: int, *, progress,
            hooks: Optional[FileHooks] = None, overrides: Optional[dict] = None,
            is_cancelled: Optional[Callable[[], bool]] = None, ipc_prefix: str = 'tp_pipe_',
            feed_diag_progress: bool = False, converting_cleanup: str = 'cancelled',
            raise_on_spawn_error: bool = False) -> FileResult:
        """Elabora `video_path` e ritorna l'esito.

        progress             FileProgress del file (percentuale e fase); il chiamante lo crea con la lingua di destinazione.
        overrides            eccezioni per file da passare a pipeline_cli; None = la chiave "overrides" non viene scritta
                             in args.json (comportamento della coda headless di prima).
        is_cancelled         callable interrogato a ogni riga (la GUI passa il suo flag); in piu' vale cancel().
        feed_diag_progress   False: le righe [DIAG-RAM] ("N. Step" che NON e' un confine di passo) non muovono la barra
                             (GUI); True: la muovono (coda headless di prima).
        converting_cleanup   'cancelled' = si ripulisce <video>.converting solo se fermato (GUI); 'always' = sempre (headless).
        raise_on_spawn_error True: se il figlio non parte si rilancia l'eccezione originale (headless); False: esito con
                             spawn_error (GUI, che lo scrive nel log e passa al file dopo).
        """
        hooks = hooks or FileHooks()
        ipc_dir = Path(tempfile.mkdtemp(prefix=ipc_prefix))
        args_path = ipc_dir / 'args.json'
        result_path = ipc_dir / 'result.json'
        args = {'video_path': video_path, 'target_language': target_language}
        if overrides is not None:
            args['overrides'] = overrides
        args.update({'files_processed': files_processed, 'result_path': str(result_path)})
        args_path.write_text(json.dumps(args, ensure_ascii=False), encoding='utf-8')

        t0 = time.time()
        result = None
        try:
            try:
                proc = subprocess.Popen(
                    [sys.executable, '-m', 'core.pipeline_cli', str(args_path)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(self.project_root), env=child_env(),
                    text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=creation_flags())
            except Exception as exc:
                if raise_on_spawn_error:
                    raise
                result = FileResult(success=False, spawn_error=str(exc))
                return result
            self.proc = proc
            hooks.on_spawn(proc)
            result = self._stream(proc, video_path, progress, hooks, is_cancelled, feed_diag_progress, t0, result_path)
            return result
        finally:
            self.proc = None
            shutil.rmtree(ipc_dir, ignore_errors=True)
            if converting_cleanup == 'always' or (converting_cleanup == 'cancelled' and result is not None and result.cancelled):
                try:   # Stop o interruzione: un remux ffmpeg in corso lascia <video>.converting accanto al video
                    Path(str(video_path) + '.converting').unlink(missing_ok=True)
                except Exception:
                    pass

    # ------------------------------------------------------------------------------------------------------------------
    def _stream(self, proc, video_path, progress, hooks, is_cancelled, feed_diag_progress, t0, result_path) -> FileResult:
        def drain_stderr(stream):
            try:
                for eline in stream:
                    eline = eline.rstrip()
                    if eline:
                        hooks.on_stderr(eline)
            except Exception:
                pass

        lines: 'queue.Queue' = queue.Queue()

        def read_stdout(stream):
            try:
                for ln in stream:
                    lines.put(ln)
            except Exception:
                pass
            finally:
                lines.put(None)

        stderr_thread = threading.Thread(target=drain_stderr, args=(proc.stderr,), daemon=True)
        stdout_thread = threading.Thread(target=read_stdout, args=(proc.stdout,), daemon=True)
        stderr_thread.start()
        stdout_thread.start()

        def cancelled_now() -> bool:
            return self._cancelled or bool(is_cancelled and is_cancelled())

        return_code = 1
        try:
            while True:
                try:
                    raw = lines.get(timeout=POLL_S)
                except queue.Empty:
                    continue                         # attesa interrompibile da Ctrl+C
                if raw is None:
                    break
                hooks.on_raw(raw)
                if cancelled_now():
                    kill_tree(proc)
                    break
                line = raw.rstrip()
                if not line:
                    continue
                if line.lstrip().startswith(STDOUT_NOISE):
                    hooks.on_noise(line)
                    continue
                ev = _events.parse_line(line)
                changed = False
                if ev is not None:
                    # evento strutturato: non e' testo per l'utente, muove solo la barra del file
                    try:
                        pct = progress.feed_event(ev[0], ev[1]) if ev[0] else None
                    except Exception:
                        pct = None
                    changed = pct is not None
                    try:
                        hooks.on_progress(progress.value, progress.phase or '', changed)
                    except Exception:
                        pass
                    if ev[0]:                        # ordine storico della GUI: prima la barra, poi l'anteprima dei passi
                        try:
                            hooks.on_event(ev[0], ev[1])
                        except Exception:
                            pass
                    continue
                else:
                    hooks.on_text(line)
                    # le righe [DIAG-RAM] contengono "N. Step" ma NON sono confini di passo: la GUI le esclude dalla barra
                    if feed_diag_progress or '[DIAG-RAM]' not in line:
                        try:
                            pct = progress.feed(line)
                        except Exception:
                            pct = None               # mai far fallire la lettura del log per la barra
                        changed = pct is not None
                try:
                    hooks.on_progress(progress.value, progress.phase or '', changed)
                except Exception:
                    pass
            return_code = proc.wait()
        except BaseException:
            kill_tree(proc)
            raise
        finally:
            try:
                stderr_thread.join(timeout=5)
            except Exception:
                pass
            try:
                stdout_thread.join(timeout=5)
            except Exception:
                pass

        duration = time.time() - t0
        was_cancelled = cancelled_now()
        if was_cancelled:
            return FileResult(success=False, cancelled=True, returncode=return_code, duration=duration)
        success, output = (return_code == 0), None
        try:
            if result_path.exists():
                res = json.loads(result_path.read_text(encoding='utf-8'))
                success = bool(res.get('success', success))
                output = res.get('last_output_path')
        except Exception:
            pass
        return FileResult(success=success, returncode=return_code, output=output, duration=duration)
