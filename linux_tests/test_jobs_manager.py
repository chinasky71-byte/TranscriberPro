# -*- coding: utf-8 -*-
"""Job manager tests with a fake runner (no subprocess, no GPU)."""
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.manager import JobManager  # noqa: E402
from core.jobs.models import CANCELLED, DONE, INTERRUPTED, QUEUED, RUNNING, Job  # noqa: E402
from core.jobs.persistence import load_jobs, save_jobs  # noqa: E402


class FakeRunner:
    def __init__(self, block: bool = False, fail: bool = False):
        self.block = block
        self.fail = fail
        self.calls = []

    def run(self, video, target_language, files_processed, log_path,
            on_line=None, on_event=None, cancel_event=None):
        self.calls.append((str(video), target_language))
        if on_event:
            on_event("phase", {"name": "asr"})
            on_event("bar", {"phase": "asr", "pct": 40})
        if on_line:
            on_line("4. Audio transcription...")
        if self.block:
            deadline = time.time() + 5
            while not cancel_event.is_set() and time.time() < deadline:
                time.sleep(0.01)
        if cancel_event is not None and cancel_event.is_set():
            return {"ok": False, "cancelled": True, "error": "cancelled", "output": None}
        if self.fail:
            return {"ok": False, "error": "boom", "cancelled": False, "output": None}
        if log_path:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(log_path).write_text("log\n", encoding="utf-8")
        return {"ok": True, "output": f"{video}.srt", "error": None, "cancelled": False}


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_queue_runs_jobs_one_after_another(tmp_path):
    runner = FakeRunner()
    manager = JobManager(runner=runner, log_dir=tmp_path / "logs")
    first = manager.add("/tmp/a.mp4")
    second = manager.add("/tmp/b.mp4", {"target_language": "eng"})

    manager.start()
    manager.wait()

    jobs = {job["id"]: job for job in manager.snapshot()}
    assert jobs[first.id]["status"] == DONE
    assert jobs[first.id]["percent"] == 100
    assert jobs[second.id]["status"] == DONE
    assert runner.calls == [("/tmp/a.mp4", "ita"), ("/tmp/b.mp4", "eng")]
    assert manager.state == "finished"
    assert (tmp_path / "logs" / f"{first.id}.log").exists()


def test_failure_marks_job_failed_and_queue_continues(tmp_path):
    runner = FakeRunner(fail=True)
    manager = JobManager(runner=runner, log_dir=tmp_path)
    manager.add("/tmp/a.mp4")
    manager.add("/tmp/b.mp4")
    manager.start()
    manager.wait()
    assert [job["status"] for job in manager.snapshot()] == ["failed", "failed"]
    assert manager.legacy_snapshot()["failed"] == 2


def test_cancel_running_job(tmp_path):
    runner = FakeRunner(block=True)
    manager = JobManager(runner=runner)
    job = manager.add("/tmp/a.mp4")
    manager.start()
    assert _wait_for(lambda: manager.snapshot()[0]["status"] == RUNNING)
    assert manager.cancel(job.id) is True
    manager.wait()
    assert manager.snapshot()[0]["status"] == CANCELLED


def test_cancel_and_remove_queued_job():
    manager = JobManager(runner=FakeRunner())
    job = manager.add("/tmp/a.mp4")
    assert manager.cancel(job.id) is True
    assert manager.snapshot()[0]["status"] == CANCELLED
    # a terminal job cannot be removed
    assert manager.remove(job.id) is False

    other = manager.add("/tmp/b.mp4")
    assert manager.remove(other.id) is True
    assert [item["id"] for item in manager.snapshot()] == [job.id]


def test_events_are_recorded_for_reconnect():
    manager = JobManager(runner=FakeRunner())
    manager.add("/tmp/a.mp4")
    manager.start()
    manager.wait()
    events = manager.hub.history(manager.snapshot()[0]["id"])
    kinds = [event["kind"] for event in events]
    assert "created" in kinds
    assert "progress" in kinds
    assert "status" in kinds
    assert any(event.get("event_kind") == "bar" for event in events)


def test_legacy_snapshot_schema():
    manager = JobManager(runner=FakeRunner())
    manager.add("/tmp/a.mp4")
    manager.start()
    manager.wait()
    snap = manager.legacy_snapshot()
    assert snap["version"] == 1
    assert snap["total"] == 1 and snap["completed"] == 1
    assert snap["files"][0]["status"] == "completed"
    assert snap["files"][0]["percent"] == 100
    assert snap["current"] is None


def test_persistence_marks_running_as_interrupted(tmp_path):
    path = tmp_path / "jobs.json"
    save_jobs(path, [Job(path="/tmp/x.mp4", status=RUNNING)])
    jobs = load_jobs(path)
    assert len(jobs) == 1
    assert jobs[0].status == INTERRUPTED


def test_persistence_keeps_queued_jobs(tmp_path):
    path = tmp_path / "jobs.json"
    manager = JobManager(persist_path=path, runner=FakeRunner())
    manager.add("/tmp/a.mp4")
    reloaded = JobManager(persist_path=path, runner=FakeRunner())
    assert len(reloaded.snapshot()) == 1
    assert reloaded.snapshot()[0]["status"] == QUEUED
