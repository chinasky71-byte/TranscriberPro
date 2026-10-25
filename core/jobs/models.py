"""Job model for the shared queue.

A job is one video file. The pipeline still runs in its own subprocess; this
object is the state the UI, the CLI and the headless queue observe.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"

TERMINAL = {DONE, FAILED, CANCELLED, INTERRUPTED}

# Legacy names used by the headless queue status file.
LEGACY_STATUS = {
    QUEUED: "queued",
    RUNNING: "processing",
    DONE: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled",
    INTERRUPTED: "failed",
}


@dataclass
class Job:
    path: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    overrides: Dict[str, Any] = field(default_factory=dict)
    status: str = QUEUED
    percent: int = 0
    phase: str = ""
    output: Optional[str] = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.name:
            from pathlib import Path
            self.name = Path(self.path).name

    @property
    def seconds(self) -> Optional[int]:
        if self.started_at is None:
            return None
        end = self.finished_at or time.time()
        return int(end - self.started_at)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "overrides": self.overrides,
            "status": self.status,
            "percent": self.percent,
            "phase": self.phase,
            "output": self.output,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{key: value for key, value in data.items() if key in allowed})
