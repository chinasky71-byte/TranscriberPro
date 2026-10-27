# -*- coding: utf-8 -*-
"""SyncBatchEngine: la coda multi-file del Subtitle Sync, senza Qt e senza GUI.

Trasposizione fedele di `SyncBatchWorker.run()` e `_run_one()` (gui/sync_batch_worker.py): scorre le coppie (video, SRT) in sequenza e
lancia per ciascuna `python -m core.sync_cli` (un subprocess per coppia): contesto CUDA vergine a ogni file e RAM/VRAM restituite
all'OS a fine coppia. Una coppia che fallisce si logga e si salta; la coda prosegue. Annullamento: si uccide l'albero del subprocess in
corso e si ferma la coda.

Chi lo usa passa un `SyncBatchListener` con i ganci che gli servono (la GUI li trasforma negli stessi 6 segnali Qt di prima). I ganci sono
chiamati nel thread che esegue `run()`.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

_STEP_PCT = {'1': 10, '2': 40, '3': 80, '4': 95}
_STEP_RE = re.compile(r'^\n?([1-4])\.\s')
_PCT_PREFIX = '[SYNC-PCT] '

DEFAULT_CLI_MODULE = 'core.sync_cli'


def kill_proc_tree(proc) -> None:
    """Uccide il subprocess e TUTTI i discendenti (ffmpeg, gender_corrector_cli): su Windows terminate() sul
    child Python non propaga ai nipoti."""
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
            proc.wait(timeout=5)
        except Exception:
            pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass



class SyncBatchListener:
    """Ganci della coda di sync. Tutti facoltativi, tutti chiamati nel thread che esegue `SyncBatchEngine.run()`."""

    def on_log(self, text: str) -> None: ...

    def on_pair_started(self, idx: int, video: str) -> None: ...

    def on_pair_progress(self, idx: int, pct: int) -> None: ...

    def on_pair_finished(self, idx: int, ok: bool, info: str) -> None:
        """info: percorso dell'output se ok, altrimenti il messaggio d'errore ("annullato" se fermata dall'utente)."""

    def on_batch_progress(self, done: int, total: int) -> None: ...

    def on_all_done(self, ok: int, fail: int, skipped: int) -> None: ...


class SyncBatchEngine:
    """pairs: lista di oggetti con .video, .srt, .output (core.sync_pairing.Pair gia' filtrata con runnable())."""

    def __init__(self, pairs: List, listener: Optional[SyncBatchListener] = None,
                 cli_module: Callable[[], str] = lambda: DEFAULT_CLI_MODULE):
        self._pairs = list(pairs)
        self.listener = listener or SyncBatchListener()
        self._cli_module = cli_module          # callable: il modulo si legge a ogni coppia (sostituibile nei test)
        self.is_cancelled = False
        self._proc = None

    def cancel(self) -> None:
        self.is_cancelled = True
        proc = self._proc
        if proc is not None:
            kill_proc_tree(proc)

    # ------------------------------------------------------------------ esecuzione
    def run(self) -> None:
        ok_n = fail_n = 0
        total = len(self._pairs)
        done = 0
        try:
            for idx, pair in enumerate(self._pairs):
                if self.is_cancelled:
                    break
                self.listener.on_pair_started(idx, str(pair.video))
                self.listener.on_log(f"\n=== Coda sync {idx + 1}/{total}: {Path(pair.video).name} ===")
                ok, info = self._run_one(idx, pair)
                if self.is_cancelled and not ok:
                    self.listener.on_pair_finished(idx, False, "annullato")
                    break
                self.listener.on_pair_finished(idx, ok, info)
                ok_n += bool(ok)
                fail_n += (not ok)
                done += 1
                self.listener.on_batch_progress(done, total)
                self._log_ram()
        except Exception as exc:                       # non deve mai lasciare il thread senza all_done
            logger.exception("SyncBatchWorker: eccezione non gestita")
            self.listener.on_log(f"ERRORE coda sync: {exc}")
        finally:
            self.listener.on_all_done(ok_n, fail_n, max(0, total - ok_n - fail_n))

    def _log_ram(self) -> None:
        try:
            import psutil
            self.listener.on_log(f"   RAM libera dopo la coppia: {psutil.virtual_memory().available / 1e9:.1f} GB")
        except Exception:
            pass

    def _run_one(self, idx: int, pair):
        ipc_dir = Path(tempfile.mkdtemp(prefix='tp_sync_'))
        args_path = ipc_dir / 'args.json'
        result_path = ipc_dir / 'result.json'
        args_path.write_text(json.dumps({
            'video_path': str(pair.video), 'external_srt_path': str(pair.srt),
            'output_path': str(pair.output) if pair.output else None, 'result_path': str(result_path),
        }, ensure_ascii=False), encoding='utf-8')

        project_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        # RDNA2: HSA_OVERRIDE_GFX_VERSION=10.3.0 solo per il figlio, solo se rilevata e se l'utente non l'ha gia' impostata
        from utils.gpu_detect import apply_subprocess_env
        apply_subprocess_env(env)
        env['PYTHONIOENCODING'] = 'utf-8'      # NON PYTHONUTF8 (vedi ProcessingWorker: cambia il default dei nipoti)
        env['TP_SUBPROCESS'] = '1'
        env['TQDM_DISABLE'] = '1'
        flags = 0
        if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP'):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            flags |= subprocess.CREATE_NO_WINDOW
        t0 = time.time()
        try:
            proc = subprocess.Popen(
                [sys.executable, '-m', self._cli_module(), str(args_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(project_root), env=env,
                text=True, encoding='utf-8', errors='replace', bufsize=1, creationflags=flags)
        except Exception as e:
            shutil.rmtree(ipc_dir, ignore_errors=True)
            return False, f"avvio del processo fallito: {e}"
        self._proc = proc

        def _drain(stream):
            try:
                for line in stream:
                    line = line.rstrip()
                    if line:
                        logger.info(f"[sync-child-stderr] {line}")
            except Exception:
                pass
        t_err = threading.Thread(target=_drain, args=(proc.stderr,), daemon=True)
        t_err.start()

        last_pct = 0
        rc = 1
        try:
            for line in proc.stdout:
                if self.is_cancelled:
                    kill_proc_tree(proc)
                    break
                line = line.rstrip('\r\n')
                if not line.strip():
                    continue
                if line.startswith(_PCT_PREFIX):
                    try:
                        last_pct = max(last_pct, int(line[len(_PCT_PREFIX):]))
                        self.listener.on_pair_progress(idx, last_pct)
                    except ValueError:
                        pass
                    continue
                self.listener.on_log(line)
                m = _STEP_RE.match(line)
                if m:
                    pct = _STEP_PCT.get(m.group(1), 0)
                    if pct > last_pct:
                        last_pct = pct
                        self.listener.on_pair_progress(idx, last_pct)
            rc = proc.wait()
        finally:
            self._proc = None
            try:
                t_err.join(timeout=5)
            except Exception:
                pass
            for _st in (proc.stdout, proc.stderr):
                try:
                    _st.close()
                except Exception:
                    pass

        ok, info = (rc == 0), ''
        try:
            if result_path.exists():
                res = json.loads(result_path.read_text(encoding='utf-8'))
                ok = bool(res.get('success', ok))
                info = res.get('output_path') or res.get('error') or ''
        except Exception:
            pass
        shutil.rmtree(ipc_dir, ignore_errors=True)
        if not ok and not info:
            info = f"processo terminato con codice {rc}" + (" (crash?)" if rc not in (0, 1) else "")
        self.listener.on_log(f"   {'OK' if ok else 'FALLITA'} in {time.time() - t0:.0f}s: {info}")
        if ok:
            self.listener.on_pair_progress(idx, 100)
        return ok, info
