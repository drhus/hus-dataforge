"""Job runners executed inside the RQ worker. One entrypoint per job kind.

Auto-pipeline chain: when a runner finishes successfully, it consults the
project's `auto_pipeline` config and may enqueue the next stage
(scrape→clean→export). De-duped: if an active job of the next stage is
already queued/running for the project, the chain skips. The user can
disable the chain per-project with `auto_pipeline: false` in config."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.api import projects_store
from packages.api.db import Job, engine
from packages.engine import run_scrape as engine_run_scrape
from packages.engine.progress import DBProgress
from packages.export import run_export as export_run_export
from packages.pipeline import run_clean as pipeline_run_clean

log = logging.getLogger(__name__)

# Stage successor map: scrape→clean→export→(terminal)
_NEXT_STAGE: dict[str, str] = {"scrape": "clean", "clean": "export"}


def _auto_pipeline_includes(project: str, stage: str) -> bool:
    """Decide whether the chain should advance to `stage` for `project`.

    Config semantics for `auto_pipeline`:
      - omitted or `true` → chain ALL stages (default)
      - `false`           → never chain
      - list of stage names → chain only those (e.g. ["clean"] = scrape→clean
        but not clean→export)
    """
    try:
        cfg = projects_store.get_project(project).config
    except Exception as e:
        log.warning("chain: could not load project %s config: %s", project, e)
        return False
    chain = cfg.get("auto_pipeline", True)
    if chain is False:
        return False
    if chain is True or chain is None:
        return True
    if isinstance(chain, list):
        return stage in chain
    return True


def _has_active_job(session: Session, project: str, kind: str) -> Job | None:
    """Return any queued-or-running job of `kind` for `project`, else None."""
    stmt = (
        select(Job)
        .where(Job.project == project)
        .where(Job.kind == kind)
        .where(Job.status.in_(["queued", "running"]))
    )
    return session.scalars(stmt).first()


def _maybe_enqueue_next(project: str, just_finished: str) -> int | None:
    """Enqueue the next pipeline stage if the chain is enabled and no active
    job of that stage already exists. Returns the new job_id, or None."""
    next_stage = _NEXT_STAGE.get(just_finished)
    if next_stage is None:
        return None
    if not _auto_pipeline_includes(project, next_stage):
        return None

    eng = engine()
    with Session(eng) as session:
        existing = _has_active_job(session, project, next_stage)
        if existing:
            log.info(
                "chain: skip %s for %s — job %d already %s",
                next_stage, project, existing.id, existing.status,
            )
            return None
        job = Job(project=project, kind=next_stage, status="queued")
        session.add(job)
        session.commit()
        try:
            from packages.api.queue import get_queue

            runners = {"clean": run_clean, "export": run_export}
            rq_job = get_queue().enqueue(
                runners[next_stage], project, job.id, job_timeout=7200
            )
            job.rq_job_id = rq_job.id
            job.message = '{"chain":"auto"}'
            session.commit()
            log.info(
                "chain: enqueued %s for %s (job=%d, parent=%s)",
                next_stage, project, job.id, just_finished,
            )
            return job.id
        except Exception as e:
            job.status = "failed"
            job.message = f"chain enqueue failed: {e}"
            session.commit()
            log.warning("chain: enqueue failed for %s/%s: %s", project, next_stage, e)
            return None


def run_scrape(project: str, job_id: int, force: bool = False) -> dict:
    eng = engine()
    with Session(eng) as session:
        job = session.get(Job, job_id)
        if not job:
            raise RuntimeError(f"job {job_id} not found in DB")
        job.status = "running"
        session.commit()
        progress = DBProgress(session, job_id)
        try:
            result = engine_run_scrape(
                project, progress=progress, run_id=job_id, force=force
            )
        finally:
            progress.finish()
    _maybe_enqueue_next(project, "scrape")
    return result


def run_clean(project: str, job_id: int) -> dict:
    eng = engine()
    with Session(eng) as session:
        job = session.get(Job, job_id)
        if not job:
            raise RuntimeError(f"job {job_id} not found in DB")
        job.status = "running"
        session.commit()
        progress = DBProgress(session, job_id)
        try:
            result = pipeline_run_clean(project, progress=progress)
        finally:
            progress.finish()
    _maybe_enqueue_next(project, "clean")
    return result


def run_export(project: str, job_id: int) -> dict:
    eng = engine()
    with Session(eng) as session:
        job = session.get(Job, job_id)
        if not job:
            raise RuntimeError(f"job {job_id} not found in DB")
        job.status = "running"
        session.commit()
        progress = DBProgress(session, job_id)
        try:
            return export_run_export(project, progress=progress)
        finally:
            progress.finish()


def run_stub(project: str, kind: str, duration_sec: int = 5) -> dict:
    """Kept for any not-yet-implemented job kind."""
    import time

    for _ in range(duration_sec):
        time.sleep(1)
    return {"project": project, "kind": kind, "ok": True}
