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


# --- Cleanup-rule editor ---


class CleanRulesIn(BaseModel):
    title_ops: list[dict] | None = None
    text_ops: list[dict] | None = None
    filter_min_chars: int | None = None
    filter_min_lines: int | None = None
    filter_min_arabic_ratio: float | None = None
    drop_if_url_dominated: bool | None = None


@router.get("/{slug}/sources/{source_name}/cleanup")
def get_cleanup_rules(slug: str, source_name: str):
    """Return the EFFECTIVE cleanup rules (type-defaults merged with overrides)."""
    from packages.engine.spec import default_clean_rules

    try:
        p = projects_store.get_project(slug)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    for s in p.config.get("sources") or []:
        if isinstance(s, dict) and s.get("name") == source_name:
            stype = s.get("type") or ""
            defaults = default_clean_rules(stype)
            override = s.get("clean_rules") or {}
            effective = {
                "title_ops": override.get("title_ops", defaults.title_ops),
                "text_ops": override.get("text_ops", defaults.text_ops),
                "filter_min_chars": override.get(
                    "filter_min_chars", defaults.filter_min_chars
                ),
                "filter_min_lines": override.get(
                    "filter_min_lines", defaults.filter_min_lines
                ),
                "filter_min_arabic_ratio": override.get(
                    "filter_min_arabic_ratio", defaults.filter_min_arabic_ratio
                ),
                "drop_if_url_dominated": override.get(
                    "drop_if_url_dominated", defaults.drop_if_url_dominated
                ),
            }
            return {
                "source": source_name,
                "source_type": stype,
                "rules": effective,
                "is_overridden": bool(override),
            }
    raise HTTPException(status_code=404, detail=f"source {source_name!r} not found in project")


@router.put("/{slug}/sources/{source_name}/cleanup")
def put_cleanup_rules(slug: str, source_name: str, body: CleanRulesIn):
    try:
        p = projects_store.get_project(slug)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    cfg = p.config
    found = False
    for s in cfg.get("sources") or []:
        if isinstance(s, dict) and s.get("name") == source_name:
            override = s.get("clean_rules") or {}
            updates = body.model_dump(exclude_none=True)
            override.update(updates)
            s["clean_rules"] = override
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"source {source_name!r} not found in project")
    projects_store.update_project(slug, cfg)
    return {"ok": True, "source": source_name, "applied": body.model_dump(exclude_none=True)}


@router.delete("/{slug}/sources/{source_name}/cleanup", status_code=204)
def reset_cleanup_rules(slug: str, source_name: str):
    """Reset overrides → fall back to type-defaults."""
    try:
        p = projects_store.get_project(slug)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))
    cfg = p.config
    found = False
    for s in cfg.get("sources") or []:
        if isinstance(s, dict) and s.get("name") == source_name:
            s.pop("clean_rules", None)
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"source {source_name!r} not found in project")
    projects_store.update_project(slug, cfg)


# --- Add source from wizard ---


class SubjectManifestIn(BaseModel):
    slug: str
    type: str = "poet"
    name_ar: str | None = None
    name_en: str | None = None
    aliases: list[str] = Field(default_factory=list)
    sources: dict[str, str | int] = Field(default_factory=dict)
    notes: str | None = None


class AddSourceIn(BaseModel):
    source: dict = Field(default_factory=dict)
    subject: SubjectManifestIn | None = None


@router.post("/{slug}/sources", status_code=201)
def add_source(slug: str, body: AddSourceIn):
    """Append a new source to the project config; optionally write/update
    a subject manifest under projects/<slug>/subjects/<slug>.yaml.

    This is what the add-source wizards (by-URL + by-name) call to persist
    the plan once the user has approved it."""
    import yaml

    from packages.api.settings import PROJECTS_DIR

    try:
        p = projects_store.get_project(slug)
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))

    src = dict(body.source or {})
    if not src.get("name"):
        raise HTTPException(status_code=400, detail="source.name is required")
    if not src.get("type"):
        raise HTTPException(status_code=400, detail="source.type is required")

    cfg = p.config
    existing_names = {s.get("name") for s in cfg.get("sources") or [] if isinstance(s, dict)}
    if src["name"] in existing_names:
        raise HTTPException(status_code=409, detail=f"source {src['name']!r} already exists")
    cfg.setdefault("sources", []).append(src)

    if body.subject:
        subj_dir = PROJECTS_DIR / slug / "subjects"
        subj_dir.mkdir(parents=True, exist_ok=True)
        subj_path = subj_dir / f"{body.subject.slug}.yaml"
        manifest = body.subject.model_dump(exclude_none=True)
        manifest.pop("slug", None)  # slug = filename, redundant in body
        subj_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        # link the source to this subject
        src["subject"] = body.subject.slug
        # ensure subjects list on project config
        subs = cfg.setdefault("subjects", [])
        if not any(
            isinstance(x, dict) and x.get("slug") == body.subject.slug for x in subs
        ):
            subs.append(
                {
                    "slug": body.subject.slug,
                    "type": body.subject.type,
                    "manifest": f"subjects/{body.subject.slug}.yaml",
                }
            )

    projects_store.update_project(slug, cfg)
    return {"ok": True, "source": src, "subject": body.subject.slug if body.subject else None}
