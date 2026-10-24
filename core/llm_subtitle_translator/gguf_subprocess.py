# -*- coding: utf-8 -*-
"""Motore GGUF eseguito in un SOTTOPROCESSO pulito (vedi gguf_worker.py per il perche').

`GGUFSubprocessEngine` ha la stessa interfaccia di `GGUFEngine` (spec, mt_messages, generate, load, unload, log): per
`LLMSubtitleTranslator` e per la pipeline non cambia nulla. Il modello resta caricato nel processo di lavoro tra un file e
l'altro della coda; `unload()` lo chiude (e libera la VRAM).

Robustezza: ogni richiesta ha un id e le risposte con id diverso (arretrate) si scartano; le righe che non sono eventi JSON
(rumore sul canale) si ignorano; la lettura passa da un thread e ha un tempo massimo; `unload()` durante un `generate()`
(annullo dalla GUI) chiude il processo invece di aspettare; dopo una morte del worker si riprova UNA volta a riavviarlo.
"""
from __future__ import annotations

import itertools
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from utils.logger import setup_logger
from utils.platform_compat import no_window_flags
from utils.translations import get_translations, tr

from .engine import DEFAULT_MODEL_KEY
from .gguf_engine import EXPECTED_ARCH, GGUFEngine, UnknownLanguageError

logger = setup_logger(__name__)

WORKER_SCRIPT = Path(__file__).resolve().parent / 'gguf_worker.py'
# Tempi massimi, larghi apposta: servono solo a non bloccare per sempre la coda se il worker si pianta (driver, decode).
# Un blocco di <= n_parallel righe si genera in secondi; il caricamento del 12B da disco lento in minuti.
LOAD_TIMEOUT_S = 900
GENERATE_TIMEOUT_S = 600
STOP_TIMEOUT_S = 15
UNLOAD_WAIT_S = 3          # attesa di un generate() in corso prima di chiudere il worker con la forza
MAX_RESTARTS = 1           # riavvii dopo la morte del worker, per serie di fallimenti consecutivi


