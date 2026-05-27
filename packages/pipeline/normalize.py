"""Per-source-kind normalization to a canonical record schema.

Cleanup is rules-driven — each source carries its own CleanRules
(see spec.py). Source-type defaults are filled in at parse time, so
existing projects work unchanged; new corpora can override any rule.

Always-on transforms (regardless of rules):
  - ftfy.fix_text() for mojibake
  - whitespace normalization (collapse blank-line runs, strip trailing)

Canonical record:
  {
    "id": <16-char content hash>,
    "poet": <poet-slug or None>,
    "title": <str or None>,
    "text": <str>,                 # cleaned poem/verses body
    "lang": "ar" | <other>,
    "source": <source name in project>,
    "source_kind": "aldiwan" | "telegram" | "x" | "fixture" | "unknown",
    "source_url": <str>,
    "scraped_at": <iso datetime>,
    "word_count": int,
    "line_count": int,
    "category": <set later by pipeline>,
    "meta": { ... source-specific extras ... }
  }
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import ftfy

from packages.engine.spec import CleanRules, default_clean_rules

log = logging.getLogger(__name__)

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def _arabic_ratio(text: str) -> float:
    if not text:
        return 0.0
    arabic = len(ARABIC_RE.findall(text))
    total = sum(1 for c in text if not c.isspace())
    return arabic / total if total else 0.0


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w])


def _line_count(text: str) -> int:
    return len([l for l in text.splitlines() if l.strip()])


def _content_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# --- Title ops ---


def _apply_title_op(title: str, op: dict) -> str:
    name = op.get("op")
    if name == "split_last":
        sep = op.get("separator") or "»"
        prefix = op.get("if_starts_with")
        if prefix and not title.startswith(prefix):
            return title
        if sep not in title:
            return title
        last = title.rsplit(sep, 1)[-1].strip()
        return last or title
    if name == "regex_replace":
        pat = op.get("pattern") or ""
        repl = op.get("replacement") or ""
        if not pat:
            return title
        try:
            return re.sub(pat, repl, title)
        except re.error as e:
            log.warning("title regex_replace failed: %s", e)
            return title
    log.warning("unknown title op: %s", name)
    return title


def _clean_title(title: str | None, rules: CleanRules) -> str | None:
    if not title:
        return None
    title = ftfy.fix_text(title)
    # collapse all whitespace before rule application — most ops assume
    # single-line input
    title = re.sub(r"\s+", " ", title).strip()
    for op in rules.title_ops:
        title = _apply_title_op(title, op)
    return title.strip() or None


# --- Text ops ---


def _apply_text_op(text: str, op: dict) -> str:
    name = op.get("op")
    if name == "truncate_before_first_of":
        markers = op.get("markers") or []
        if not markers:
            return text
        out_lines: list[str] = []
        for ln in text.splitlines():
            if any(m in ln for m in markers):
                break
            out_lines.append(ln)
        return "\n".join(out_lines)
    if name == "strip_lines_matching":
        pat = op.get("pattern") or ""
        if not pat:
            return text
        try:
            rx = re.compile(pat)
        except re.error as e:
            log.warning("strip_lines_matching regex failed: %s", e)
            return text
        return "\n".join(ln for ln in text.splitlines() if not rx.search(ln))
    if name == "regex_replace":
        pat = op.get("pattern") or ""
        repl = op.get("replacement") or ""
        if not pat:
            return text
        try:
            return re.sub(pat, repl, text)
        except re.error as e:
            log.warning("text regex_replace failed: %s", e)
            return text
    log.warning("unknown text op: %s", name)
    return text


def _clean_text(text: str | None, rules: CleanRules) -> str:
    if not text:
        return ""
    text = ftfy.fix_text(text)
    for op in rules.text_ops:
        text = _apply_text_op(text, op)
    # always-on tail: collapse blank-line runs, strip trailing per line
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(ln.rstrip() for ln in text.splitlines()).strip()
    return text


# --- Filter ---


def _passes_filter(text: str, rules: CleanRules) -> bool:
    if not text:
        return False
    if len(text) < rules.filter_min_chars:
        return False
    if rules.filter_min_lines and _line_count(text) < rules.filter_min_lines:
        return False
    if rules.drop_if_url_dominated:
        url_chars = len(re.findall(r"https?://\S+", text))
        if url_chars and len(text.replace(" ", "")) < 80:
            return False
    if rules.filter_min_arabic_ratio > 0 and _arabic_ratio(text) < rules.filter_min_arabic_ratio:
        return False
    return True


# --- Main entry ---


def normalize_record(
    raw: dict,
    *,
    source_name: str,
    source_kind: str,
    poet: str | None,
    clean_rules: CleanRules | None = None,
) -> dict[str, Any] | None:
    """Return a canonical record dict, or None if filtered out.

    `clean_rules` carries the per-source rules (filled from defaults +
    user overrides at spec-parse time). If omitted, type-defaults are used
    — this keeps backward compatibility with old callers and tests."""
    rules = clean_rules or default_clean_rules(_kind_to_default_type(source_kind))

    if source_kind == "telegram":
        text = raw.get("text") or ""
        title = None
        url = raw.get("_source_url") or raw.get("permalink")
        scraped_at = raw.get("_scraped_at")
        meta = {
            "post_id": raw.get("post_id"),
            "published_at": raw.get("published_at"),
            "views": raw.get("views"),
            "channel": raw.get("_channel"),
        }
    elif source_kind == "aldiwan":
        text = raw.get("verses") or raw.get("text") or ""
        title = raw.get("title")
        url = raw.get("_source_url")
        scraped_at = raw.get("_reextracted_at")  # may be None
        # Preserve aldiwan-specific structured metadata if extracted
        meta = {}
        for k in (
            "categories",
            "category_slugs",
            "meter",
            "meter_slug",
            "rhyme",
            "rhyme_slug",
            "topics",
            "topic_slugs",
            "related_poets",
            "related_poet_slugs",
        ):
            v = raw.get(k)
            if v:
                meta[k] = v
    elif source_kind == "fixture":
        text = raw.get("text") or raw.get("verses") or ""
        title = raw.get("title")
        url = raw.get("_source_url")
        scraped_at = None
        meta = {}
    else:  # unknown / x / future
        text = (
            raw.get("text") or raw.get("verses") or raw.get("body") or raw.get("full_text") or ""
        )
        title = raw.get("title")
        url = raw.get("_source_url") or raw.get("permalink") or raw.get("source_url")
        scraped_at = raw.get("_scraped_at")
        meta = {k: v for k, v in raw.items() if k not in {"text", "title", "_source_url"}}

    text = _clean_text(text, rules)
    title = _clean_title(title, rules)

    if not _passes_filter(text, rules):
        return None

    lang = "ar" if _arabic_ratio(text) >= 0.5 else "other"

    return {
        "id": _content_hash((title or "") + "||" + text),
        "poet": poet,
        "title": title,
        "text": text,
        "lang": lang,
        "source": source_name,
        "source_kind": source_kind,
        "source_url": url,
        "scraped_at": scraped_at,
        "word_count": _word_count(text),
        "line_count": _line_count(text),
        "run_id": raw.get("_run_id"),
        "meta": meta,
    }


def _kind_to_default_type(source_kind: str) -> str:
    """Map the cleaning source_kind back to a spec source type for defaults."""
    if source_kind == "aldiwan":
        return "list_detail"
    if source_kind == "telegram":
        return "telegram_web"
    if source_kind == "x":
        return "x_syndication"
    return source_kind or "fixture"
