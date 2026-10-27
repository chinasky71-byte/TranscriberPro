# -*- coding: utf-8 -*-
"""
Coda headless di Transcriber Pro (senza GUI) con file di stato leggibile.

Usa lo STESSO motore della GUI (`core/jobs/engine.py`: un processo `core.pipeline_cli` per file, la RAM/VRAM torna al sistema a
fine file) e aggiorna a ogni evento `queue_status.json`, cosi' una coda lanciata fuori dall'interfaccia si puo' controllare: file
corrente, fase, percentuale, ETA, anteprima dei passi (`current.steps`), completati e falliti. Come la GUI: scrive la cronologia
(`~/.transcriberpro/history.json`, la stessa della scheda Cronologia), produce gli stessi testi di log e a fine coda ripulisce le
cache dei modelli (`--keep-caches` per non farlo).

Uso:
    python -m core.queue_runner "V:\\RahXephon" [altra\\cartella o file.mkv ...]
        [--recursive] [--skip-existing] [--status percorso.json] [--notify] [--log-dir cartella] [--keep-caches]

Log: `<log-dir>/<data>_queue.log` ha l'intero flusso (quello del log della GUI), `<data>_NNN.log` solo il file N; ogni riga e'
preceduta da [INFO], [WARNING] o [ERROR].

Note operative:
  - NON lanciarla insieme alla GUI (o a un'altra coda) sulla stessa macchina: stessa GPU, stessa cache
    dei modelli (a fine coda si ripuliscono le cache non preservate). Un file di lock lo impedisce
    tra due code headless; con la GUI aperta viene stampato un avviso.
  - Si interrompe con Ctrl+C (uccide l'albero dei processi e segna la coda 'cancelled'). Chiudere la
    finestra della console NON ferma il figlio.
  - Il file di stato e' scritto in modo atomico (temporaneo + replace): si puo' aprire in qualunque
    momento. Default: ~/.transcriberpro/queue_status.json.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from core.jobs.engine import QueueEngine, QueueListener, level_of
from core.jobs.file_runner import kill_tree  # noqa: F401  (nome storico del modulo)
from core.jobs.job_queue import JobQueue
from utils.translations import tr

VIDEO_EXTS = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.ts', '.mpg', '.mpeg', '.wmv', '.webm'}
_ROOT = Path(__file__).resolve().parent.parent
_HOME = Path.home() / '.transcriberpro'


def _iso(t: Optional[float] = None) -> str:
    return datetime.fromtimestamp(t if t is not None else time.time()).isoformat(timespec='seconds')


def _natural_key(p: Path):
    """Ordine naturale: 'Ep 2' prima di 'Ep 10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(p))]


def collect_files(inputs: List[str], recursive: bool = False, skip_existing: bool = False) -> List[Path]:
    """Video delle cartelle/file indicati, in ordine naturale per cartella. Percorsi risolti (nessun
    duplicato anche se passati in forma relativa e assoluta). Con `skip_existing` salta i video che
    hanno gia' `<nome>.it.srt` accanto."""
    found: List[Path] = []
    for item in inputs:
        p = Path(item)
        try:
            p = p.resolve()
        except Exception:
            pass
        if p.is_file():
            found.append(p)
        elif p.is_dir():
            it = p.rglob('*') if recursive else p.iterdir()
            found.extend(sorted((f for f in it if f.is_file() and f.suffix.lower() in VIDEO_EXTS),
                                key=_natural_key))
    out, seen = [], set()
    for f in found:
        key = str(f).lower()
        if key in seen:
            continue
        seen.add(key)
        if skip_existing and f.with_name(f.stem + '.it.srt').exists():
            continue
        out.append(f)
    return out


def eta_seconds(percent: int, elapsed: float) -> Optional[int]:
    """ETA del file dalla percentuale e dal tempo trascorso: non prima del 3% e dei 20 s."""
    if percent < 3 or percent >= 99 or elapsed < 20:
        return None
    return int(elapsed * (100 - percent) / percent)


