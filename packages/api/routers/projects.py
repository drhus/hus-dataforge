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
