"""Job runners executed inside the RQ worker. One entrypoint per job kind."""
from __future__ import annotations

import logging

from packages.api.db import Job, engine
from packages.engine import run_scrape as engine_run_scrape
from packages.engine.progress import DBProgress
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def run_scrape(project: str, job_id: int) -> dict:
    eng = engine()
    with Session(eng) as session:
        job = session.get(Job, job_id)
        if not job:
            raise RuntimeError(f"job {job_id} not found in DB")
        job.status = "running"
        session.commit()
        progress = DBProgress(session, job_id)
        try:
            result = engine_run_scrape(project, progress=progress)
            return result
        finally:
            progress.finish()


def run_stub(project: str, kind: str, duration_sec: int = 5) -> dict:
    """Kept for clean/export until real runners land."""
    import time

    for _ in range(duration_sec):
        time.sleep(1)
    return {"project": project, "kind": kind, "ok": True}
