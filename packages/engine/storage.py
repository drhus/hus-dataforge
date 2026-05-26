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
    """Append-only JSONL writer for raw extracted records."""

    def __init__(self, slug: str, source_name: str):
        path = project_data_dir(slug) / "raw" / f"{source_name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("a", encoding="utf-8")
        self.count = 0

    def write(self, record: dict) -> None:
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
