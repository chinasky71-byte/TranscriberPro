"""
Invocazione dei motori (senza EngineRouter: un errore resta un errore,
nessun ripiego silenzioso su Whisper), ripresa, scritture atomiche,
raggruppamento Canary con offset e monitor VRAM via nvidia-smi.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

SCHEMA_HYP = "asr-bench/hyp/1"
CANARY_OFFSET_S = 10_000.0
_NO_WINDOW = {'creationflags': 0x08000000} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}

_RE_FAILED_CHUNKS = re.compile(r'Completato con (\d+) chunks falliti')
_RE_ALIGNER_FAILED = re.compile(r'Aligner fallito su (\d+) chunk')
_ERROR_MARKERS = ('❌ Errore trascrizione', '❌ Errore caricamento')


def write_json_atomic(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, allow_nan=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_text_atomic(path: Path, text: str, encoding: str = 'utf-8') -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding=encoding, newline='') as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def hyp_is_current(path: Path, wav_sha: str, fp: Dict) -> bool:
    """True se l'ipotesi esiste, non e' fallita, e corrisponde allo stesso wav
    e alla stessa impronta di configurazione."""
    try:
        d = json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return False
    return (d.get('schema') == SCHEMA_HYP and d.get('status') in ('ok', 'partial')
            and d.get('wav_sha') == wav_sha and d.get('fingerprint') == fp)


def clean_segments(segs: Sequence[Dict], shift: float = 0.0) -> List[Dict]:
    out = []
    for s in segs:
        words = [{'start': round(float(w['start']) - shift, 3), 'end': round(float(w['end']) - shift, 3),
                  'word': str(w['word'])} for w in (s.get('words') or [])]
        out.append({'start': round(float(s['start']) - shift, 3), 'end': round(float(s['end']) - shift, 3),
                    'text': str(s.get('text', '')), 'words': words})
    return out


class LogCapture:
    def __init__(self, echo: Optional[Callable[[str], None]] = None):
        self.lines: List[str] = []
        self.echo = echo

    def __call__(self, msg: str) -> None:
        self.lines.append(str(msg))
        if self.echo:
            self.echo(str(msg))

    def mark(self) -> int:
        return len(self.lines)

    def since(self, k: int) -> List[str]:
        return self.lines[k:]


def parse_engine_log(lines: Sequence[str]) -> Dict:
    n_failed = 0
    n_align_failed = 0
    errors = []
    for l in lines:
        m = _RE_FAILED_CHUNKS.search(l)
        if m:
            n_failed += int(m.group(1))
        m = _RE_ALIGNER_FAILED.search(l)
        if m:
            n_align_failed += int(m.group(1))
        if any(k in l for k in _ERROR_MARKERS):
            errors.append(l.strip())
    return {'n_failed_chunks': n_failed, 'n_aligner_failed': n_align_failed, 'errors': errors}


def transcribe_window(engine, chunks: List[Tuple[str, float, float]], lang: str,
                      logcap: LogCapture, output_path: str = '') -> Dict:
    """Una chiamata transcribe_chunks per finestra (whisper, qwen3).
    (False, lang) senza eccezioni e senza righe d'errore = ipotesi vuota."""
    engine._last_segments = []
    k = logcap.mark()
    t0 = time.time()
    try:
        ok, detected = engine.transcribe_chunks(chunks, output_path, lang)
    except Exception as e:
        return {'status': 'failed', 'error': f"{type(e).__name__}: {e}", 'segments': [],
                'elapsed_s': round(time.time() - t0, 3), 'detected_lang': None,
                **parse_engine_log(logcap.since(k))}
    elapsed = time.time() - t0
    info = parse_engine_log(logcap.since(k))
    segs = list(engine.last_segments or [])
    status = 'ok'
    error = None
    if info['errors']:
        status, error = 'failed', '; '.join(info['errors'])[:500]
    elif info['n_failed_chunks'] or info['n_aligner_failed']:
        status = 'partial'
        error = f"chunk falliti={info['n_failed_chunks']} aligner falliti={info['n_aligner_failed']}"
    return {'status': status, 'error': error, 'segments': clean_segments(segs) if status != 'failed' else [],
            'elapsed_s': round(elapsed, 3), 'detected_lang': detected, **info}