class QueueStatus:
    """Stato della coda, serializzato in JSON in modo atomico."""

    def __init__(self, path: Path, files: List[Path]):
        self.path = Path(path)
        self.started = time.time()
        self.state = 'running'
        self.files: List[Dict] = [
            {'name': f.name, 'path': str(f), 'status': 'queued', 'percent': 0, 'phase': '',
             'seconds': None, 'output': None, 'error': None} for f in files]
        self.current: Optional[int] = None
        self._file_t0: Optional[float] = None
        self._steps: Optional[Dict] = None          # anteprima dei passi del file corrente (steps_to_dict)

    # -- aggiornamenti ----------------------------------------------------
    def start_file(self, idx: int) -> None:
        self.current = idx
        self._file_t0 = time.time()
        self.files[idx].update(status='processing', percent=0, phase='setup')
        self._steps = None
        self.write()

    def set_steps(self, steps: Optional[Dict]) -> None:
        self._steps = steps
        self.write()

    def progress(self, idx: int, percent: int, phase: str) -> None:
        f = self.files[idx]
        f['percent'], f['phase'] = percent, phase or f.get('phase', '')
        self.write()

    def end_file(self, idx: int, ok: bool, output: Optional[str] = None, error: Optional[str] = None,
                 status: Optional[str] = None) -> None:
        f = self.files[idx]
        f.update(status=status or ('completed' if ok else 'failed'),
                 percent=100 if ok else f['percent'], phase='',
                 seconds=int(time.time() - (self._file_t0 or time.time())), output=output, error=error)
        self.current = None
        self._steps = None
        self.write()

    def finish(self, state: str = 'finished') -> None:
        self.state = state
        self.current = None
        self.write(retries=6)

    # -- serializzazione --------------------------------------------------
    def snapshot(self) -> Dict:
        by = lambda s: [f for f in self.files if f['status'] == s]    # noqa: E731
        done, failed, queued = by('completed'), by('failed'), by('queued')
        cur = self.files[self.current] if self.current is not None else None
        elapsed = (time.time() - self._file_t0) if (cur is not None and self._file_t0) else 0.0
        eta_file = eta_seconds(cur['percent'], elapsed) if cur is not None else None
        eta_queue = None
        durations = [f['seconds'] for f in done if f.get('seconds')]   # i falliti non fanno media
        if durations:
            avg = sum(durations) / len(durations)
            if cur is None:
                rest = 0.0
            elif eta_file is not None:
                rest = eta_file
            elif cur['percent'] >= 99:
                rest = 0.0                                    # fase finale (upload/remux): quasi finito
            else:
                rest = max(avg - elapsed, 0.0)                # primi secondi del file: stima dalla media
            eta_queue = int(rest + avg * len(queued))
        return {
            'version': 1,
            'state': self.state,
            'pid': os.getpid(),
            'started': _iso(self.started),
            'updated': _iso(),
            'total': len(self.files),
            'completed': len(done),
            'failed': len(failed),
            'cancelled': len(by('cancelled')),
            'queued': len(queued),
            'current': ({'index': self.current + 1, 'name': cur['name'], 'phase': cur['phase'],
                         'percent': cur['percent'], 'eta_seconds': eta_file,
                         **({'steps': self._steps} if self._steps else {})} if cur else None),
            'eta_queue_seconds': eta_queue,
            'files': self.files,
        }

    def write(self, retries: int = 2) -> None:
        """Scrittura atomica. Su Windows `replace` puo' fallire se un lettore ha il file aperto: si riprova
        (indispensabile per lo stato finale); un errore non deve mai far fallire la coda."""
        data = None
        for attempt in range(retries + 1):
            try:
                if data is None:
                    data = json.dumps(self.snapshot(), ensure_ascii=False, indent=2)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(self.path.suffix + f'.{os.getpid()}.tmp')
                tmp.write_text(data, encoding='utf-8')
                tmp.replace(self.path)
                return
            except Exception:
                time.sleep(0.2)


