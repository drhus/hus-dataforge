"""Search-engine-backed discovery — finds arbitrary sources for any subject.

Complements the static probes in discovery.py (which check 4 hand-coded
sites). This one runs ~4 query variants on DDG, groups the hits by domain,
and classifies each domain as a candidate source with an appropriate spider
template.

Recognised domains get high-confidence templates; unknown domains get a
generic list_detail template marked low-confidence — the user can tune
selectors after dry-run."""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from urllib.parse import urlparse

from packages.engine.web_search import search_many

log = logging.getLogger(__name__)

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def _has_arabic(text: str) -> bool:
    return bool(text and ARABIC_RE.search(text))


def _arabic_ratio(text: str) -> float:
    if not text:
        return 0.0
    arabic = len(ARABIC_RE.findall(text))
    non_space = sum(1 for c in text if not c.isspace())
    return arabic / non_space if non_space else 0.0


_QUALITY_ENGINES = {"google", "brave", "wikipedia", "qwant"}
_SPAM_PRONE_ENGINES = {"bing"}


def _is_spam_url(url: str, hits: list[dict]) -> bool:
    """Cheap quality filter — drop obvious spam/parked domains.

    Real sites appear via Google or Brave. Bing's Arabic index has heavy spam
    pollution (SEO-stuffed domains with gibberish content). For an unknown
    domain we require at least one quality-engine hit.

    Also drops short-random-slug URLs even if they have Bing hits — the
    "ahinaret.bt/bi" pattern."""
    parsed = urlparse(url)
    domain = parsed.hostname or ""
    path = parsed.path.strip("/")

    # 1) Multi-engine quality gate — require at least one Google/Brave/Wikipedia hit
    engines = {(h.get("_engine") or "").lower() for h in hits}
    if not (engines & _QUALITY_ENGINES):
        # No quality-engine hit → require either rich snippet or recognizable
        # word in the domain SLD; otherwise treat as spam.
        snippets = [h.get("snippet") or "" for h in hits]
        if not any(s.strip() for s in snippets):
            return True
        if _looks_like_random_domain(domain):
            return True

    # 2) Random-slug guard — applies regardless of engine
    if path and "/" not in path and 3 <= len(path) <= 12 and re.fullmatch(r"[a-z]+", path):
        if all(not (h.get("snippet") or "").strip() for h in hits):
            return True

    return False


def _looks_like_random_domain(domain: str) -> bool:
    """Cheap check: very-short TLD with a low-vowel-density SLD often means
    a parked / SEO-spam domain (acugoek.cy, jeagu.ca, fonto.il etc.)."""
    parts = domain.split(".")
    if len(parts) < 2:
        return False
    sld = parts[-2]
    tld = parts[-1]
    if len(tld) > 3:
        return False  # multi-char TLD = unlikely the pattern
    if len(sld) < 4 or len(sld) > 9:
        return False
    # vowel density
    vowels = sum(1 for c in sld if c in "aeiouy")
    if vowels == 0 or vowels >= len(sld) - 1:
        return True
    # bigram repeat — gibberish often has rare bigrams
    consonant_clusters = re.findall(r"[bcdfghjklmnpqrstvwxz]{3,}", sld)
    if consonant_clusters:
        return True
    return False


def _has_relevant_signal(url: str, hits: list[dict], expected_lang: str) -> bool:
    """For low-confidence candidates: require strong Arabic signal in the
    title or snippet. Spam pages stuff a few Arabic words into gibberish
    English titles — low Arabic ratio. Real Arabic pages have ≥40%
    Arabic chars in the snippet."""
    if expected_lang != "ar":
        return True
    for h in hits:
        title = h.get("title") or ""
        snippet = h.get("snippet") or ""
        # Combine title + snippet; require strong Arabic majority
        combined = f"{title} {snippet}"
        if _arabic_ratio(combined) >= 0.4:
            return True
    return False