def canary_group(engine, group: List[Tuple[str, List[Tuple[str, float, float]], float]],
                 out_dir: Path, logcap: LogCapture) -> Dict[str, Dict]:
    """Una sola chiamata Canary per un gruppo di finestre: la finestra k ha
    offset k*CANARY_OFFSET_S; i segmenti tornano alla finestra per offset.
    group: [(win_id, chunks relativi alla finestra, durata)]."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_chunks = []
    for k, (_wid, chunks, dur) in enumerate(group):
        if dur >= CANARY_OFFSET_S:
            raise ValueError("finestra piu' lunga dell'offset Canary")
        off = k * CANARY_OFFSET_S
        all_chunks += [(str(p), off + float(s), off + float(e)) for p, s, e in chunks]
    engine._last_segments = []
    m = logcap.mark()
    t0 = time.time()
    try:
        engine.load()
        ok, _lang = engine.transcribe_chunks(all_chunks, str(out_dir / 'canary_group.srt'), 'en')
        error = None
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    elapsed = time.time() - t0
    info = parse_engine_log(logcap.since(m))
    total_audio = sum(g[2] for g in group) or 1.0
    res: Dict[str, Dict] = {}
    if error is not None:
        for wid, _c, dur in group:
            res[wid] = {'status': 'failed', 'error': error, 'segments': [],
                        'elapsed_s': round(elapsed * dur / total_audio, 3), **info}
        return res
    buckets: Dict[int, List[Dict]] = {k: [] for k in range(len(group))}
    stray = 0
    for s in engine.last_segments or []:
        k = int(float(s['start']) // CANARY_OFFSET_S)
        if k in buckets:
            buckets[k].append(s)
        else:
            stray += 1
    status = 'partial' if (info['n_aligner_failed'] or stray) else 'ok'
    for k, (wid, _c, dur) in enumerate(group):
        res[wid] = {'status': status,
                    'error': (f"aligner falliti={info['n_aligner_failed']} fuori offset={stray}"
                              if status == 'partial' else None),
                    'segments': clean_segments(buckets[k], shift=k * CANARY_OFFSET_S),
                    'elapsed_s': round(elapsed * dur / total_audio, 3),
                    'group_elapsed_s': round(elapsed, 3), 'group_size': len(group), **info}
    return res


# ── GPU ────────────────────────────────────────────────────────────────────

def _nvsmi(args: List[str], timeout: float = 15) -> Optional[str]:
    try:
        r = subprocess.run(['nvidia-smi'] + args, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=timeout, **_NO_WINDOW)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def gpu_busy_reasons(own_pids: Optional[set] = None) -> List[str]:
    """Motivi per cui la GPU NON e' libera (lista vuota = libera). Su WDDM
    nvidia-smi elenca anche explorer/chrome con memoria N/A: conta solo i
    processi python e l'app Transcriber Pro (main.py)."""
    own = set(own_pids or ()) | {os.getpid(), os.getppid()}
    out = _nvsmi(['--query-compute-apps=pid,process_name', '--format=csv,noheader'])
    if out is None:
        return ["nvidia-smi non disponibile: impossibile verificare che la GPU sia libera"]
    reasons = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(',', 1)]
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid in own:
            continue
        if 'python' in parts[1].lower():
            reasons.append(f"processo GPU {pid} {parts[1]}")
    # ASR_EVAL_ALLOW_GUI=1: l'app aperta ma INATTIVA (nessun job, nessun processo
    # sulla GPU) non e' un ostacolo; la sandbox ferma comunque il banco se
    # config.json cambia. Restano vietati i processi python sulla GPU e ogni
    # pipeline_cli.
    allow_gui = os.environ.get('ASR_EVAL_ALLOW_GUI') == '1'
    try:
        import psutil
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            if p.info['pid'] in own:
                continue
            name = (p.info.get('name') or '').lower()
            cmd = ' '.join(p.info.get('cmdline') or []).lower()
            if 'python' in name and re.search(r'core[.\\/]pipeline_cli', cmd):
                reasons.append(f"job di Transcriber Pro in corso (pid {p.info['pid']}: {cmd[:120]})")
            elif (not allow_gui and 'python' in name
                    and re.search(r'(^|[\\/\s])main\.py\b', cmd)):
                reasons.append(f"Transcriber Pro in esecuzione (pid {p.info['pid']}: {cmd[:120]})")
    except Exception:
        pass
    return reasons


def gpu_mem_used_mb() -> Optional[float]:
    out = _nvsmi(['--query-gpu=memory.used', '--format=csv,noheader,nounits'], timeout=5)
    if not out:
        return None
    try:
        return float(out.splitlines()[0].strip())
    except (ValueError, IndexError):
        return None


class VramMonitor:
    """Interroga nvidia-smi ogni 500 ms: memoria TOTALE usata della GPU (su
    WDDM la memoria per processo non e' leggibile). Picco meno base."""

    def __init__(self, interval: float = 0.5, reader: Callable[[], Optional[float]] = gpu_mem_used_mb):
        self.interval = interval
        self.reader = reader
        self.baseline = reader()
        self._peak = self.baseline
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._t.start()
        return self

    def _loop(self):
        while not self._stop.wait(self.interval):
            v = self.reader()
            if v is not None:
                with self._lock:
                    self._peak = v if self._peak is None else max(self._peak, v)

    def take_peak(self) -> Optional[float]:
        """Picco dall'ultima chiamata; azzera il picco al valore attuale."""
        with self._lock:
            p = self._peak
            self._peak = self.reader()
        return p

    def stop(self):
        self._stop.set()