def notify(title: str, message: str) -> None:
    """Notifica di sistema (best effort). Windows: testo passato per variabile d'ambiente, nessun apice/carattere
    speciale viene mai interpretato da PowerShell. Linux: `notify-send` se presente (senza non fa nulla). Altrove: niente."""
    if sys.platform.startswith('linux'):
        try:
            exe = shutil.which('notify-send')
            if exe:
                subprocess.Popen([exe, '--app-name=Transcriber Pro', '--', title, message],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        return
    if os.name != 'nt':
        return
    try:
        ps = ("Add-Type -AssemblyName System.Windows.Forms; "
              "$n = New-Object System.Windows.Forms.NotifyIcon; "
              "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
              "$n.ShowBalloonTip(8000, $env:TP_NOTIFY_TITLE, $env:TP_NOTIFY_MSG, 'Info'); "
              "Start-Sleep -Seconds 9; $n.Dispose()")
        env = dict(os.environ, TP_NOTIFY_TITLE=title, TP_NOTIFY_MSG=message)
        subprocess.Popen(['powershell', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', ps], env=env,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception:
        pass


def _gui_running() -> bool:
    try:
        import psutil
        for p in psutil.process_iter(['cmdline']):
            cl = ' '.join(p.info.get('cmdline') or [])
            if 'main.py' in cl and 'Transcriber' in cl and 'queue_runner' not in cl:
                return True
    except Exception:
        pass
    return False


class QueueLock:
    """Lock su file tra due code headless (stessa GPU, stessa cache dei modelli)."""

    def __init__(self, path: Path):
        self.path = path

    def acquire(self) -> bool:
        try:
            if self.path.exists():
                try:
                    pid = int(json.loads(self.path.read_text(encoding='utf-8')).get('pid', 0))
                    import psutil
                    if pid and psutil.pid_exists(pid) and pid != os.getpid():
                        cl = ' '.join(psutil.Process(pid).cmdline())
                        if 'queue_runner' in cl:
                            return False
                except Exception:
                    pass            # lock orfano o illeggibile: si sovrascrive
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({'pid': os.getpid(), 'since': _iso()}), encoding='utf-8')
        except Exception:
            pass
        return True

    def release(self) -> None:
        try:
            self.path.unlink()
        except Exception:
            pass


def steps_to_dict(snapshot) -> Dict:
    """Anteprima dei passi (PipelineSnapshot della GUI) in forma JSON: {'done', 'total', 'active', 'steps': [{key, status, pct, eta}]}."""
    act = snapshot.active
    return {'done': snapshot.done, 'total': snapshot.total, 'active': act.key if act else '',
            'steps': [{'key': st.key, 'status': st.status, 'pct': st.pct, 'eta': st.eta} for st in snapshot.steps]}


class _Listener(QueueListener):
    """Ganci del motore (core/jobs/engine.py) -> stato JSON, log, cronologia, notifiche, stampe a console.

    I log sono quelli della GUI (stessi testi, stesso filtro del rumore delle librerie), ognuno preceduto da un'etichetta di livello
    ([INFO], [WARNING], [ERROR]): `<stamp>_queue.log` ha tutto il flusso, `<stamp>_NNN.log` solo il file N."""

    def __init__(self, files: List[Path], status: QueueStatus, log_dir: Path, stamp: str, notify_errors: bool):
        self.files, self.status, self.log_dir, self.stamp = files, status, log_dir, stamp
        self.notify_errors = notify_errors
        self._idx_of = {str(f): i for i, f in enumerate(files)}
        self._cur: Optional[int] = None
        self._file_log = None
        self._queue_log = open(log_dir / f'{stamp}_queue.log', 'w', encoding='utf-8')
        self._out: Dict[str, str] = {}
        self._err: Dict[str, str] = {}
        self._phase = ''
        self._first_error_notified = False

    def close(self) -> None:
        for f in (self._file_log, self._queue_log):
            try:
                if f:
                    f.close()
            except Exception:
                pass
        self._file_log = None

    # -- log
    def on_log(self, text: str) -> None:
        for line in text.split('\n'):
            if not line.strip():
                continue
            row = f'[{level_of(line)}] {line}\n'
            self._queue_log.write(row)
            if self._file_log:
                self._file_log.write(row)
        self._queue_log.flush()
        if self._file_log:
            self._file_log.flush()

    # -- file
    def on_file_started(self, path: str) -> None:
        idx = self._idx_of.get(path)
        if idx is None:
            return
        self._cur, self._phase = idx, 'setup'
        self.status.start_file(idx)
        self._file_log = open(self.log_dir / f'{self.stamp}_{idx + 1:03d}.log', 'w', encoding='utf-8')
        print(f'[{idx + 1}/{len(self.files)}] {Path(path).name}', flush=True)

    def on_file_progress(self, path: str, percent: int) -> None:
        if self._cur is not None:
            self.status.progress(self._cur, percent, self._phase)

    def on_file_steps(self, path: str, snapshot) -> None:
        if self._cur is not None:
            act = snapshot.active
            self._phase = act.key if act else self._phase
            self.status.set_steps(steps_to_dict(snapshot))

    def on_history(self, entry: dict) -> None:
        self._out[entry.get('video_path', '')] = entry.get('srt_path') or ''
        from core.jobs.history_store import append_entry
        append_entry(entry)

    def on_file_error(self, path: str, message: str) -> None:
        self._err[path] = message

    def _end(self, path: str, ok: bool) -> None:
        idx = self._cur if self._cur is not None else self._idx_of.get(path)
        if idx is None:
            return
        self.status.end_file(idx, ok, self._out.get(path) if ok else None, None if ok else self._err.get(path))
        print(f"    {'OK' if ok else tr('qr_status_failed')} ({self.status.files[idx]['seconds']} s)", flush=True)
        try:
            if self._file_log:
                self._file_log.close()
        except Exception:
            pass
        self._file_log, self._cur = None, None

    def on_file_completed(self, path: str) -> None:
        self._end(path, True)

    def on_file_failed(self, path: str) -> None:
        self._end(path, False)
        if self.notify_errors and not self._first_error_notified:
            self._first_error_notified = True
            notify(tr('qr_transcriber_pro_error'), tr('qr_failed').format(name=Path(path).name))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Coda headless di Transcriber Pro con file di stato.')
    ap.add_argument('inputs', nargs='+', help='cartelle o file video')
    ap.add_argument('--recursive', action='store_true')
    ap.add_argument('--skip-existing', action='store_true', help='salta i video con <nome>.it.srt accanto')
    ap.add_argument('--status', default=str(_HOME / 'queue_status.json'))
    ap.add_argument('--log-dir', default=str(_HOME / 'queue_logs'))
    ap.add_argument('--notify', action='store_true', help='notifica di Windows a fine coda e al primo errore')
    ap.add_argument('--keep-caches', action='store_true',
                    help="non ripulire le cache dei modelli a fine coda (come fa la GUI: di default si ripuliscono)")
    args = ap.parse_args(argv)

    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

    files = collect_files(args.inputs, args.recursive, args.skip_existing)
    if not files:
        print(tr('qr_no_video_file_found'))
        return 1

    lock = QueueLock(_HOME / 'queue.lock')
    if not lock.acquire():
        print(tr('qr_another_headless_queue_is_already'))
        return 3
    if _gui_running():
        print(tr('qr_warning_the_transcriber_pro_gui'))

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    status = QueueStatus(Path(args.status), files)
    status.write()
    print(tr('qr_files_in_the_queue_status').format(n=len(files), path=status.path), flush=True)

    queue = JobQueue()
    for f in files:
        queue.add(str(f))
    listener = _Listener(files, status, log_dir, stamp, args.notify)
    engine = QueueEngine(queue, listener, cleanup_caches=not args.keep_caches, check_exists=True, project_root=_ROOT)
    state = 'finished'
    try:
        engine.run()
    except KeyboardInterrupt:
        state = 'cancelled'
        print(tr('qr_interrupted'), flush=True)
        cur = status.current
        if cur is not None and status.files[cur]['status'] == 'processing':
            status.end_file(cur, False, error=tr('qr_interrupted_2'), status='cancelled')
    finally:
        status.finish(state)
        lock.release()
        listener.close()
    snap = status.snapshot()
    print(tr('qr_done_ok_failed_cancelled_out').format(completed=snap['completed'], failed=snap['failed'], cancelled=snap['cancelled'], total=snap['total']), flush=True)
    if args.notify:
        notify(tr('qr_transcriber_pro_queue_finished'),
               tr('qr_completed_failed_out_of').format(completed=snap['completed'], failed=snap['failed'], total=snap['total']))
    if state == 'cancelled':
        return 130
    return 0 if snap['failed'] == 0 else 2


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    # Lingua dei log: stessa regola della GUI (config 'language'), senza Qt.
    try:
        from utils.translations import init_language_headless as _tp_init_lang
        _tp_init_lang()
    except Exception:
        pass

    sys.exit(main())
