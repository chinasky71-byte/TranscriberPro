# -*- coding: utf-8 -*-
"""
Coda headless di Transcriber Pro (senza GUI) con file di stato leggibile.

Esegue i file UNO ALLA VOLTA con lo stesso `core.pipeline_cli` che usa la GUI (un processo per file:
la RAM/VRAM torna al sistema a fine file) e aggiorna a ogni evento `queue_status.json`, cosi' una coda
lanciata fuori dall'interfaccia si puo' controllare: file corrente, fase, percentuale, ETA, completati
e falliti. La percentuale e' quella della GUI (`gui/file_progress.FileProgress`, classe senza Qt).

Uso:
    python -m core.queue_runner "V:\\RahXephon" [altra\\cartella o file.mkv ...]
        [--recursive] [--skip-existing] [--status percorso.json] [--notify] [--log-dir cartella]

Note operative:
  - NON lanciarla insieme alla GUI (o a un'altra coda) sulla stessa macchina: stessa GPU, stessa cache
    dei modelli (a fine coda la GUI ripulisce le cache non preservate). Un file di lock lo impedisce
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
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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

    # -- aggiornamenti ----------------------------------------------------
    def start_file(self, idx: int) -> None:
        self.current = idx
        self._file_t0 = time.time()
        self.files[idx].update(status='processing', percent=0, phase='setup')
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
                         'percent': cur['percent'], 'eta_seconds': eta_file} if cur else None),
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
    """Notifica di Windows (best effort). Testo passato per variabile d'ambiente: nessun apice/carattere
    speciale viene mai interpretato da PowerShell."""
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


def kill_tree(proc: subprocess.Popen) -> None:
    """Uccide il processo e TUTTI i discendenti (ffmpeg, gender_corrector_cli...), come il worker della GUI."""
    try:
        import psutil
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        parent.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
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


def run_one(video: Path, target_language: str, files_done: int, file_progress_cls, on_progress,
            log_path: Path) -> Dict:
    """Elabora un file in un subprocess `core.pipeline_cli`. Ritorna {'ok', 'output', 'error'}.
    KeyboardInterrupt: uccide l'albero, pulisce i temporanei e rilancia."""
    ipc = Path(tempfile.mkdtemp(prefix='tp_queue_'))
    args_path, result_path = ipc / 'args.json', ipc / 'result.json'
    proc = None
    try:
        args_path.write_text(json.dumps({
            'video_path': str(video), 'target_language': target_language,
            'files_processed': files_done, 'result_path': str(result_path)}, ensure_ascii=False),
            encoding='utf-8')
        # Stesso ambiente della GUI (gui/workers.py): NIENTE PYTHONUTF8 / `-X utf8` (cambierebbe la codifica
        # di default delle subprocess annidate), solo gli stream del figlio in UTF-8.
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['TP_SUBPROCESS'] = '1'
        env['TQDM_DISABLE'] = '1'
        flags = 0
        for name in ('CREATE_NEW_PROCESS_GROUP', 'CREATE_NO_WINDOW'):
            flags |= getattr(subprocess, name, 0)
        proc = subprocess.Popen(
            [sys.executable, '-m', 'core.pipeline_cli', str(args_path)], cwd=str(_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
            bufsize=1, env=env, creationflags=flags)

        fp = file_progress_cls(target_language)
        lf = open(log_path, 'w', encoding='utf-8')
        lock = threading.Lock()

        def _out():
            last_write = 0.0
            for line in proc.stdout:
                with lock:
                    lf.write(line)
                try:
                    pct = fp.feed(line.rstrip())
                except Exception:
                    pct = None
                now = time.time()
                if pct is not None or now - last_write > 15:
                    on_progress(fp.value, fp.phase or '')
                    last_write = now

        def _err():
            for line in proc.stderr:
                with lock:
                    lf.write('[stderr] ' + line)

        threads = [threading.Thread(target=_out, daemon=True), threading.Thread(target=_err, daemon=True)]
        for t in threads:
            t.start()
        try:
            while proc.poll() is None:      # attesa interrompibile da Ctrl+C (la lettura dalla pipe non lo e')
                time.sleep(0.5)
        except BaseException:
            kill_tree(proc)
            raise
        finally:
            for t in threads:
                t.join(timeout=5)
            try:
                lf.close()
            except Exception:
                pass
        rc = proc.returncode
        ok, output = rc == 0, None
        try:
            res = json.loads(result_path.read_text(encoding='utf-8'))
            ok = bool(res.get('success', ok))
            output = res.get('last_output_path')
        except Exception:
            pass
        return {'ok': ok, 'output': output, 'error': None if ok else f'exit code {rc}'}
    finally:
        shutil.rmtree(ipc, ignore_errors=True)
        try:   # il remux ffmpeg in corso puo' lasciare <video>.converting
            Path(str(video) + '.converting').unlink(missing_ok=True)
        except Exception:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Coda headless di Transcriber Pro con file di stato.')
    ap.add_argument('inputs', nargs='+', help='cartelle o file video')
    ap.add_argument('--recursive', action='store_true')
    ap.add_argument('--skip-existing', action='store_true', help='salta i video con <nome>.it.srt accanto')
    ap.add_argument('--status', default=str(_HOME / 'queue_status.json'))
    ap.add_argument('--log-dir', default=str(_HOME / 'queue_logs'))
    ap.add_argument('--notify', action='store_true', help='notifica di Windows a fine coda e al primo errore')
    args = ap.parse_args(argv)

    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from utils.config import get_config
    from gui.file_progress import FileProgress
    target = get_config().get_target_language()

    files = collect_files(args.inputs, args.recursive, args.skip_existing)
    if not files:
        print('Nessun file video trovato.')
        return 1

    lock = QueueLock(_HOME / 'queue.lock')
    if not lock.acquire():
        print('Un\'altra coda headless e\' gia\' in esecuzione (queue.lock). Non avviata.')
        return 3
    if _gui_running():
        print('ATTENZIONE: la GUI di Transcriber Pro risulta aperta. Non lanciare code in parallelo '
              '(stessa GPU e stessa cache dei modelli).')

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    status = QueueStatus(Path(args.status), files)
    status.write()
    print(f'{len(files)} file in coda. Stato: {status.path}', flush=True)

    first_error_notified = False
    state = 'finished'
    idx = None
    try:
        for idx, video in enumerate(files):
            status.start_file(idx)
            if not video.exists():
                status.end_file(idx, False, error='file non trovato')
                continue
            print(f'[{idx + 1}/{len(files)}] {video.name}', flush=True)
            try:
                res = run_one(video, target, idx, FileProgress,
                              lambda pct, phase, i=idx: status.progress(i, pct, phase),
                              log_dir / f'{stamp}_{idx + 1:03d}.log')
            except KeyboardInterrupt:
                raise
            except Exception as exc:          # un file non deve fermare la coda
                res = {'ok': False, 'output': None, 'error': f'{type(exc).__name__}: {exc}'}
            status.end_file(idx, res['ok'], res['output'], res['error'])
            print(f"    {'OK' if res['ok'] else 'FALLITO'} ({status.files[idx]['seconds']} s)", flush=True)
            if not res['ok'] and args.notify and not first_error_notified:
                first_error_notified = True
                notify('Transcriber Pro: errore', f'Fallito: {video.name}')
    except KeyboardInterrupt:
        state = 'cancelled'
        print('Interrotto.', flush=True)
        if idx is not None and status.files[idx]['status'] == 'processing':
            status.end_file(idx, False, error='interrotto', status='cancelled')
    finally:
        status.finish(state)
        lock.release()
    snap = status.snapshot()
    print(f"Fine: {snap['completed']} ok, {snap['failed']} falliti, {snap['cancelled']} annullati "
          f"su {snap['total']}.", flush=True)
    if args.notify:
        notify('Transcriber Pro: coda terminata',
               f"{snap['completed']} completati, {snap['failed']} falliti su {snap['total']}.")
    if state == 'cancelled':
        return 130
    return 0 if snap['failed'] == 0 else 2


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
