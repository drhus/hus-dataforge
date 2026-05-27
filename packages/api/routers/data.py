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
    run_id: int | None = Query(None, description="filter by lineage run_id"),
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
            if needle and needle not in line.lower():
                continue
            if run_id is not None:
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = parsed.get("run_id") or parsed.get("_run_id")
                if rid != run_id:
                    continue
                total += 1
                if total <= offset:
                    continue
                if len(records) >= limit:
                    continue
                records.append(parsed)
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


def _load_subject_manifests(project: str) -> list[dict]:
    """Read subject + legacy poet manifests, returning a unified subject list.

    When the same slug exists in both `poets/` and `subjects/`, fields from
    the legacy file are kept as the *base* and the subjects/ file overrides
    field-by-field (so a new wizard-written manifest doesn't lose the rich
    metadata from the original)."""
    import yaml

    from packages.api.settings import PROJECTS_DIR

    _safe_segment(project)
    subjects: dict[str, dict] = {}
    # Legacy poets dir → implicit type=poet
    pdir = PROJECTS_DIR / project / "poets"
    if pdir.exists():
        for f in sorted(pdir.glob("*.yaml")):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                data.setdefault("type", "poet")
                data["slug"] = f.stem
                subjects[f.stem] = data
            except Exception as e:
                subjects[f.stem] = {"slug": f.stem, "_error": str(e)}
    # New canonical subjects dir — MERGE field-by-field, non-empty wins
    sdir = PROJECTS_DIR / project / "subjects"
    if sdir.exists():
        for f in sorted(sdir.glob("*.yaml")):
            try:
                new_data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                base = subjects.get(f.stem, {})
                merged = dict(base)
                for k, v in new_data.items():
                    # only override if the new value is non-empty/non-None
                    if v in (None, "", [], {}):
                        continue
                    if k == "sources" and isinstance(v, dict) and isinstance(merged.get(k), dict):
                        merged[k] = {**merged[k], **v}
                    else:
                        merged[k] = v
                merged["slug"] = f.stem
                merged.setdefault("type", "poet")
                subjects[f.stem] = merged
            except Exception as e:
                subjects[f.stem] = {"slug": f.stem, "_error": str(e)}
    return list(subjects.values())


@router.get("/{project}/subjects")
def list_subjects(project: str):
    """Return all subject manifests (poet | topic | person | site)."""
    return {"project": project, "subjects": _load_subject_manifests(project)}


@router.get("/{project}/poets")
def list_poets(project: str):
    """Legacy alias — returns ALL subjects (not just type=poet) so wizard-written
    manifests with type=person|topic|site still show. Kept as `/poets` for
    backward compat with the dashboard project page."""
    subs = _load_subject_manifests(project)
    return {"project": project, "poets": subs}
