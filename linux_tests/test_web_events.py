# -*- coding: utf-8 -*-
"""SSE bridge tests: replay, live events, job filter, heartbeat."""
import asyncio
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.events import EventHub  # noqa: E402
from web.events import SSEBridge  # noqa: E402


def _payload(frame: str) -> dict:
    data = [line[5:] for line in frame.splitlines() if line.startswith("data: ")]
    return json.loads(data[-1]) if data else {}


def test_replays_history_and_streams_new_events():
    async def scenario():
        hub = EventHub()
        hub.publish("job-a", "status", status="running")
        bridge = SSEBridge(hub, job_id="job-a")
        frames = bridge.frames()

        first = _payload(await asyncio.wait_for(frames.__anext__(), 2))
        assert first["kind"] == "status"

        threading.Thread(target=lambda: hub.publish("job-a", "log", line="hello")).start()
        second = _payload(await asyncio.wait_for(frames.__anext__(), 2))
        assert second["kind"] == "log" and second["line"] == "hello"

        bridge.close()
        await frames.aclose()

    asyncio.run(scenario())


def test_filters_other_jobs_and_sends_heartbeat():
    async def scenario():
        hub = EventHub()
        bridge = SSEBridge(hub, job_id="job-a", heartbeat_s=0.1)
        frames = bridge.frames()
        hub.publish("job-b", "log", line="other")
        frame = await asyncio.wait_for(frames.__anext__(), 2)
        assert frame.startswith(": ping")
        bridge.close()
        await frames.aclose()

    asyncio.run(scenario())
