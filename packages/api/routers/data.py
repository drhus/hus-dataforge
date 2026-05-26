from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from packages.api.settings import DATA_DIR

router = APIRouter(prefix="/data", tags=["data"])


def _safe_jsonl(project: str, stage: str) -> Path:
    if not project.replace("-", "").isalnum() or stage not in {"raw", "clean", "export"}:
        raise HTTPException(status_code=400, detail="invalid project or stage")
    return DATA_DIR / project / stage / "records.jsonl"


@router.get("/{project}/{stage}")
def preview(
    project: str,
    stage: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    path = _safe_jsonl(project, stage)
    if not path.exists():
        return {"project": project, "stage": stage, "total": 0, "records": []}

    records: list[dict] = []
    total = 0
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            total += 1
            if i < offset or len(records) >= limit:
                if len(records) >= limit and i >= offset:
                    # keep counting to give caller a real total
                    pass
                continue
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                records.append({"_error": "malformed line", "_raw": line[:200]})
    return {"project": project, "stage": stage, "total": total, "records": records}
