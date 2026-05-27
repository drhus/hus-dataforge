"""Curation endpoints — bulk actions on records."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.api import curation
from packages.api.projects_store import ProjectError, get_project

router = APIRouter(prefix="/projects", tags=["curation"])


class CurationAction(BaseModel):
    id: str
    action: str
    category: str | None = None
    subject: str | None = None
    by: str | None = None


class CurationBatch(BaseModel):
    actions: list[CurationAction] = Field(..., min_length=1)


@router.get("/{slug}/curation")
def get_curation(slug: str, limit: int = 200):
    try:
        get_project(slug)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "project": slug,
        "actions": curation.list_actions(slug, limit=limit),
        "overlay": curation.load_overlay(slug),
    }


@router.post("/{slug}/curation", status_code=201)
def post_curation(slug: str, body: CurationBatch):
    try:
        get_project(slug)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    bad = [a for a in body.actions if a.action not in curation.VALID_ACTIONS]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"unknown action(s): {[a.action for a in bad]}. "
            f"valid: {sorted(curation.VALID_ACTIONS)}",
        )
    n = curation.append_actions(slug, [a.model_dump(exclude_none=True) for a in body.actions])
    return {"ok": True, "written": n}
