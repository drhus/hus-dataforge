"""Hus-DataForge export (Milestone 4).

Input:  data/<slug>/clean/<poet>.jsonl
Output: data/<slug>/export/<poet>.parquet
        data/<slug>/export/README.md   (HuggingFace dataset card)
        data/<slug>/export/_stats.json (counts, schema, last-export ts)

Optional upload to HuggingFace Hub if HUGGINGFACE_TOKEN is set
(via `dataforge push <slug>` — separate command, not part of run_export).

Public API:
    run_export(slug, *, progress=None) -> dict
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from packages.api import projects_store
from packages.api.settings import DATA_DIR
from packages.engine.progress import NullProgress, Progress

log = logging.getLogger(__name__)


def _read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _write_parquet(records: list[dict], path: Path) -> int:
    """Write JSONL records to a Parquet file via pyarrow.

    Returns the row count. Records have heterogeneous keys; pyarrow handles
    that via schema inference on the in-memory table."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not records:
        return 0

    # Normalize keys across records (Arrow needs a uniform schema). meta is
    # flattened to a single JSON-string column to dodge nested-schema pain.
    rows: list[dict] = []
    keys: set[str] = set()
    for r in records:
        flat = {k: v for k, v in r.items() if k != "meta"}
        flat["meta_json"] = json.dumps(r.get("meta") or {}, ensure_ascii=False)
        rows.append(flat)
        keys.update(flat.keys())
    for r in rows:
        for k in keys:
            r.setdefault(k, None)

    table = pa.Table.from_pylist(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    return table.num_rows


def _dataset_card(slug: str, stats: dict, poets: list[str]) -> str:
    """Generate a minimal HuggingFace dataset card (README.md frontmatter + body)."""
    by_poet_lines = []
    for p in sorted(stats["by_poet"].keys()):
        by_poet_lines.append(
            f"- **{p}** — {stats['by_poet'][p]['rows']} records "
            f"({stats['by_poet'][p]['words']:,} words)"
        )
    return f"""---
license: cc-by-4.0
language:
  - ar
size_categories:
  - n<1K
task_categories:
  - text-generation
tags:
  - arabic
  - poetry
  - {slug}
---

# {slug}

Arabic poetry corpus assembled by [hus-dataforge](https://github.com/drhus/hus-dataforge).

## Per-poet counts

{chr(10).join(by_poet_lines)}

## Schema

| Field        | Type    | Notes |
|--------------|---------|-------|
| id           | string  | 16-char content hash (title + text) |
| poet         | string  | Per-poet manifest slug |
| title        | string  | Cleaned title (may be null for Telegram) |
| text         | string  | Cleaned poem/verses body |
| lang         | string  | "ar" or other (langdetect-based) |
| source       | string  | Source name within the project |
| source_kind  | string  | aldiwan / telegram / x / fixture |
| source_url   | string  | Canonical URL of the record |
| scraped_at   | string  | ISO-8601 |
| word_count   | int     | |
| line_count   | int     | |
| meta_json    | string  | JSON-encoded source-specific metadata |

## Provenance

Records were scraped from public Arabic poetry sites (primarily
[aldiwan.net](https://www.aldiwan.net)) and public Telegram channels.
Cleaning steps: per-source-kind normalization, mojibake fix (ftfy),
breadcrumb/chrome stripping for aldiwan, exact-hash + MinHash-LSH dedup
(threshold 0.85) per poet.

## License

Source content remains under each upstream source's terms.
This dataset's compilation, schema, and metadata are released CC-BY-4.0.
For Telegram channel content: messages are public but reproduced under
fair-use for research / training; channel owners can request removal
by opening an issue on the repo.

## Generated

- Compiler: hus-dataforge v0.1.0
- Exported: {stats['exported_at']}
"""


def run_export(slug: str, *, progress: Progress | None = None) -> dict:
    progress = progress or NullProgress()

    # validate project exists (raises if not)
    projects_store.get_project(slug)

    clean_dir = DATA_DIR / slug / "clean"
    export_dir = DATA_DIR / slug / "export"
    export_dir.mkdir(parents=True, exist_ok=True)

    if not clean_dir.exists():
        raise FileNotFoundError(
            f"no clean/ dir for {slug} — run the cleaning pipeline first"
        )

    stats = {
        "project": slug,
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        "by_poet": {},
        "total_rows": 0,
    }
    poets: list[str] = []

    for poet_jsonl in sorted(clean_dir.glob("*.jsonl")):
        poet_slug = poet_jsonl.stem
        records = list(_read_jsonl(poet_jsonl))
        progress.start(f"export:{poet_slug}")
        out_path = export_dir / f"{poet_slug}.parquet"
        n = _write_parquet(records, out_path)
        words = sum(int(r.get("word_count") or 0) for r in records)
        stats["by_poet"][poet_slug] = {"rows": n, "words": words}
        stats["total_rows"] += n
        poets.append(poet_slug)
        log.info("export: wrote %d rows to %s", n, out_path)
        progress.page(str(out_path), n)

    # Dataset card + stats
    (export_dir / "README.md").write_text(
        _dataset_card(slug, stats, poets), encoding="utf-8"
    )
    (export_dir / "_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    progress.finish()
    return stats


__all__ = ["run_export"]
