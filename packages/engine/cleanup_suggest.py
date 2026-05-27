"""Auto-suggest CleanRules from a small sample of records.

Heuristics:
  - If most titles share a common separator-delimited prefix (e.g. "X » Y » <real>"),
    propose a split_last op with the dominant separator.
  - If most texts end with a common boilerplate footer (last 1-3 lines repeat
    across samples), propose truncate_before_first_of with those markers.
  - Filter thresholds derived from observed length / arabic-ratio stats.

The output is a partial CleanRules dict suitable for the
PUT /projects/{slug}/sources/{src}/cleanup endpoint."""
from __future__ import annotations

import re
from collections import Counter
from statistics import median
from typing import Any

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
COMMON_SEPARATORS = ("»", "›", "·", "|", "—", "/", "::")


def _arabic_ratio(text: str) -> float:
    if not text:
        return 0.0
    arabic = len(ARABIC_RE.findall(text))
    total = sum(1 for c in text if not c.isspace())
    return arabic / total if total else 0.0


def _suggest_title_ops(titles: list[str]) -> list[dict]:
    """If most titles match `prefix SEP middle SEP last`, propose split_last."""
    titles = [t.strip() for t in titles if isinstance(t, str) and t.strip()]
    if not titles:
        return []

    sep_hits = Counter()
    for t in titles:
        for sep in COMMON_SEPARATORS:
            if sep in t:
                sep_hits[sep] += 1
    if not sep_hits:
        return []

    sep, hits = sep_hits.most_common(1)[0]
    # Only suggest if >= 60% of titles share this separator
    if hits < max(2, int(0.6 * len(titles))):
        return []

    # Find the most common prefix (first segment) — usually a site/section name
    prefixes = Counter()
    for t in titles:
        if sep in t:
            head = t.split(sep, 1)[0].strip()
            if head:
                prefixes[head] += 1
    prefix, prefix_hits = (prefixes.most_common(1)[0] if prefixes else ("", 0))

    op: dict[str, Any] = {"op": "split_last", "separator": sep}
    if prefix_hits >= int(0.6 * len(titles)):
        op["if_starts_with"] = prefix
    return [op]


def _suggest_text_ops(texts: list[str]) -> list[dict]:
    """If samples end with the same 1–3 lines (boilerplate footer), propose
    truncate_before_first_of with those literal lines as markers."""
    texts = [t for t in texts if isinstance(t, str) and t.strip()]
    if len(texts) < 2:
        return []

    last_line_hits: Counter[str] = Counter()
    for t in texts:
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        for ln in lines[-3:]:  # last 3 non-empty lines
            if 3 < len(ln) < 80:
                last_line_hits[ln] += 1

    # markers seen in >= 50% of samples
    threshold = max(2, len(texts) // 2)
    markers = sorted(
        [line for line, n in last_line_hits.items() if n >= threshold],
        key=lambda l: -last_line_hits[l],
    )[:6]

    if not markers:
        return []
    return [{"op": "truncate_before_first_of", "markers": markers}]


def _suggest_filter(texts: list[str]) -> dict[str, Any]:
    if not texts:
        return {}
    lens = [len(t) for t in texts]
    arabic = [_arabic_ratio(t) for t in texts]
    if not lens:
        return {}
    out: dict[str, Any] = {}
    p25 = sorted(lens)[len(lens) // 4]
    out["filter_min_chars"] = max(20, min(p25, int(median(lens) * 0.5)))
    if min(arabic) >= 0.4:
        out["filter_min_arabic_ratio"] = 0.4
    elif median(arabic) >= 0.5:
        out["filter_min_arabic_ratio"] = 0.4
    else:
        out["filter_min_arabic_ratio"] = 0.0  # non-Arabic-dominant corpus
    return out


def suggest_clean_rules(samples: list[dict], *, source_type: str | None = None) -> dict[str, Any]:
    """Take preview samples → suggest a CleanRules patch.

    Records can have varying shapes — we collect anything that looks like a
    title (title field or first short line) and text (text/verses/message)."""
    titles: list[str] = []
    texts: list[str] = []
    for r in samples:
        if not isinstance(r, dict):
            continue
        t = r.get("title")
        if isinstance(t, str) and t.strip():
            titles.append(t)
        body = r.get("text") or r.get("verses") or r.get("message") or r.get("body")
        if isinstance(body, str) and body.strip():
            texts.append(body)

    suggestion: dict[str, Any] = {
        "title_ops": _suggest_title_ops(titles),
        "text_ops": _suggest_text_ops(texts),
        **_suggest_filter(texts),
        "_stats": {
            "samples": len(samples),
            "with_title": len(titles),
            "with_text": len(texts),
            "median_text_len": int(median([len(t) for t in texts])) if texts else 0,
            "median_arabic_ratio": (
                round(median([_arabic_ratio(t) for t in texts]), 2) if texts else 0.0
            ),
        },
    }
    return suggestion


__all__ = ["suggest_clean_rules"]
