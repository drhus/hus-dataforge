"""Schedules CRUD endpoints (under /projects/<slug>/schedules) plus
auto-pipeline (chain) configuration."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.api import projects_store, scheduler
from packages.api.db import Job, engine
from packages.api.projects_store import ProjectError

router = APIRouter(prefix="/projects", tags=["schedules"])
# Separate router for global schedule operations (presets, etc.) that don't
# live under a project slug — keeps them from colliding with /projects/{slug}
# validation, which rejects names with underscores.
global_router = APIRouter(prefix="/schedule-presets", tags=["schedules"])


class ScheduleIn(BaseModel):
    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    kind: str = Field(..., description="scrape | clean | export")
    cron: str = Field(..., description="standard 5-field cron expression")
    enabled: bool = True


class PipelineIn(BaseModel):
    auto_pipeline: bool | list[str] = Field(
        ...,
        description=(
            "true (chain all stages), false (never chain), "
            "or list of stages to chain into, e.g. ['clean'] = scrape→clean "
            "but not clean→export"
        ),
    )


@router.get("/{slug}/schedules")
def list_schedules(slug: str):
    try:
        return {"project": slug, "schedules": scheduler.list_schedules(slug)}
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{slug}/schedules")
def upsert(slug: str, body: ScheduleIn):
    try:
        return scheduler.upsert_schedule(slug, body.model_dump())
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{slug}/schedules/{schedule_id}", status_code=204)
def delete(slug: str, schedule_id: str):
    try:
        deleted = scheduler.delete_schedule(slug, schedule_id)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")


@router.post("/_scheduler/tick")
def tick():
    """Manual scheduler tick — useful for testing. The systemd timer
    `dataforge-scheduler.timer` calls this every minute in production."""
    return scheduler.tick()


@router.get("/{slug}/pipeline")
def get_pipeline(slug: str):
    """Return the auto-pipeline (chain) config + last-run timestamps for
    each stage so the dashboard can show 'scraped 2h ago, cleaned 2h ago,
    exported 2h ago' next to the chain toggle."""
    try:
        cfg = projects_store.get_project(slug).config
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))

    chain = cfg.get("auto_pipeline", True)
    eng = engine()
    last_run: dict[str, dict | None] = {"scrape": None, "clean": None, "export": None}
    last_chained_at: str | None = None
    with Session(eng) as session:
        for kind in last_run:
            stmt = (
                select(Job)
                .where(Job.project == slug)
                .where(Job.kind == kind)
                .order_by(Job.created_at.desc())
                .limit(1)
            )
            job = session.scalars(stmt).first()
            if job:
                last_run[kind] = {
                    "id": job.id,
                    "status": job.status,
                    "created_at": job.created_at.isoformat(),
                    "updated_at": job.updated_at.isoformat(),
                    "chained": (job.message or "").startswith('{"chain":"auto"}'),
                }
                if (
                    kind == "export"
                    and job.status == "succeeded"
                    and last_chained_at is None
                ):
                    last_chained_at = job.updated_at.isoformat()
    return {
        "project": slug,
        "auto_pipeline": chain,
        "last_run": last_run,
        "last_full_pipeline_at": last_chained_at,
    }


@router.put("/{slug}/pipeline")
def put_pipeline(slug: str, body: PipelineIn):
    """Update the auto_pipeline (chain) config for a project."""
    try:
        cfg = projects_store.get_project(slug).config
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    cfg["auto_pipeline"] = body.auto_pipeline
    projects_store.update_project(slug, cfg)
    return {"project": slug, "auto_pipeline": body.auto_pipeline}


# Curated cron presets — sensible defaults for a new project.
_SCHEDULE_PRESETS = {
    "daily-scrape": {
        "id": "daily-scrape",
        "kind": "scrape",
        "cron": "0 4 * * *",  # 04:00 UTC every day
        "enabled": True,
    },
    "weekly-scrape": {
        "id": "weekly-scrape",
        "kind": "scrape",
        "cron": "0 4 * * 0",  # 04:00 UTC every Sunday
        "enabled": True,
    },
    "hourly-scrape": {
        "id": "hourly-scrape",
        "kind": "scrape",
        "cron": "0 * * * *",  # top of every hour
        "enabled": True,
    },
}


@global_router.get("")
def list_schedule_presets():
    """Available schedule presets — the dashboard lists these as one-click
    'Add daily 04:00 scrape' buttons."""
    return {
        "presets": [
            {**v, "name": k, "description": _preset_description(k)}
            for k, v in _SCHEDULE_PRESETS.items()
        ]
    }


def _preset_description(key: str) -> str:
    return {
        "daily-scrape": "Run a scrape every day at 04:00 UTC",
        "weekly-scrape": "Run a scrape every Sunday at 04:00 UTC",
        "hourly-scrape": "Run a scrape at the top of every hour",
    }.get(key, "")


@router.post("/{slug}/schedules/preset/{preset}")
def apply_preset(slug: str, preset: str):
    """Apply a named preset to this project's schedules. Idempotent —
    re-applying just upserts."""
    if preset not in _SCHEDULE_PRESETS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown preset {preset!r}; see /projects/_schedule_presets",
        )
    try:
        return scheduler.upsert_schedule(slug, dict(_SCHEDULE_PRESETS[preset]))
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
