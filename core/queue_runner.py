# -*- coding: utf-8 -*-
"""
Headless queue for Transcriber Pro, with a readable status file.

Thin CLI client of `core.jobs.JobManager`: it collects the files, adds them to
the shared queue and writes the historical `queue_status.json` schema at every
update. The pipeline still runs one subprocess per file (`core.pipeline_cli`).

Usage:
    python -m core.queue_runner <folder or file> [...] [--recursive]
        [--skip-existing] [--status path.json] [--notify] [--log-dir folder]

Notes:
  - Do not run it together with the GUI or another queue on the same machine.
  - Ctrl+C kills the process tree and marks the queue cancelled.
  - The status file is written atomically; default ~/.transcriberpro/queue_status.json.
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
from typing import List, Optional

from utils.translations import tr

VIDEO_EXTS = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.ts', '.mpg', '.mpeg', '.wmv', '.webm'}
_ROOT = Path(__file__).resolve().parent.parent
_HOME = Path.home() / '.transcriberpro'

from core.jobs.process_runner import kill_tree  # noqa: E402,F401  (re-export, legacy API)


def _iso(t: Optional[float] = None) -> str:
    return datetime.fromtimestamp(t if t is not None else time.time()).isoformat(timespec='seconds')


def _natural_key(p: Path):
    """Natural order: 'Ep 2' before 'Ep 10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(p))]


def collect_files(inputs: List[str], recursive: bool = False, skip_existing: bool = False) -> List[Path]:
    """Videos of the given folders/files, natural order per folder, no duplicates."""
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
    """File ETA from percentage and elapsed time: not before 3% and 20 s."""
    if percent < 3 or percent >= 99 or elapsed < 20:
        return None
    return int(elapsed * (100 - percent) / percent)


def notify(title: str, message: str) -> None:
    """Best-effort system notification. Windows: environment variables; Linux: notify-send."""
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
    """File lock between two headless queues (same GPU, same model cache)."""

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
                    pass
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


class _StatusWriter:
    """Write the legacy status schema atomically, throttled."""

    def __init__(self, path: Path, manager, interval_s: float = 0.5):
        self.path = Path(path)
        self.manager = manager
        self.interval_s = interval_s
        self._last = 0.0

    def write(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last < self.interval_s:
            return
        self._last = now
        data = self.manager.legacy_snapshot()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + f'.{os.getpid()}.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(self.path)
        except Exception:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Headless Transcriber Pro queue with a status file.')
    ap.add_argument('inputs', nargs='+', help='folders or video files')
    ap.add_argument('--recursive', action='store_true')
    ap.add_argument('--skip-existing', action='store_true', help='skip videos with <name>.it.srt next to them')
    ap.add_argument('--status', default=str(_HOME / 'queue_status.json'))
    ap.add_argument('--log-dir', default=str(_HOME / 'queue_logs'))
    ap.add_argument('--notify', action='store_true', help='system notification at the end and on the first error')
    args = ap.parse_args(argv)

    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from utils.config import get_config
    from core.jobs.manager import JobManager

    target = get_config().get_target_language()

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

    from utils.temp_cleanup import sweep_summary
    leftover = sweep_summary()
    if leftover:
        print(f"TMPDIR: {leftover}")
    from utils.backend_preflight import check_for_job
    _cfg = get_config()
    manager = JobManager(target_language=target, persist_path=None, log_dir=log_dir,
                         preflight=lambda job: check_for_job(_cfg, job.overrides))
    writer = _StatusWriter(Path(args.status), manager)
    for video in files:
        manager.add(video)

    def _on_event(event: dict) -> None:
        writer.write(force=event.get('kind') in ('status', 'created', 'removed'))

    unsubscribe = manager.subscribe(_on_event)
    writer.write(force=True)
    print(tr('qr_files_in_the_queue_status').format(n=len(files), path=args.status), flush=True)

    first_error_notified = False
    cancelled = False
    try:
        manager.start()
        manager.wait()
    except KeyboardInterrupt:
        cancelled = True
        print(tr('qr_interrupted'), flush=True)
        manager.stop()
    finally:
        unsubscribe()
        writer.write(force=True)
        snap = manager.legacy_snapshot()
        snap['state'] = 'cancelled' if cancelled else 'finished'
        try:
            Path(args.status).write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        lock.release()

    if not cancelled and manager.snapshot():
        failed = [job for job in manager.snapshot() if job['status'] == 'failed']
        if failed and args.notify and not first_error_notified:
            first_error_notified = True
            notify(tr('qr_transcriber_pro_error'), tr('qr_failed').format(name=failed[0]['name']))
    snap = manager.legacy_snapshot()
    print(tr('qr_done_ok_failed_cancelled_out').format(completed=snap['completed'], failed=snap['failed'],
                                                       cancelled=snap['cancelled'], total=snap['total']), flush=True)
    if args.notify:
        notify(tr('qr_transcriber_pro_queue_finished'),
               tr('qr_completed_failed_out_of').format(completed=snap['completed'],
                                                       failed=snap['failed'], total=snap['total']))
    if cancelled:
        return 130
    return 0 if snap['failed'] == 0 else 2


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        from utils.translations import init_language_headless as _tp_init_lang
        _tp_init_lang()
    except Exception:
        pass
    sys.exit(main())