class GGUFSubprocessEngine(GGUFEngine):

    def __init__(self, gguf_path: str, quant: str, model_key: str = DEFAULT_MODEL_KEY,
                 log_callback: Optional[Callable] = None, n_parallel: int = 4, ctx_per_seq: int = 512,
                 n_gpu_layers: int = -1, expected_arch: Optional[str] = EXPECTED_ARCH):
        super().__init__(gguf_path, quant, model_key, log_callback, n_parallel, ctx_per_seq, n_gpu_layers, expected_arch)
        self._proc: Optional[subprocess.Popen] = None
        self._stderr = None
        self._lines: Optional[queue.Queue] = None
        self._ids = itertools.count(1)
        self._failures = 0          # morti consecutive del worker senza un generate riuscito in mezzo
        self._cancelled = False     # chiusura forzata (Stop dell'utente): niente riavvii finche' un load() esplicito non lo azzera

    # -- processo ---------------------------------------------------------
    class _NotSerializable(RuntimeError):
        pass

    def _stderr_tail(self, n: int = 600) -> str:
        try:
            self._stderr.flush()
            size = self._stderr.seek(0, 2)
            self._stderr.seek(max(0, size - n))
            return self._stderr.read().decode('utf-8', errors='replace').strip()
        except Exception:
            return ''

    @staticmethod
    def _pump(proc: subprocess.Popen, q: queue.Queue) -> None:
        """Thread lettore: una riga alla volta in coda; None = fine del flusso (processo morto o chiuso)."""
        try:
            for line in proc.stdout:
                q.put(line)
        except Exception:
            pass
        q.put(None)

    def _send(self, proc: subprocess.Popen, req: Dict[str, Any]) -> int:
        rid = next(self._ids)
        try:
            data = json.dumps(dict(req, id=rid)) + '\n'  # prima la serializzazione: se fallisce non e' partito nulla
        except (TypeError, ValueError) as exc:
            raise self._NotSerializable(tr('gg_err_not_serializable').format(exc=exc)) from exc
        proc.stdin.write(data)
        proc.stdin.flush()
        return rid

    def _recv(self, rid: int, timeout: float) -> Dict[str, Any]:
        """Evento finale della richiesta `rid` (i log vanno al log_callback). Il worker morto o in ritardo chiude tutto."""
        q = self._lines
        end = time.monotonic() + timeout            # tetto assoluto: le righe di log non lo azzerano
        while True:
            try:
                line = q.get(timeout=max(0.0, end - time.monotonic())) if q is not None else None
            except queue.Empty:
                self._die(tr('gg_err_worker_timeout').format(s=int(timeout)))
            if line is None:
                self._die(None)
            try:
                ev = json.loads(line)
                if not isinstance(ev, dict):
                    raise ValueError
            except ValueError:
                logger.debug(f"gguf worker: riga non valida sul canale: {line[:80]!r}")
                continue
            if ev.get('ev') == 'log':
                self.log(ev.get('msg', ''))
                continue
            if ev.get('id') not in (None, rid):
                logger.debug(f"gguf worker: evento arretrato scartato (id {ev.get('id')}, atteso {rid})")
                continue
            return ev

    def _die(self, why: Optional[str]):
        """Chiude il worker e solleva RuntimeError con la coda dell'stderr (la causa nativa, se c'e')."""
        tail = self._kill()          # prima si uccide, poi si legge la coda dell'stderr (il figlio non scrive piu')
        if self._cancelled:
            raise RuntimeError(tr('gg_err_worker_cancelled'))
        self._failures += 1
        msg = why or tr('gg_err_worker_died').format(detail=tail or '-')
        self.log(msg)               # all'utente: chiaro, una volta (i blocchi dopo una morte ripetuta non lo ripetono)
        raise RuntimeError(msg)

    @staticmethod
    def _raise(ev: Dict[str, Any]):
        if ev.get('kind') == 'unknown_language':
            raise UnknownLanguageError(ev.get('msg', ''))
        raise RuntimeError(ev.get('msg', ''))

    def _kill(self) -> str:
        """Chiude il figlio e restituisce la coda del suo stderr ('' se non c'e'). Idempotente."""
        proc, self._proc = self._proc, None
        q, self._lines = self._lines, None
        if proc is None:
            return ''
        try:
            proc.kill()
            proc.wait(5)
        except Exception:
            pass
        tail = self._stderr_tail()
        for f in (proc.stdin, proc.stdout):
            try:
                f.close()
            except Exception:
                pass
        if q is not None:
            q.put(None)         # sveglia chi aspetta in _recv
        try:
            self._stderr.close()
        except Exception:
            pass
        self._stderr = None
        return tail

    def abort(self) -> None:
        """Stop dell'utente: chiude il figlio SENZA aspettare locks (anche durante un caricamento o un generate) e vieta i
        riavvii. Chi aspettava una risposta riceve un errore subito."""
        self._cancelled = True
        self._kill()

    def _start(self) -> None:
        self._kill()
        self._stderr = tempfile.TemporaryFile()
        try:
            proc = subprocess.Popen(
                [sys.executable, str(WORKER_SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._stderr, text=True, encoding='ascii', errors='replace', bufsize=1, cwd=str(WORKER_SCRIPT.parents[2]),
                creationflags=no_window_flags())
        except OSError as exc:
            raise RuntimeError(tr('gg_err_worker_start').format(exc=exc)) from exc
        self._proc, self._lines = proc, queue.Queue()
        threading.Thread(target=self._pump, args=(proc, self._lines), daemon=True).start()
        try:
            ev = self._recv(0, LOAD_TIMEOUT_S)          # 'ready' non porta id
            if ev.get('ev') != 'ready':
                if ev.get('phase') == 'start':           # il figlio non e' partito: la causa e' anche nell'stderr
                    tail = self._kill()
                    raise RuntimeError(f"{ev.get('msg', '')} {tail}".strip())
                self._raise(ev)
            try:
                rid = self._send(proc, {'op': 'load', 'gguf_path': self.gguf_path, 'quant': self.quant,
                                    'model_key': self.model_key, 'n_parallel': self.n_parallel,
                                    'ctx_per_seq': self.ctx_per_seq, 'n_gpu_layers': self.n_gpu_layers,
                                    'lang': get_translations().current_language})
            except (OSError, ValueError):                # il figlio e' morto dopo 'ready': la causa sta nell'stderr
                self._die(None)
            ev = self._recv(rid, LOAD_TIMEOUT_S)
            if ev.get('ev') != 'loaded':
                self._raise(ev)
        except BaseException:
            self._kill()
            raise

    # -- interfaccia del motore --------------------------------------------
    def load(self) -> None:
        with self._run_lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            self._failures = 0              # un load esplicito riparte da zero (il router lo chiama a ogni file)
            self._cancelled = False
            self._start()

    def generate(self, conversations: List[List[Dict[str, Any]]], max_new_tokens: int = 512,
                 **overrides: Any) -> List[str]:
        with self._run_lock:
            if self._cancelled:
                raise RuntimeError(tr('gg_err_worker_cancelled'))     # dopo uno Stop nessun riavvio del 12B
            proc = self._proc
            if proc is None or proc.poll() is not None:
                if self._failures > MAX_RESTARTS:
                    # il worker e' morto di nuovo subito dopo il riavvio: niente ricaricamenti del 12B a ogni blocco
                    raise RuntimeError(tr('gg_err_worker_died').format(detail='-'))
                self._start()
            proc = self._proc
            try:
                rid = self._send(proc, {'op': 'generate', 'conversations': conversations,
                                        'max_new_tokens': max_new_tokens})
            except self._NotSerializable:                 # nulla e' partito, il worker e' intatto
                raise
            except (OSError, ValueError, AttributeError):
                self._die(None)
            try:
                ev = self._recv(rid, GENERATE_TIMEOUT_S)
            except BaseException:
                self._kill()
                raise
            if ev.get('ev') != 'result':
                self._raise(ev)                           # errore di richiesta: il worker resta vivo
            self._failures = 0
            return ev['outputs']

    def unload(self, quiet: bool = False) -> None:
        # generate() in corso (annullo dalla GUI, cleanup): chiusura forzata, il lettore vede EOF ed esce con errore
        got = self._run_lock.acquire(timeout=UNLOAD_WAIT_S)
        if not got:
            self.abort()
            self._run_lock.acquire()
        try:
            proc = self._proc
            if proc is None:
                return
            if not quiet and proc.poll() is None:
                self.log(tr('le_unloading_from_vram').format(label=self.spec.label))
            try:
                self._send(proc, {'op': 'unload'})
                proc.wait(STOP_TIMEOUT_S)
            except Exception:
                pass
            self._kill()                # dopo l'uscita ordinata e' innocuo; se non risponde lo chiude comunque
            self._failures = 0
        finally:
            self._run_lock.release()
