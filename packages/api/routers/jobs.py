from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from rq.job import Job as RqJob
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.api import projects_store
from packages.api.db import Job, get_session
from packages.api.jobs_runner import run_clean, run_export, run_scrape, run_stub
from packages.api.projects_store import ProjectError
from packages.api.queue import get_queue, get_redis

router = APIRouter(prefix="/jobs", tags=["jobs"])

ALLOWED_KINDS = {"scrape", "clean", "export"}
TERMINAL_STATUSES = {"succeeded", "failed"}
RQ_TO_DB_STATUS = {
    "queued": "queued",
    "started": "running",
    "deferred": "queued",
    "finished": "succeeded",
    "failed": "failed",
    "stopped": "failed",
    "scheduled": "queued",
    "canceled": "failed",
}


class JobIn(BaseModel):
    project: str
    kind: str = Field(..., description="scrape | clean | export")
    duration_sec: int = Field(5, ge=1, le=300, description="for the stub runner")
    force: bool = Field(
        False, description="scrape: re-fetch all sources from scratch (ignore incremental checkpoints)"
    )


def _serialize(job: Job) -> dict:
    return {
        "id": job.id,
        "project": job.project,
        "kind": job.kind,
        "status": job.status,
        "rq_job_id": job.rq_job_id,
        "message": job.message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _sync_with_rq(jobs: list[Job], session: Session) -> None:
    """Refresh DB status for any non-terminal job by reading its RQ state."""
    dirty = False
    for job in jobs:
        if job.status in TERMINAL_STATUSES or not job.rq_job_id:
            continue
        try:
            rj = RqJob.fetch(job.rq_job_id, connection=get_redis())
            new_status = RQ_TO_DB_STATUS.get(rj.get_status(refresh=True), job.status)
            if new_status != job.status:
                job.status = new_status
                job.updated_at = datetime.utcnow()
                dirty = True
        except Exception:
            continue
    if dirty:
        session.commit()


@router.get("")
def list_jobs(project: str | None = None, session: Session = Depends(get_session)):
    stmt = select(Job).order_by(Job.created_at.desc()).limit(200)
    if project:
        stmt = stmt.where(Job.project == project)
    jobs = list(session.scalars(stmt))
    _sync_with_rq(jobs, session)
    return [_serialize(j) for j in jobs]


@router.post("", status_code=201)
def enqueue_job(body: JobIn, session: Session = Depends(get_session)):
    if body.kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(ALLOWED_KINDS)}")
    try:
        projects_store.get_project(body.project)
    except ProjectError:
        raise HTTPException(status_code=404, detail=f"project not found: {body.project}")

    job = Job(project=body.project, kind=body.kind, status="queued")
    session.add(job)
    session.commit()

    try:
        if body.kind == "scrape":
            rq_job = get_queue().enqueue(
                run_scrape, body.project, job.id, body.force, job_timeout=7200
            )
            if body.force:
                job.message = '{"mode": "force_full"}'
        elif body.kind == "clean":
            rq_job = get_queue().enqueue(run_clean, body.project, job.id, job_timeout=3600)
        elif body.kind == "export":
            rq_job = get_queue().enqueue(run_export, body.project, job.id, job_timeout=1800)
        else:
            rq_job = get_queue().enqueue(
                run_stub, body.project, body.kind, body.duration_sec, job_timeout=600
            )
        job.rq_job_id = rq_job.id
        job.status = "queued"
    except Exception as e:
        job.status = "failed"
        job.message = f"enqueue failed: {e}"
    job.updated_at = datetime.utcnow()
    session.commit()
    return _serialize(job)


@router.get("/{job_id}")
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    _sync_with_rq([job], session)
    return _serialize(job)
