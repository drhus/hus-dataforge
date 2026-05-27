"""Schedules CRUD endpoints (under /projects/<slug>/schedules)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.api import scheduler
from packages.api.projects_store import ProjectError

router = APIRouter(prefix="/projects", tags=["schedules"])


class ScheduleIn(BaseModel):
    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    kind: str = Field(..., description="scrape | clean | export")
    cron: str = Field(..., description="standard 5-field cron expression")
    enabled: bool = True


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
