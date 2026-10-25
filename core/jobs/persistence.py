"""Atomic persistence of the job queue state."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from .models import Job, RUNNING, INTERRUPTED


def load_jobs(path: Path) -> List[Job]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []
    jobs = []
    for item in data.get("jobs", []):
        try:
            job = Job.from_dict(item)
        except Exception:
            continue
        if job.status == RUNNING:
            # The process died with the previous session: do not pretend it is alive.
            job.status = INTERRUPTED
            job.error = job.error or "interrupted by restart"
        jobs.append(job)
    return jobs


def save_jobs(path: Path, jobs: List[Job]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"version": 1, "jobs": [job.to_dict() for job in jobs]},
                      ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)
