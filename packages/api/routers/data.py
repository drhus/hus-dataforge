from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from packages.api.settings import DATA_DIR

router = APIRouter(prefix="/data", tags=["data"])

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


def _safe_segment(s: str) -> str:
    if not _SAFE_SEGMENT.match(s):
        raise HTTPException(status_code=400, detail=f"invalid path segment: {s!r}")
    return s


def _stage_dir(project: str, stage: str) -> Path:
    _safe_segment(project)
    if stage not in {"raw", "clean", "export"}:
        raise HTTPException(status_code=400, detail="stage must be raw|clean|export")
    return DATA_DIR / project / stage


@router.get("/{project}/sources")
def list_sources(project: str, stage: str = Query("raw", pattern="^(raw|clean|export)$")):
    """Enumerate available JSONL files in a stage with row counts."""
    d = _stage_dir(project, stage)
    if not d.exists():
        return {"project": project, "stage": stage, "sources": []}
    out: list[dict] = []
    for p in sorted(d.glob("*.jsonl")):
        if p.name.startswith("_"):
            continue
        # quick line count without loading file
        with p.open("rb") as fh:
            n = sum(1 for _ in fh)
        out.append({"name": p.stem, "count": n, "bytes": p.stat().st_size})
    return {"project": project, "stage": stage, "sources": out}


@router.get("/{project}/{stage}/{source}")
def list_records(
    project: str,
    stage: str,
    source: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    q: str | None = Query(None, description="full-text filter (case-insensitive)"),
):
    d = _stage_dir(project, stage)
    _safe_segment(source)
    path = d / f"{source}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no such source: {source}")

    needle = q.lower() if q else None
    records: list[dict] = []
    total = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if needle:
                if needle not in line.lower():
                    continue
            total += 1
            if total <= offset:
                continue
            if len(records) >= limit:
                continue  # keep counting matches
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                records.append({"_error": "malformed line", "_raw": line[:200]})
    return {
        "project": project,
        "stage": stage,
        "source": source,
        "total": total,
        "offset": offset,
        "limit": limit,
        "records": records,
    }


@router.get("/{project}/poets")
def list_poets(project: str):
    """Return poet manifests for a project (from projects/<slug>/poets/*.yaml)."""
    import yaml

    from packages.api.settings import PROJECTS_DIR

    _safe_segment(project)
    pdir = PROJECTS_DIR / project / "poets"
    if not pdir.exists():
        return {"project": project, "poets": []}

    poets: list[dict] = []
    for f in sorted(pdir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            data["slug"] = f.stem
            poets.append(data)
        except Exception as e:
            poets.append({"slug": f.stem, "_error": str(e)})
    return {"project": project, "poets": poets}
