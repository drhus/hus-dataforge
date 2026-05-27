"""Dry-run / preview mode: fetch a small sample for a single source without
writing anything permanent. Used by the add-source wizards and the per-source
'Preview' button.

Returns a structured preview: extracted records, type detection, suggested
selector tweaks. Does not touch the project's raw/ dir."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from packages.engine.extract import extract_links, extract_records
from packages.engine.http_client import RateLimitedClient
from packages.engine.spec import SourceSpec, project_spec_from_dict

log = logging.getLogger(__name__)

DEFAULT_SAMPLE_SIZE = 5


def detect_source_type(url: str) -> dict:
    """Heuristic spider-type detection from a URL.

    Returns {type, confidence, hints} — used by the add-by-URL wizard to
    pre-fill source config so the user only confirms / tweaks."""
    u = urlparse(url)
    host = (u.hostname or "").lower()

    if host.startswith("t.me") or host == "telegram.me":
        # /s/<channel> → public mirror; /<channel>/<id> → permalink
        parts = [p for p in (u.path or "").split("/") if p]
        if parts and parts[0] == "s" and len(parts) >= 2:
            return {
                "type": "telegram_web",
                "channel": parts[1],
                "confidence": "high",
                "hint": "Telegram public channel mirror — recent ~thousands of messages, anonymous.",
            }
        if parts:
            return {
                "type": "telegram_web",
                "channel": parts[0],
                "confidence": "high",
                "hint": "Telegram channel — using public mirror at t.me/s/<channel>.",
            }

    if host in ("x.com", "twitter.com"):
        parts = [p for p in (u.path or "").split("/") if p]
        if parts:
            return {
                "type": "x_syndication",
                "handle": parts[0],
                "confidence": "medium",
                "hint": "X profile — syndication endpoint only returns data for ~10K+ follower accounts.",
            }

    # aldiwan-style: /cat-poet-<slug> is a listing
    if "/cat-poet-" in (u.path or ""):
        return {
            "type": "list_detail",
            "list_url": url,
            "list_link_selector": 'a[href^="poem"]',
            "base_url": f"{u.scheme}://{u.hostname}/",
            "confidence": "high",
            "hint": "aldiwan-style poet listing — list_detail spider with poem-link selector.",
        }

    # paginated query param
    if re.search(r"[?&]page=\d+", url):
        return {
            "type": "paginated",
            "url_template": re.sub(r"(page=)\d+", r"\g<1>{page}", url),
            "page_range": [1, 5],
            "confidence": "medium",
            "hint": "URL has a `page=N` parameter — paginated spider with {page} template.",
        }

    # Default fallback
    return {
        "type": "list_detail",
        "list_url": url,
        "list_link_selector": "a",
        "base_url": f"{u.scheme}://{u.hostname}/" if u.hostname else None,
        "confidence": "low",
        "hint": "Unable to auto-detect — defaulting to list_detail. Tighten selectors after dry-run.",
    }


def preview_source(
    slug: str,
    source_dict: dict,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> dict[str, Any]:
    """Run a single source for N records without writing anything permanent.

    `source_dict` is the raw source config (same shape as what'd be saved
    into the project config). We build a SourceSpec, then run the spider
    with `max_records=sample_size` and intercept its output.

    Returns:
        {
          "source": <source name>,
          "type": <spider type>,
          "samples": [<extracted records>...],
          "sample_count": int,
          "errors": [<strings>],
        }
    """
    samples: list[dict] = []
    errors: list[str] = []

    # build a single-source project spec to reuse the existing validator
    try:
        full = {"sources": [{**source_dict, "name": source_dict.get("name", "_preview")}]}
        spec = project_spec_from_dict(slug, full)
        if not spec.sources:
            return {"source": None, "samples": [], "sample_count": 0, "errors": ["empty spec"]}
        source = spec.sources[0]
    except Exception as e:
        return {"source": source_dict.get("name"), "samples": [], "sample_count": 0, "errors": [f"spec: {e}"]}

    # Cap records and dispatch to a preview-friendly fetcher per type
    source.max_records = min(source.max_records or sample_size, sample_size)
    try:
        if source.type == "telegram_web":
            samples = _preview_telegram_web(source)
        elif source.type in ("list_detail",):
            samples = _preview_list_detail(source)
        elif source.type == "paginated":
            samples = _preview_paginated(source)
        elif source.type == "fixture":
            samples = _preview_fixture(slug, source)
        else:
            errors.append(f"preview not yet implemented for spider type: {source.type}")
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")

    return {
        "source": source.name,
        "type": source.type,
        "samples": samples[:sample_size],
        "sample_count": len(samples),
        "errors": errors,
    }


def _preview_telegram_web(source: SourceSpec) -> list[dict]:
    from packages.engine.spiders.telegram_web import _page_url, _parse_messages

    assert source.list_url
    parts = source.list_url.rstrip("/").split("/")
    channel = parts[parts.index("s") + 1].split("?")[0]

    client = RateLimitedClient(rate_limit_sec=max(0.5, source.rate_limit_sec))
    try:
        html = client.get(_page_url(channel, None))
        msgs = _parse_messages(html, channel)
        return msgs[: source.max_records or DEFAULT_SAMPLE_SIZE]
    finally:
        client.close()


def _preview_list_detail(source: SourceSpec) -> list[dict]:
    assert source.list_url and source.list_link_selector
    cap = source.max_records or DEFAULT_SAMPLE_SIZE
    client = RateLimitedClient(rate_limit_sec=max(0.5, source.rate_limit_sec))
    try:
        listing_html = client.get(source.list_url)
        raw_links = extract_links(
            listing_html, source.list_link_selector, attr=source.link_attr
        )
        base = source.base_url or source.list_url
        urls = [urljoin(base, h) for h in raw_links][:cap]
        out: list[dict] = []
        for url in urls:
            try:
                html = client.get(url)
            except Exception as e:
                out.append({"_error": str(e), "_source_url": url})
                continue
            recs = extract_records(html, source.record_selector, source.fields)
            for r in recs:
                r["_source_url"] = url
                out.append(r)
        return out[:cap]
    finally:
        client.close()


def _preview_paginated(source: SourceSpec) -> list[dict]:
    assert source.url_template and source.page_range
    cap = source.max_records or DEFAULT_SAMPLE_SIZE
    start, _ = source.page_range
    client = RateLimitedClient(rate_limit_sec=max(0.5, source.rate_limit_sec))
    try:
        out: list[dict] = []
        page = start
        while len(out) < cap:
            url = source.url_template.format(page=page)
            html = client.get(url)
            recs = extract_records(html, source.record_selector, source.fields)
            for r in recs:
                r["_source_url"] = url
                out.append(r)
                if len(out) >= cap:
                    break
            page += 1
            if page > start + 2:  # safety: never iterate >3 pages in preview
                break
        return out
    finally:
        client.close()


def _preview_fixture(slug: str, source: SourceSpec) -> list[dict]:
    from pathlib import Path

    from packages.api.settings import PROJECTS_DIR

    assert source.fixture_path
    p = Path(source.fixture_path)
    if not p.is_absolute():
        p = PROJECTS_DIR / slug / source.fixture_path
    if not p.exists():
        raise FileNotFoundError(str(p))
    html = p.read_text(encoding="utf-8")
    return extract_records(html, source.record_selector, source.fields)[
        : source.max_records or DEFAULT_SAMPLE_SIZE
    ]


__all__ = ["preview_source", "detect_source_type", "DEFAULT_SAMPLE_SIZE"]