# Domains we know how to scrape well — map domain → spider template factory.
KNOWN_DOMAINS: dict[str, dict] = {
    "www.aldiwan.net": {
        "site_name": "aldiwan",
        "spider_type": "list_detail",
        "rate_limit_sec": 3.5,
        "selectors": {
            "list_link_selector": 'a[href^="poem"]',
            "record_selector": "body",
            "fields": {
                "title": {"selector": "h2", "attr": "text"},
                "verses": {"selector": "div.bet-1", "attr": "text"},
            },
        },
    },
    "poetspedia.com": {
        "site_name": "poetspedia",
        "spider_type": "list_detail",
        "rate_limit_sec": 2.0,
        "selectors": {
            "list_link_selector": "a[href*='poem']",
            "record_selector": "body",
            "fields": {
                "title": {"selector": "h1", "attr": "text"},
                "verses": {"selector": "article", "attr": "text"},
            },
        },
    },
    "poetsgate.com": {
        "site_name": "poetsgate",
        "spider_type": "list_detail",
        "rate_limit_sec": 2.0,
        "selectors": {
            "list_link_selector": "a[href*='PoteDetails']",
            "record_selector": "body",
            "fields": {
                "title": {"selector": "h1", "attr": "text"},
                "verses": {"selector": "article, .content, .poem", "attr": "text"},
            },
        },
        "notes": "Dewans are organized by collection; needs multi_level spider for full coverage.",
    },
    "www.adab.com": {
        "site_name": "adab",
        "spider_type": "list_detail",
        "rate_limit_sec": 2.0,
        "selectors": {
            "list_link_selector": "a[href*='modules.php']",
            "record_selector": "body",
            "fields": {
                "title": {"selector": "h2, h3", "attr": "text"},
                "verses": {"selector": ".content, .poem", "attr": "text"},
            },
        },
        "notes": "Older-style site — selectors likely need tuning per page.",
    },
    "qafiyah.com": {
        "site_name": "qafiyah",
        "spider_type": "list_detail",
        "rate_limit_sec": 2.0,
        "selectors": {
            "list_link_selector": "a[href*='/poem']",
            "record_selector": "body",
            "fields": {
                "title": {"selector": "h1", "attr": "text"},
                "verses": {"selector": "main, article, .verses", "attr": "text"},
            },
        },
        "notes": "Has an open API + DB dumps — prefer those over scraping.",
    },
    "t.me": {
        "site_name": "telegram",
        "spider_type": "telegram_web",
        "rate_limit_sec": 1.0,
        "selectors": {},
        "notes": "Public channel mirror. Add channel handle from URL.",
    },
    "x.com": {
        "site_name": "x",
        "spider_type": "x_syndication",
        "rate_limit_sec": 5.0,
        "selectors": {},
        "notes": "Syndication API only works for ~10K+ follower accounts.",
    },
    "twitter.com": {
        "site_name": "x",
        "spider_type": "x_syndication",
        "rate_limit_sec": 5.0,
        "selectors": {},
        "notes": "Syndication API only works for ~10K+ follower accounts.",
    },
}

# Domains to outright exclude
EXCLUDE_DOMAINS = {
    "www.google.com",
    "www.bing.com",
    "duckduckgo.com",
    "html.duckduckgo.com",
    "www.facebook.com",  # not currently scrapable
    "www.instagram.com",  # not currently scrapable
    "www.youtube.com",
    "youtube.com",
    "m.youtube.com",
    "translate.google.com",
}

# Reference / read-only sites (returned as info, not scraped by default)
REFERENCE_DOMAINS = {
    "ar.wikipedia.org",
    "en.wikipedia.org",
    "ar.wikiquote.org",
    "wikidata.org",
    "www.britannica.com",
}


