"""Stub job runners. Real implementations land with the Scraping/Cleaning
milestones — this exists so the dashboard has something to schedule and watch."""
from __future__ import annotations

import time


def run_stub(project: str, kind: str, duration_sec: int = 5) -> dict:
    for _ in range(duration_sec):
        time.sleep(1)
    return {"project": project, "kind": kind, "ok": True}
