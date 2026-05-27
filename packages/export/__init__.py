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

from collections import Counter

from packages.api import projects_store
from packages.api.settings import DATA_DIR, PROJECTS_DIR
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


def _size_category(total: int) -> str:
    """HuggingFace `size_categories` tag bracket."""
    if total < 1_000:
        return "n<1K"
    if total < 10_000:
        return "1K<n<10K"
    if total < 100_000:
        return "10K<n<100K"
    if total < 1_000_000:
        return "100K<n<1M"
    return "n>1M"


def _percentile(sorted_vals: list[int], pct: float) -> int:
    if not sorted_vals:
        return 0
    idx = max(0, min(len(sorted_vals) - 1, int(round((pct / 100) * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def _subject_names(slug: str) -> dict[str, dict]:
    """Best-effort name lookup: slug → {name_ar, name_en, country, era}."""
    import yaml

    out: dict[str, dict] = {}
    for dirname in ("poets", "subjects"):
        d = PROJECTS_DIR / slug / dirname
        if not d.exists():
            continue
        for f in d.glob("*.yaml"):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            existing = out.get(f.stem, {})
            for k in ("name_ar", "name_en", "country", "era", "born", "died"):
                v = data.get(k)
                if v and not existing.get(k):
                    existing[k] = v
            out[f.stem] = existing
    return out


def _dataset_card(
    slug: str,
    stats: dict,
    poets: list[str],
    extras: dict,
) -> str:
    """Generate a HuggingFace dataset card with richer corpus stats."""
    names = _subject_names(slug)

    def _label(poet_slug: str) -> str:
        n = names.get(poet_slug, {})
        ar = n.get("name_ar")
        en = n.get("name_en")
        if ar and en:
            return f"{ar} ({en})"
        return ar or en or poet_slug

    by_poet_lines = []
    sorted_poets = sorted(
        stats["by_poet"].keys(),
        key=lambda p: stats["by_poet"][p]["rows"],
        reverse=True,
    )
    for p in sorted_poets:
        label = _label(p)
        meta = names.get(p, {})
        born = meta.get("born")
        died = meta.get("died")
        years = ""
        if born and died:
            years = f", {born}–{died}"
        elif born:
            years = f", b. {born}"
        country = meta.get("country")
        country_s = f" · {country}" if country else ""
        rows = stats["by_poet"][p]["rows"]
        words = stats["by_poet"][p]["words"]
        by_poet_lines.append(
            f"- **{label}**{country_s}{years} — `{p}` — "
            f"{rows:,} records ({words:,} words)"
        )

    top_topics = extras["topics"][:15]
    top_meters = extras["meters"][:10]
    sources_used = extras["sources"][:20]

    topics_md = (
        "\n".join(f"| {t} | {c:,} |" for t, c in top_topics)
        if top_topics
        else "| _none extracted_ | 0 |"
    )
    meters_md = (
        "\n".join(f"| {m} | {c:,} |" for m, c in top_meters)
        if top_meters
        else "| _none extracted_ | 0 |"
    )
    sources_md = (
        "\n".join(f"| `{s}` | {c:,} |" for s, c in sources_used)
        if sources_used
        else "| _no sources_ | 0 |"
    )
    sidecars_md = ""
    if extras.get("sidecars"):
        lines = [
            f"- `{name}.parquet` — alternate category bucket "
            f"({stats['by_sidecar'][name]['rows']:,} rows, "
            f"{stats['by_sidecar'][name]['words']:,} words)"
            for name in extras["sidecars"]
        ]
        sidecars_md = (
            "\n## Sidecar splits\n\n"
            "Non-primary category buckets (e.g. commentary about a poem rather "
            "than the poem itself) — kept as separate Parquet files so the "
            "primary subject splits stay clean for training:\n\n"
            + "\n".join(lines)
            + "\n"
        )

    return f"""---
license: cc-by-4.0
language:
  - ar
size_categories:
  - {_size_category(stats['total_rows'])}
task_categories:
  - text-generation
tags:
  - arabic
  - poetry
  - {slug}
pretty_name: {slug}
---

# {slug}

Arabic poetry corpus assembled by [hus-dataforge](https://github.com/drhus/hus-dataforge).

**{stats['total_rows']:,} records · {extras['total_words']:,} words · {extras['total_lines']:,} lines · {len(sorted_poets)} subjects**

Median record length: {extras['len_p50']:,} words (p90 {extras['len_p90']:,}, p99 {extras['len_p99']:,}).
Cross-source duplicates collapsed: {extras['multi_source_records']:,} records appear in ≥2 sources.

## Subjects

{chr(10).join(by_poet_lines)}

## Top topics

| Topic | Records |
|-------|---------|
{topics_md}

## Top meters

| Meter | Records |
|-------|---------|
{meters_md}

## Source provenance

Most-frequent originating sources (first hit only — see `sources` column
for the full list per record when multiple agreed):

| Source | Records |
|--------|---------|
{sources_md}

{sidecars_md}
## Schema

| Field          | Type    | Notes |
|----------------|---------|-------|
| id             | string  | 16-char content hash (title + text) |
| poet           | string  | Subject manifest slug |
| title          | string  | Cleaned title (may be null for Telegram) |
| text           | string  | Cleaned poem/verses body |
| lang           | string  | "ar" or other |
| source         | string  | First-seen source name |
| sources        | list    | All sources this record was seen in |
| source_kind    | string  | aldiwan / telegram / x / fixture |
| source_url     | string  | Canonical URL of the record |
| source_urls    | list    | All variant URLs |
| scraped_at     | string  | ISO-8601 |
| word_count     | int     | |
| line_count     | int     | |
| category       | string  | Primary record category (poetry / commentary / quote …) |
| meta_json      | string  | JSON-encoded source-specific metadata (topics, meter, rhyme, …) |

## Provenance

Records were scraped from public Arabic poetry sites (primarily
[aldiwan.net](https://www.aldiwan.net)) and public Telegram channels.
Cleaning steps: per-source rules-driven normalization, mojibake fix
(ftfy), exact-hash + MinHash-LSH dedup (threshold 0.85) per (poet,
category). When the same poem is found in multiple sources, all source
names and URLs are accumulated on the surviving record.

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
        "by_sidecar": {},
        "total_rows": 0,
        "sidecar_rows": 0,
    }
    poets: list[str] = []
    topic_counter: Counter = Counter()
    meter_counter: Counter = Counter()
    source_counter: Counter = Counter()
    word_lengths: list[int] = []
    line_lengths: list[int] = []
    multi_source_records = 0

    for poet_jsonl in sorted(clean_dir.glob("*.jsonl")):
        stem = poet_jsonl.stem
        is_sidecar = "__" in stem
        records = list(_read_jsonl(poet_jsonl))
        progress.start(f"export:{stem}")
        out_path = export_dir / f"{stem}.parquet"
        n = _write_parquet(records, out_path)
        words = sum(int(r.get("word_count") or 0) for r in records)

        if is_sidecar:
            # Sidecar bucket (e.g. anas-aldaghim__commentary): export to
            # Parquet but track separately so primary subject stats reflect
            # only the canonical category (poetry).
            stats["by_sidecar"][stem] = {"rows": n, "words": words}
            stats["sidecar_rows"] += n
        else:
            poet_slug = stem
            stats["by_poet"][poet_slug] = {"rows": n, "words": words}
            stats["total_rows"] += n
            poets.append(poet_slug)

            # Aggregate corpus-wide stats — single pass, no extra I/O.
            for r in records:
                word_lengths.append(int(r.get("word_count") or 0))
                line_lengths.append(int(r.get("line_count") or 0))
                srcs = r.get("sources") or [r.get("source")]
                if srcs and len(srcs) > 1:
                    multi_source_records += 1
                for s in srcs:
                    if s:
                        source_counter[s] += 1
                meta = r.get("meta") or {}
                for t in str(meta.get("topics") or "").split("|"):
                    t = t.strip()
                    if t:
                        topic_counter[t] += 1
                for m in str(meta.get("meter") or "").split("|"):
                    m = m.strip()
                    if m:
                        meter_counter[m] += 1

        log.info("export: wrote %d rows to %s", n, out_path)
        progress.page(str(out_path), n)

    word_lengths.sort()
    extras = {
        "topics": topic_counter.most_common(50),
        "meters": meter_counter.most_common(20),
        "sources": source_counter.most_common(30),
        "total_words": sum(word_lengths),
        "total_lines": sum(line_lengths),
        "len_p50": _percentile(word_lengths, 50),
        "len_p90": _percentile(word_lengths, 90),
        "len_p99": _percentile(word_lengths, 99),
        "multi_source_records": multi_source_records,
        "sidecar_rows": stats["sidecar_rows"],
        "sidecars": list(stats["by_sidecar"].keys()),
    }
    stats["extras"] = extras

    # Dataset card + stats
    (export_dir / "README.md").write_text(
        _dataset_card(slug, stats, poets, extras), encoding="utf-8"
    )
    (export_dir / "_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    progress.finish()
    return stats


__all__ = ["run_export"]
