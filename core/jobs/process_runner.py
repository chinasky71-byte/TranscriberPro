"""Run one video through the isolated pipeline subprocess.

The pipeline itself is unchanged: ``python -m core.pipeline_cli args.json``.
This module owns the process details (environment, streams, cancellation,
result file) so the manager does not have to.

No Qt, no GPU: it only spawns and reads.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict
from utils.events import parse_line


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process and all its descendants (ffmpeg, helper CLIs)."""
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


class ProcessRunner:
    def __init__(self, root: Path | None = None, python: str | None = None):
        self.root = Path(root) if root else Path(__file__).resolve().parents[2]
        self.python = python or sys.executable

    def run(self, video: Path, target_language: str, files_processed: int,
            log_path: Path,
            on_line: Callable[[str], None] | None = None,
            on_event: Callable[[str, Dict[str, Any]], None] | None = None,
            cancel_event: threading.Event | None = None) -> Dict[str, Any]:
        """Run the file. Returns ``{ok, output, error, cancelled, exit_code}``."""
        video = Path(video)
        ipc = Path(tempfile.mkdtemp(prefix="tp_job_"))
        args_path, result_path = ipc / "args.json", ipc / "result.json"
        proc = None
        cancelled = False
        try:
            args_path.write_text(json.dumps({
                "video_path": str(video),
                "target_language": target_language,
                "files_processed": files_processed,
                "result_path": str(result_path),
            }, ensure_ascii=False), encoding="utf-8")

            env = os.environ.copy()
            from utils.gpu_detect import apply_subprocess_env
            apply_subprocess_env(env)
            env["PYTHONIOENCODING"] = "utf-8"
            env["TP_SUBPROCESS"] = "1"
            env["TQDM_DISABLE"] = "1"
            env["TP_EVENTS"] = "1"

            flags = 0
            for name in ("CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
                flags |= getattr(subprocess, name, 0)

            log_path = Path(log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "w", encoding="utf-8")
            lock = threading.Lock()

            proc = subprocess.Popen(
                [self.python, "-m", "core.pipeline_cli", str(args_path)],
                cwd=str(self.root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env=env, creationflags=flags,
            )

            def _out() -> None:
                for raw in proc.stdout:
                    line = raw.rstrip("\n")
                    with lock:
                        log_file.write(raw)
                    event = parse_line(line)
                    if event is not None:
                        if event[0] and on_event:
                            try:
                                on_event(event[0], event[1])
                            except Exception:
                                pass
                    elif on_line:
                        try:
                            on_line(line)
                        except Exception:
                            pass

            def _err() -> None:
                for raw in proc.stderr:
                    with lock:
                        log_file.write("[stderr] " + raw)
                    if on_line:
                        try:
                            on_line("[stderr] " + raw.rstrip("\n"))
                        except Exception:
                            pass

            readers = [threading.Thread(target=_out, daemon=True),
                       threading.Thread(target=_err, daemon=True)]
            for thread in readers:
                thread.start()

            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    kill_tree(proc)
                    break
                time.sleep(0.2)

            for thread in readers:
                thread.join(timeout=5)
            try:
                log_file.close()
            except Exception:
                pass

            rc = proc.returncode
            ok, output = rc == 0, None
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                ok = bool(result.get("success", ok))
                output = result.get("last_output_path")
            except Exception:
                pass
            if cancelled:
                return {"ok": False, "output": output, "error": "cancelled",
                        "cancelled": True, "exit_code": rc}
            return {"ok": ok, "output": output,
                    "error": None if ok else f"exit code {rc}",
                    "cancelled": False, "exit_code": rc}
        finally:
            shutil.rmtree(ipc, ignore_errors=True)
            try:
                Path(str(video) + ".converting").unlink(missing_ok=True)
            except Exception:
                pass
