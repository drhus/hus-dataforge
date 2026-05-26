"""Per-source-kind normalization to a canonical record schema.

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
    "meta": { ... source-specific extras ... }
  }
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import ftfy

log = logging.getLogger(__name__)

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")

# Aldiwan breadcrumb noise — title field captures the chain like
# "الديوان»سوريا»حذيفة العرجي»قصيدة النصر". With the engine's new \n-aware
# text extractor these can also arrive multi-line like "\nالديوان\n»\nسوريا\n…".
# Normalise whitespace first, then take the last »-separated segment.

# Aldiwan h3 chrome at the bottom of poem pages — once we hit one of these
# strings in the verses field, drop everything after.
ALDIWAN_CHROME_MARKERS = (
    "المزيد عن",
    "أضف معلومة",
    "أضف تعليق",
    "اقتباسات",
    "تعليقات",
)


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


def _strip_chrome(text: str | None) -> str:
    if not text:
        return ""
    out_lines: list[str] = []
    for ln in text.splitlines():
        if any(m in ln for m in ALDIWAN_CHROME_MARKERS):
            break
        out_lines.append(ln)
    return "\n".join(out_lines).strip()


def _clean_title(title: str | None) -> str | None:
    if not title:
        return None
    title = ftfy.fix_text(title)
    # collapse all whitespace (incl. newlines from the \n-separator extractor)
    title = re.sub(r"\s+", " ", title).strip()
    if title.startswith("الديوان") and "»" in title:
        # take last segment of the breadcrumb chain
        last = title.rsplit("»", 1)[-1].strip()
        if last:
            return last
    return title


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = ftfy.fix_text(text)
    text = _strip_chrome(text)
    # collapse runs of blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # strip trailing whitespace per line
    text = "\n".join(ln.rstrip() for ln in text.splitlines()).strip()
    return text


def _looks_like_poetry(text: str) -> bool:
    """Heuristic to keep records that are plausibly poems/verses.

    Permissive: we'd rather keep junk and dedup it than drop real poems.
    Drops only obvious non-poetry: empty, link-only, single-sentence ads."""
    if not text:
        return False
    if len(text) < 20:
        return False
    # all-URL messages
    url_chars = len(re.findall(r"https?://\S+", text))
    if url_chars and len(text.replace(" ", "")) < 80:
        return False
    if _arabic_ratio(text) < 0.4:
        return False
    return True


def normalize_record(
    raw: dict,
    *,
    source_name: str,
    source_kind: str,
    poet: str | None,
) -> dict[str, Any] | None:
    """Return a canonical record dict, or None if filtered out."""
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
        scraped_at = None
        meta = {}
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

    text = _clean_text(text)
    title = _clean_title(title)

    if not _looks_like_poetry(text):
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
        "meta": meta,
    }
