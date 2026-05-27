"""Cron-style scheduler for project-level recurring jobs.

Schedules live in the project config under `schedules: list[Schedule]`. A
single systemd timer (or `dataforge schedule-tick` CLI) fires every minute,
evaluates which schedules are due, and enqueues the corresponding jobs.

Schema:
  schedules:
    - id: <slug>
      kind: scrape | clean | export
      cron: "0 4 * * *"          # standard 5-field cron
      enabled: true
      last_run_at: <iso>          # written by scheduler
      last_status: succeeded | failed
      next_run_at: <iso>          # cached for the dashboard

Why a custom mini-scheduler instead of RQ-Scheduler or APScheduler?
  - One systemd timer + one Python invocation is simpler than another
    daemon
  - State lives in the project config (file-based, git-friendly)
  - Easy to surface in the dashboard
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from croniter import croniter

from packages.api import projects_store
from packages.api.db import Job, engine
from packages.api.queue import get_queue
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

VALID_KINDS = {"scrape", "clean", "export"}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def list_schedules(project_slug: str) -> list[dict]:
    p = projects_store.get_project(project_slug)
    out: list[dict] = []
    for s in (p.config.get("schedules") or []):
        if not isinstance(s, dict):
            continue
        s = dict(s)
        # compute next run for display
        if s.get("cron") and s.get("enabled", True):
            try:
                base = _now()
                if s.get("last_run_at"):
                    try:
                        base = datetime.fromisoformat(s["last_run_at"])
                    except ValueError:
                        pass
                s["next_run_at"] = croniter(s["cron"], base).get_next(datetime).isoformat()
            except Exception as e:
                s["next_run_at"] = None
                s["_cron_error"] = str(e)
        out.append(s)
    return out


def upsert_schedule(project_slug: str, schedule: dict) -> dict:
    p = projects_store.get_project(project_slug)
    cfg = p.config
    schedules = cfg.setdefault("schedules", [])
    sid = schedule.get("id")
    if not sid:
        raise ValueError("schedule.id required")
    if schedule.get("kind") not in VALID_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_KINDS)}")
    try:
        croniter(schedule["cron"], _now())
    except Exception as e:
        raise ValueError(f"invalid cron: {e}")

    updated = False
    for i, s in enumerate(schedules):
        if isinstance(s, dict) and s.get("id") == sid:
            schedules[i] = {**s, **schedule}
            updated = True
            break
    if not updated:
        schedules.append({"enabled": True, **schedule})
    projects_store.update_project(project_slug, cfg)
    return schedule


def delete_schedule(project_slug: str, schedule_id: str) -> bool:
    p = projects_store.get_project(project_slug)
    cfg = p.config
    schedules = cfg.get("schedules") or []
    before = len(schedules)
    cfg["schedules"] = [s for s in schedules if not (isinstance(s, dict) and s.get("id") == schedule_id)]
    if len(cfg["schedules"]) == before:
        return False
    projects_store.update_project(project_slug, cfg)
    return True


def tick() -> dict:
    """One scheduler iteration: scan all projects, enqueue any due jobs.

    Idempotent — safe to call every minute from a systemd timer.
    Returns a summary for logging."""
    fired: list[dict] = []
    now = _now()
    for p in projects_store.list_projects():
        cfg = p.config
        schedules = cfg.get("schedules") or []
        if not schedules:
            continue
        dirty = False
        for s in schedules:
            if not isinstance(s, dict) or not s.get("enabled", True):
                continue
            cron_expr = s.get("cron")
            kind = s.get("kind")
            if not cron_expr or kind not in VALID_KINDS:
                continue
            # When was the previous expected fire?
            base = now
            try:
                last = (
                    datetime.fromisoformat(s["last_run_at"])
                    if s.get("last_run_at")
                    else now.replace(hour=0, minute=0, second=0, microsecond=0)
                )
            except Exception:
                last = now
            try:
                it = croniter(cron_expr, last)
                next_due = it.get_next(datetime)
            except Exception as e:
                log.warning("schedule %s/%s cron parse failed: %s", p.slug, s.get("id"), e)
                continue
            if next_due <= now:
                # Enqueue the job
                eng = engine()
                with Session(eng) as session:
                    job = Job(project=p.slug, kind=kind, status="queued")
                    session.add(job)
                    session.commit()
                    try:
                        from packages.api.jobs_runner import run_clean, run_export, run_scrape

                        runners = {"scrape": run_scrape, "clean": run_clean, "export": run_export}
                        rq_job = get_queue().enqueue(
                            runners[kind], p.slug, job.id, job_timeout=7200
                        )
                        job.rq_job_id = rq_job.id
                    except Exception as e:
                        job.status = "failed"
                        job.message = f"scheduler enqueue failed: {e}"
                    session.commit()
                s["last_run_at"] = now.isoformat()
                s["last_status"] = "enqueued"
                s["last_job_id"] = job.id
                dirty = True
                fired.append({"project": p.slug, "schedule": s.get("id"), "kind": kind, "job": job.id})
        if dirty:
            projects_store.update_project(p.slug, cfg)
    return {"fired": fired, "now": now.isoformat()}


__all__ = ["list_schedules", "upsert_schedule", "delete_schedule", "tick"]
