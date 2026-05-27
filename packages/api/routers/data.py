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


def _source_files(d: Path) -> list[Path]:
    """List source files in a stage dir: .jsonl (raw/clean) + .parquet (export).
    Sidecar/manifest files (starting with `_`) are excluded."""
    files: dict[str, Path] = {}
    for ext in ("*.jsonl", "*.parquet"):
        for p in d.glob(ext):
            if p.name.startswith("_"):
                continue
            # If both jsonl + parquet exist for same stem, prefer jsonl
            files.setdefault(p.stem, p)
    return [files[k] for k in sorted(files)]


def _count_records(p: Path) -> int:
    if p.suffix == ".jsonl":
        with p.open("rb") as fh:
            return sum(1 for _ in fh)
    if p.suffix == ".parquet":
        import pyarrow.parquet as pq

        try:
            return pq.ParquetFile(p).metadata.num_rows
        except Exception:
            return 0
    return 0


@router.get("/{project}/sources")
def list_sources(project: str, stage: str = Query("raw", pattern="^(raw|clean|export)$")):
    """Enumerate source files in a stage with row counts.
    Supports .jsonl (raw/clean) and .parquet (export)."""
    d = _stage_dir(project, stage)
    if not d.exists():
        return {"project": project, "stage": stage, "sources": []}
    out: list[dict] = []
    for p in _source_files(d):
        out.append(
            {
                "name": p.stem,
                "count": _count_records(p),
                "bytes": p.stat().st_size,
                "format": p.suffix.lstrip("."),
            }
        )
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
    topic: str | None = Query(None, description="filter to records whose meta.topics contains this"),
    meter: str | None = Query(None, description="filter by meter (e.g. 'البسيط')"),
    category: str | None = Query(None, description="filter by category"),
):
    d = _stage_dir(project, stage)
    _safe_segment(source)
    # Try jsonl first, then parquet (export stage)
    path = d / f"{source}.jsonl"
    if not path.exists():
        path = d / f"{source}.parquet"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no such source: {source}")

    if path.suffix == ".parquet":
        return _list_parquet_records(project, stage, source, path, offset, limit, q, run_id)

    needle = q.lower() if q else None
    records: list[dict] = []
    total = 0
    needs_parse = run_id is not None or topic or meter or category
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if needle and needle not in line.lower():
                continue
            if needs_parse:
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if run_id is not None:
                    rid = parsed.get("run_id") or parsed.get("_run_id")
                    if rid != run_id:
                        continue
                if category and parsed.get("category") != category:
                    continue
                meta_obj = parsed.get("meta") or {}
                if topic:
                    t = meta_obj.get("topics") or ""
                    if topic not in str(t):
                        continue
                if meter:
                    m = meta_obj.get("meter") or ""
                    if meter not in str(m):
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


@router.get("/{project}/{stage}/{source}/facets")
def list_facets(project: str, stage: str, source: str):
    """Aggregate counts for topics / meter / categories — drives the dashboard
    facet filters. Reads the source file once and tallies."""
    d = _stage_dir(project, stage)
    _safe_segment(source)
    path = d / f"{source}.jsonl"
    if not path.exists():
        path = d / f"{source}.parquet"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no such source: {source}")

    from collections import Counter

    topics: Counter = Counter()
    meters: Counter = Counter()
    categories: Counter = Counter()

    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        tbl = pq.read_table(path)
        for row in tbl.to_pylist():
            cat = row.get("category")
            if cat:
                categories[cat] += 1
            meta = {}
            mj = row.get("meta_json")
            if mj:
                try:
                    meta = json.loads(mj)
                except (TypeError, json.JSONDecodeError):
                    pass
            for t in str(meta.get("topics") or "").split("|"):
                t = t.strip()
                if t:
                    topics[t] += 1
            for m in str(meta.get("meter") or "").split("|"):
                m = m.strip()
                if m:
                    meters[m] += 1
    else:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cat = r.get("category")
                if cat:
                    categories[cat] += 1
                meta = r.get("meta") or {}
                for t in str(meta.get("topics") or "").split("|"):
                    t = t.strip()
                    if t:
                        topics[t] += 1
                for m in str(meta.get("meter") or "").split("|"):
                    m = m.strip()
                    if m:
                        meters[m] += 1
    return {
        "project": project,
        "stage": stage,
        "source": source,
        "topics": topics.most_common(50),
        "meters": meters.most_common(20),
        "categories": categories.most_common(20),
    }


def _list_parquet_records(
    project: str,
    stage: str,
    source: str,
    path: Path,
    offset: int,
    limit: int,
    q: str | None,
    run_id: int | None,
) -> dict:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    rows = table.to_pylist()
    needle = q.lower() if q else None

    matched: list[dict] = []
    for r in rows:
        if needle:
            blob = json.dumps(r, ensure_ascii=False).lower()
            if needle not in blob:
                continue
        if run_id is not None:
            rid = r.get("run_id") or r.get("_run_id")
            if rid != run_id:
                continue
        # decode meta_json column for readability
        if "meta_json" in r and "meta" not in r:
            try:
                r["meta"] = json.loads(r.pop("meta_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                pass
        matched.append(r)
    total = len(matched)
    page = matched[offset : offset + limit]
    return {
        "project": project,
        "stage": stage,
        "source": source,
        "total": total,
        "offset": offset,
        "limit": limit,
        "records": page,
        "format": "parquet",
    }


@router.get("/{project}/poets")
def list_poets(project: str):
    """Legacy alias — returns ALL subjects (not just type=poet) so wizard-written
    manifests with type=person|topic|site still show. Kept as `/poets` for
    backward compat with the dashboard project page."""
    subs = _load_subject_manifests(project)
    return {"project": project, "poets": subs}
