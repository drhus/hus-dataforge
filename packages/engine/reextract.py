"""Re-run extraction on already-cached HTML — no network, no rate-limiting.

Use when you've added new field selectors and want them populated for
records you scraped before the change. Walks `raw/_index.jsonl` (URL →
content_hash log), reads each cached HTML from `raw/<hash[:2]>/<hash>.html`,
runs the source's current `extract_records()` and writes a fresh JSONL.

Only affects list_detail / multi_level_list_detail / paginated sources —
spiders that store raw HTML. Telegram + X don't have cached HTML to
re-extract from."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from packages.api import projects_store
from packages.engine.extract import extract_records
from packages.engine.spec import SourceSpec, project_spec_from_dict
from packages.engine.storage import project_data_dir

log = logging.getLogger(__name__)

HTML_EXTRACTING_TYPES = {"list_detail", "multi_level_list_detail", "paginated"}


def _load_url_to_hash(slug: str) -> dict[str, str]:
    idx = project_data_dir(slug) / "raw" / "_index.jsonl"
    out: dict[str, str] = {}
    if not idx.exists():
        return out
    with idx.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = r.get("url")
            h = r.get("hash")
            if url and h:
                out[url] = h
    return out


def _read_cached_html(slug: str, content_hash: str) -> str | None:
    p = project_data_dir(slug) / "raw" / content_hash[:2] / f"{content_hash}.html"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def _existing_urls_for_source(slug: str, source_name: str) -> list[str]:
    """The URLs we've already scraped for THIS source (in its JSONL)."""
    src_jsonl = project_data_dir(slug) / "raw" / f"{source_name}.jsonl"
    if not src_jsonl.exists():
        return []
    urls: list[str] = []
    seen: set[str] = set()
    with src_jsonl.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = r.get("_source_url")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def re_extract_source(slug: str, source: SourceSpec) -> dict:
    """Re-run extraction on cached HTML for one source. Atomic: writes a
    temp file then renames over the existing JSONL."""
    if source.type not in HTML_EXTRACTING_TYPES:
        return {
            "source": source.name,
            "skipped": True,
            "reason": f"source.type={source.type} doesn't cache HTML to re-extract from",
        }

    url_to_hash = _load_url_to_hash(slug)
    urls = _existing_urls_for_source(slug, source.name)
    out_path = project_data_dir(slug) / "raw" / f"{source.name}.jsonl"
    tmp_path = out_path.with_suffix(out_path.suffix + ".reextract.tmp")

    n_total = 0
    n_extracted = 0
    n_missing_html = 0
    n_no_records = 0
    with tmp_path.open("w", encoding="utf-8") as fh:
        for url in urls:
            n_total += 1
            h = url_to_hash.get(url)
            if not h:
                n_missing_html += 1
                continue
            html = _read_cached_html(slug, h)
            if html is None:
                n_missing_html += 1
                continue
            records = extract_records(html, source.record_selector, source.fields)
            if not records:
                n_no_records += 1
                continue
            for r in records:
                r["_source_url"] = url
                r["_reextracted_at"] = datetime.now(tz=timezone.utc).isoformat()
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                n_extracted += 1

    # atomic swap, keep .bak in case
    if out_path.exists():
        bak = out_path.with_suffix(out_path.suffix + ".bak")
        shutil.move(str(out_path), str(bak))
    shutil.move(str(tmp_path), str(out_path))

    return {
        "source": source.name,
        "urls_in_jsonl": n_total,
        "records_written": n_extracted,
        "missing_cached_html": n_missing_html,
        "no_records_extracted": n_no_records,
    }


def re_extract_project(slug: str) -> dict:
    """Re-extract every HTML-caching source in a project."""
    raw_cfg = projects_store.get_project(slug).config
    if "_yaml" in raw_cfg and isinstance(raw_cfg["_yaml"], str):
        import yaml

        raw_cfg = yaml.safe_load(raw_cfg["_yaml"]) or {}
    spec = project_spec_from_dict(slug, raw_cfg)
    results: list[dict] = []
    for source in spec.sources:
        log.info("re-extract: %s/%s", slug, source.name)
        results.append(re_extract_source(slug, source))
    return {
        "project": slug,
        "sources_processed": len(results),
        "by_source": results,
    }


__all__ = ["re_extract_source", "re_extract_project"]
