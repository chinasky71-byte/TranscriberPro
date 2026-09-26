# -*- coding: utf-8 -*-
"""
Ponte verso il venv principale per il canale Qwen del glossario per-show.
File: mt_eval/glossary_qwen_bridge.py

Chiamato da build_glossary_candidates.py mentre gira dentro venv_glossary/
(llama-cpp-python CPU-only li'): invece di caricare il modello Qwen in
locale, delega l'estrazione a un subprocess lanciato col Python del venv
PRINCIPALE (mt_eval/glossary_qwen_gpu_cli.py), che ha gia' una build CUDA
di llama-cpp-python provata in produzione dal gender corrector sullo
stesso modello. Nessuna dipendenza nuova in venv_glossary/: l'isolamento
tra i due venv resta intatto per costruzione, non per disciplina.

Il PID del subprocess viene scritto in work_dir (glossary_qwen_gpu_pid.txt)
subito dopo l'avvio: gui/glossary_worker.py lo legge per uccidere anche
questo nipote quando l'utente annulla — altrimenti `terminate()` sul solo
processo venv_glossary (il padre diretto) lascerebbe il subprocess GPU
orfano con ~9GB di modello ancora in VRAM (Windows non propaga
TerminateProcess ai discendenti).
"""
import json
import logging
import subprocess
import threading
from pathlib import Path

from glossary_qwen_extract import ExtractResult

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_VENV_PYTHON = PROJECT_ROOT / 'venv' / 'Scripts' / 'python.exe'
GPU_CLI_SCRIPT = Path(__file__).resolve().parent / 'glossary_qwen_gpu_cli.py'


def main_venv_available() -> bool:
    return MAIN_VENV_PYTHON.exists() and GPU_CLI_SCRIPT.exists()


def run_qwen_channel(qwen_model_path: str, term_pairs_by_term: dict,
                      ranked_terms: list, work_dir: str,
                      n_gpu_layers: int = -1, progress_cb=None,
                      log=print) -> dict:
    """Sostituisce load/extract_spans/unload in-process di
    glossary_qwen_extract con un subprocess sul venv principale (GPU).
    Ritorna {term: [ExtractResult, ...]}, la stessa forma che
    evaluate_term/coverage/to_spans si aspettano gia'.
    `progress_cb`, se dato, e' chiamato con (term_idx, term_total, term,
    done, total)."""
    if not ranked_terms:
        return {}
    if not main_venv_available():
        raise RuntimeError(
            f"venv principale non trovato in {MAIN_VENV_PYTHON}: impossibile "
            f"usare il canale Qwen")

    request = {
        "qwen_model_path": qwen_model_path,
        "n_gpu_layers": n_gpu_layers,
        "terms": [
            {"term": term, "pairs": [
                {"source": p["source"], "reference": p["reference"]}
                for p in term_pairs_by_term[term]]}
            for term in ranked_terms],
    }
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)
    request_path = work_path / "glossary_qwen_gpu_request.json"
    result_path = work_path / "glossary_qwen_gpu_result.json"
    pid_path = work_path / "glossary_qwen_gpu_pid.txt"
    request["result_out"] = str(result_path)
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')

    proc = subprocess.Popen(
        [str(MAIN_VENV_PYTHON), str(GPU_CLI_SCRIPT), str(request_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT), text=True, encoding='utf-8', errors='replace',
        bufsize=1, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    try:
        pid_path.write_text(str(proc.pid), encoding='utf-8')
    except Exception as e:
        logger.warning(f"Scrittura pid Qwen GPU fallita: {e}")

    # stderr va drenato in un thread a parte: se resta pieno (buffer pipe
    # Windows 4KB) mentre il padre e' bloccato a leggere stdout, il figlio
    # si blocca al primo print successivo e il padre non riceve mai 'done'
    # (deadlock misurato in revisione con un traceback lungo su stderr).
    def _drain_stderr(stream):
        try:
            for eline in stream:
                eline = eline.rstrip()
                if eline:
                    logger.info(f"[qwen-gpu-stderr] {eline}")
        except Exception:
            pass

    stderr_thread = threading.Thread(target=_drain_stderr, args=(proc.stderr,),
                                      daemon=True)
    stderr_thread.start()

    error_msg = None
    got_done = False
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            ev = event.get('ev')
            if ev == 'progress' and progress_cb is not None:
                progress_cb(event.get('term_idx', 0), event.get('term_total', 0),
                            event.get('term', ''), event.get('done', 0),
                            event.get('total', 0))
            elif ev == 'vram_warning':
                log(f"  [Qwen GPU] {event.get('msg', '')}")
            elif ev == 'cpu_fallback':
                log(f"  [Qwen GPU] {event.get('msg', '')}")
            elif ev == 'error':
                error_msg = event.get('msg', 'errore sconosciuto')
            elif ev == 'done':
                got_done = True
    finally:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            log("  [Qwen GPU] processo non terminato entro 30s, kill forzato")
            try:
                proc.kill()
            except Exception:
                pass
            proc.wait()
        stderr_thread.join(timeout=5)
        try:
            pid_path.unlink()
        except Exception:
            pass

    if error_msg or not got_done or proc.returncode != 0:
        raise RuntimeError(error_msg or
                            f"subprocess Qwen GPU terminato con codice {proc.returncode}")

    results_raw = json.loads(result_path.read_text(encoding='utf-8'))
    return {
        term: [ExtractResult(r["kind"], r.get("text")) for r in results_raw[term]]
        for term in ranked_terms if term in results_raw}
