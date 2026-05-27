"""Subject-discovery — given a name (poet/person/topic), probe known sites
and return ranked candidate sources.

No external search API needed: each known source has a URL pattern + a
"probe" that checks whether that URL exists for the given name. Free to call,
no credentials, no rate-limit issues.

Known sources are declared in `DOMAIN_PROBES` below — add a new entry to
support a new site. Each probe returns (matched: bool, suggested_source: dict).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "hus-dataforge/0.1 (+https://github.com/drhus/hus-dataforge)"


@dataclass
class DiscoveryCandidate:
    site: str
    confidence: str  # "high" | "medium" | "low"
    url: str
    source_template: dict  # ready to drop into project config (minus name+subject)
    notes: str = ""


def _ar_to_url_slug(name: str) -> str:
    """Naive: Arabic name → URL-encoded slug (poetspedia uses this pattern)."""
    return quote(name.replace(" ", "-"))


def _try_url(client: httpx.Client, url: str, expect_contains: str | None = None) -> bool:
    try:
        r = client.get(url, follow_redirects=True, timeout=15)
    except httpx.HTTPError as e:
        log.info("discovery probe %s failed: %s", url, e)
        return False
    if r.status_code != 200 or len(r.text) < 400:
        return False
    if expect_contains and expect_contains not in r.text:
        return False
    return True


def _aldiwan_probe(name: str, aliases: list[str], client: httpx.Client) -> list[DiscoveryCandidate]:
    """aldiwan stores poets at /cat-poet-<latin-slug>. Without a name→slug map
    we can't probe directly, but we can search the site for the Arabic name."""
    out: list[DiscoveryCandidate] = []
    # Last-segment Latin guesses (low confidence; better: existing manifest)
    for candidate in aliases:
        if re.fullmatch(r"[a-z0-9-]+", candidate or ""):
            url = f"https://www.aldiwan.net/cat-poet-{candidate}"
            if _try_url(client, url, expect_contains='href="poem'):
                out.append(
                    DiscoveryCandidate(
                        site="aldiwan",
                        confidence="high",
                        url=url,
                        notes=f"matched slug guess `{candidate}`",
                        source_template={
                            "type": "list_detail",
                            "list_url": url,
                            "list_link_selector": 'a[href^="poem"]',
                            "base_url": "https://www.aldiwan.net/",
                            "rate_limit_sec": 3.5,
                            "record_selector": "body",
                            "fields": {
                                "title": {"selector": "h2", "attr": "text"},
                                "verses": {"selector": "div.bet-1", "attr": "text"},
                            },
                        },
                    )
                )
    return out


def _poetspedia_probe(name: str, aliases: list[str], client: httpx.Client) -> list[DiscoveryCandidate]:
    """poetspedia.com/poet/<arabic-name-url-encoded>.html"""
    out: list[DiscoveryCandidate] = []
    for candidate in [name, *aliases]:
        if not candidate:
            continue
        slug = candidate.replace(" ", "-")
        url = f"https://poetspedia.com/poet/{quote(slug)}.html"
        if _try_url(client, url):
            out.append(
                DiscoveryCandidate(
                    site="poetspedia",
                    confidence="medium",
                    url=url,
                    notes="page exists; selectors need manual tuning",
                    source_template={
                        "type": "list_detail",
                        "list_url": url,
                        "list_link_selector": "a[href*='poem']",
                        "base_url": "https://poetspedia.com/",
                        "rate_limit_sec": 2.0,
                        "record_selector": "body",
                        "fields": {
                            "title": {"selector": "h1", "attr": "text"},
                            "verses": {"selector": "article", "attr": "text"},
                        },
                    },
                )
            )
            break  # one canonical URL is enough
    return out


def _telegram_probe(name: str, aliases: list[str], client: httpx.Client) -> list[DiscoveryCandidate]:
    """t.me/s/<channel> — try each alias as a channel handle."""
    out: list[DiscoveryCandidate] = []
    for candidate in aliases:
        if not candidate or not re.fullmatch(r"[A-Za-z0-9_]{4,32}", candidate):
            continue
        url = f"https://t.me/s/{candidate}"
        if _try_url(client, url, expect_contains="tgme_widget_message"):
            out.append(
                DiscoveryCandidate(
                    site="telegram",
                    confidence="high",
                    url=url,
                    notes=f"public channel @{candidate} exists",
                    source_template={
                        "type": "telegram_web",
                        "channel": candidate,
                        "rate_limit_sec": 1.0,
                        "max_records": 5000,
                    },
                )
            )
    return out


def _x_probe(name: str, aliases: list[str], client: httpx.Client) -> list[DiscoveryCandidate]:
    """X profile existence — we DON'T probe x.com directly (it'd hit a 429
    quickly). Suggest the spider but mark confidence low; the syndication
    endpoint will silently return empty for low-follower accounts."""
    out: list[DiscoveryCandidate] = []
    for candidate in aliases:
        if not candidate or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", candidate):
            continue
        out.append(
            DiscoveryCandidate(
                site="x",
                confidence="low",
                url=f"https://x.com/{candidate}",
                notes="syndication endpoint requires ~10K+ followers; may return empty",
                source_template={
                    "type": "x_syndication",
                    "handle": candidate,
                    "rate_limit_sec": 5.0,
                },
            )
        )
        break
    return out


# Probe registry — extend to support new sites
DOMAIN_PROBES: list[Callable[[str, list[str], httpx.Client], list[DiscoveryCandidate]]] = [
    _aldiwan_probe,
    _poetspedia_probe,
    _telegram_probe,
    _x_probe,
]


def discover_sources(
    name: str,
    *,
    aliases: list[str] | None = None,
    subject_type: str = "poet",
    use_web_search: bool = True,
) -> list[dict]:
    """Discovery for a subject (poet/topic/person/site).

    Combines TWO strategies:
      1. Probe-based — fast direct checks against ~5 hand-coded poetry sites
         using the supplied aliases as slug guesses (no search engine needed).
      2. Web-search-backed — runs query variants on DuckDuckGo and classifies
         the resulting domains as candidate sources. Crucial for topics
         (which have no slug to probe) and for finding non-obvious sources.

    Returns a list of dicts sorted by confidence."""
    aliases = [a for a in (aliases or []) if a]
    by_url: dict[str, dict] = {}

    # 1) Static probes — only useful when we have aliases (slugs/handles)
    if aliases:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0) as client:
            for probe in DOMAIN_PROBES:
                try:
                    for c in probe(name, aliases, client):
                        by_url[c.url] = c.__dict__
                except Exception as e:
                    log.warning("probe %s raised: %s", probe.__name__, e)

    # 2) Web-search discovery — broader, finds new sites
    if use_web_search and name:
        from packages.engine.discovery_search import discover_via_search

        for c in discover_via_search(name, subject_type=subject_type):
            # don't overwrite a probe-based high-confidence hit with a search hit
            if c["url"] in by_url:
                # but copy evidence over
                if "_evidence" in c:
                    by_url[c["url"]]["_evidence"] = c["_evidence"]
                continue
            by_url[c["url"]] = c

    order = {"high": 0, "medium": 1, "low": 2, "reference": 3}
    return sorted(by_url.values(), key=lambda c: (order.get(c.get("confidence"), 99), c.get("site", "")))


__all__ = ["discover_sources", "DiscoveryCandidate", "DOMAIN_PROBES"]
