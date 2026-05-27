from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.api import projects_store
from packages.api.projects_store import ProjectError

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectIn(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    config: dict = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    config: dict


@router.get("")
def list_projects():
    return [p.to_dict() for p in projects_store.list_projects()]


@router.post("", status_code=201)
def create_project(body: ProjectIn):
    try:
        return projects_store.create_project(body.slug, body.config).to_dict()
    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{slug}")
def get_project(slug: str):
    try:
        return projects_store.get_project(slug).to_dict()
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{slug}")
def update_project(slug: str, body: ProjectUpdate):
    try:
        return projects_store.update_project(slug, body.config).to_dict()
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{slug}", status_code=204)
def delete_project(slug: str):
    try:
        projects_store.delete_project(slug)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Categorize-rule editor (surgical updates without resending whole config) ---


class CategorizeRuleIn(BaseModel):
    text_contains_any: list[str]
    set_category: str


class CategorizeUpdate(BaseModel):
    rules: list[CategorizeRuleIn] = Field(default_factory=list)
    primary_category: str | None = None
    fallback_category: str | None = None


@router.get("/{slug}/sources/{source_name}/categorize")
def get_categorize(slug: str, source_name: str):
    try:
        p = projects_store.get_project(slug)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    for s in p.config.get("sources") or []:
        if isinstance(s, dict) and s.get("name") == source_name:
            return {
                "source": source_name,
                "rules": s.get("categorize") or [],
                "primary_category": s.get("primary_category") or "poetry",
                "fallback_category": s.get("fallback_category"),
            }
    raise HTTPException(status_code=404, detail=f"source {source_name!r} not found in project")


@router.put("/{slug}/sources/{source_name}/categorize")
def put_categorize(slug: str, source_name: str, body: CategorizeUpdate):
    try:
        p = projects_store.get_project(slug)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    cfg = p.config
    found = False
    for s in cfg.get("sources") or []:
        if isinstance(s, dict) and s.get("name") == source_name:
            s["categorize"] = [r.model_dump() for r in body.rules]
            if body.primary_category is not None:
                s["primary_category"] = body.primary_category
            if body.fallback_category is not None:
                s["fallback_category"] = body.fallback_category
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"source {source_name!r} not found in project")
    projects_store.update_project(slug, cfg)
    return {"ok": True, "source": source_name, "rules": body.rules}
