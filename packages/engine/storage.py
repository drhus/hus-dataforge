"""Raw HTML cache + JSONL record writer, both rooted at data/<slug>/."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from packages.api.settings import DATA_DIR


def project_data_dir(slug: str) -> Path:
    d = DATA_DIR / slug
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "clean").mkdir(parents=True, exist_ok=True)
    (d / "export").mkdir(parents=True, exist_ok=True)
    return d


def content_hash(body: str | bytes) -> str:
    b = body.encode("utf-8") if isinstance(body, str) else body
    return hashlib.sha256(b).hexdigest()


def write_raw(slug: str, body: str, url: str) -> tuple[Path, str]:
    """Store raw HTML keyed by content hash. Returns (path, hash)."""
    h = content_hash(body)
    raw_dir = project_data_dir(slug) / "raw"
    out = raw_dir / f"{h[:2]}/{h}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        out.write_text(body, encoding="utf-8")
    # always (re)write the index entry so reruns refresh URL → hash
    index = raw_dir / "_index.jsonl"
    with index.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"url": url, "hash": h}, ensure_ascii=False) + "\n")
    return out, h


class RecordWriter:
    """Append-only JSONL writer for raw extracted records.

    If `run_id` is set (typically the API Job.id), every written record gets a
    `_run_id` field stamped on it — enables lineage view ("which records came
    from job #14?")."""

    def __init__(self, slug: str, source_name: str, *, run_id: int | None = None):
        path = project_data_dir(slug) / "raw" / f"{source_name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("a", encoding="utf-8")
        self.count = 0
        self.run_id = run_id

    def write(self, record: dict) -> None:
        if self.run_id is not None and "_run_id" not in record:
            record["_run_id"] = self.run_id
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.count += 1

    def close(self) -> None:
        self._fh.flush()
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def count_jsonl(slug: str, source_name: str) -> int:
    p = project_data_dir(slug) / "raw" / f"{source_name}.jsonl"
    if not p.exists():
        return 0
    with p.open("rb") as fh:
        return sum(1 for _ in fh)


def load_seen_urls(slug: str) -> set[str]:
    """Return the set of all URLs we've ever fetched in this project.

    Used by incremental scraping — list_detail spiders skip URLs already in
    this set unless force=True. Reads `raw/_index.jsonl` which write_raw()
    appends to on every fetch."""
    p = project_data_dir(slug) / "raw" / "_index.jsonl"
    if not p.exists():
        return set()
    seen: set[str] = set()
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            u = r.get("url")
            if u:
                seen.add(u)
    return seen


def load_source_checkpoint(slug: str, source_name: str) -> dict:
    """Read this source's checkpoint manifest (max_post_id, last_run_at, etc.).

    Used by telegram_web and telegram_mtproto for forward-incremental pulls."""
    p = project_data_dir(slug) / "raw" / f"{source_name}.manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_source_checkpoint(slug: str, source_name: str, data: dict) -> None:
    p = project_data_dir(slug) / "raw" / f"{source_name}.manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