def _short_domain(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host


def _classify_url(url: str, hits: list[dict]) -> dict | None:
    domain = _short_domain(url)
    if not domain or domain in EXCLUDE_DOMAINS:
        return None
    template = KNOWN_DOMAINS.get(domain)
    if template:
        # Special handling for telegram/x — extract handle from URL
        if template["site_name"] == "telegram":
            path = urlparse(url).path.lstrip("/")
            parts = [p for p in path.split("/") if p]
            channel = None
            if parts and parts[0] == "s" and len(parts) >= 2:
                channel = parts[1]
            elif parts:
                channel = parts[0]
            if not channel:
                return None
            return {
                "site": "telegram",
                "url": f"https://t.me/s/{channel}",
                "confidence": "high",
                "source_template": {
                    "type": "telegram_web",
                    "channel": channel,
                    "rate_limit_sec": 1.0,
                    "max_records": 5000,
                },
                "notes": f"Telegram channel @{channel} ({len(hits)} hit(s) in search)",
            }
        if template["site_name"] == "x":
            path = urlparse(url).path.lstrip("/")
            handle = path.split("/")[0] if path else None
            if not handle:
                return None
            return {
                "site": "x",
                "url": url,
                "confidence": "low",
                "source_template": {
                    "type": "x_syndication",
                    "handle": handle,
                    "rate_limit_sec": 5.0,
                },
                "notes": template.get("notes", ""),
            }
        # Other known poetry sites — build a list_detail template
        return {
            "site": template["site_name"],
            "url": url,
            "confidence": "high",
            "source_template": {
                "type": template["spider_type"],
                "list_url": url,
                "base_url": f"{urlparse(url).scheme}://{domain}/",
                "rate_limit_sec": template["rate_limit_sec"],
                **template["selectors"],
            },
            "notes": template.get("notes", "") or f"Known poetry domain, {len(hits)} search hit(s).",
        }
    if domain in REFERENCE_DOMAINS:
        return {
            "site": domain,
            "url": url,
            "confidence": "reference",
            "source_template": None,
            "notes": "Reference page (not scraped) — useful for context, aliases, source IDs.",
        }
    # Unknown domain — generic candidate
    return {
        "site": domain,
        "url": url,
        "confidence": "low",
        "source_template": {
            "type": "list_detail",
            "list_url": url,
            "list_link_selector": "a",
            "base_url": f"{urlparse(url).scheme}://{domain}/",
            "rate_limit_sec": 2.0,
            "record_selector": "body",
            "fields": {
                "title": {"selector": "h1, h2", "attr": "text"},
                "verses": {"selector": "article, main, .content", "attr": "text"},
            },
        },
        "notes": "Unknown site — tighten selectors after dry-run.",
    }


def _query_variants(name: str, *, subject_type: str) -> list[str]:
    """Build a set of queries that surface poetry-related pages."""
    name = name.strip().strip('"')
    if subject_type in ("poet", "person"):
        return [
            f'"{name}" شعر',
            f'"{name}" قصيدة',
            f'"{name}" ديوان',
            f'"{name}"',
        ]
    if subject_type == "topic":
        return [
            f'{name} شعر',
            f'{name} ديوان قصائد',
            f'قصائد عن {name}',
            f'{name} موضوع شعري',
        ]
    if subject_type == "site":
        return [name]
    return [f'"{name}"', name]


def discover_via_search(
    name: str,
    *,
    subject_type: str = "poet",
    per_query: int = 15,
) -> list[dict]:
    """Run a real web search for the subject and classify the hits."""
    queries = _query_variants(name, subject_type=subject_type)
    log.info("discover_via_search %r queries=%s", name, queries)
    hits = search_many(queries, per_query=per_query, rate_sec=1.0)

    # group by URL (some hits are repeats), then classify the first URL per domain
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for h in hits:
        d = _short_domain(h["url"])
        if not d or d in EXCLUDE_DOMAINS:
            continue
        by_domain[d].append(h)

    # Detect search language for quality-gate (Arabic queries → require Arabic
    # in snippets to keep a low-confidence candidate)
    expected_lang = "ar" if any(ARABIC_RE.search(q) for q in queries) else "en"

    candidates: list[dict] = []
    for domain, group in by_domain.items():
        # use the first hit's URL for classification (usually most relevant)
        c = _classify_url(group[0]["url"], group)
        if c is None:
            continue
        # Quality filter — applies to low-confidence (unknown-domain) candidates
        if c["confidence"] == "low":
            if _is_spam_url(group[0]["url"], group):
                continue
            if not _has_relevant_signal(group[0]["url"], group, expected_lang):
                continue
        # attach search-snippet evidence
        c["_evidence"] = [
            {"title": g["title"], "url": g["url"], "query": g.get("_query")}
            for g in group[:3]
        ]
        c["_hits"] = len(group)
        candidates.append(c)

    order = {"high": 0, "medium": 1, "low": 2, "reference": 3}
    candidates.sort(key=lambda c: (order.get(c["confidence"], 99), -c.get("_hits", 0), c["site"]))
    return candidates


__all__ = ["discover_via_search", "KNOWN_DOMAINS", "REFERENCE_DOMAINS", "EXCLUDE_DOMAINS"]
