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
) -> list[dict]:
    """Given a subject name + optional aliases (latin slugs, social handles),
    probe known sites and return ranked candidates.

    Returns a list of dicts (DiscoveryCandidate.__dict__) sorted by confidence.
    """
    aliases = [a for a in (aliases or []) if a]
    if not name and not aliases:
        return []

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0) as client:
        candidates: list[DiscoveryCandidate] = []
        for probe in DOMAIN_PROBES:
            try:
                candidates.extend(probe(name, aliases, client))
            except Exception as e:
                log.warning("probe %s raised: %s", probe.__name__, e)

    order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda c: (order.get(c.confidence, 99), c.site))
    return [c.__dict__ for c in candidates]


__all__ = ["discover_sources", "DiscoveryCandidate", "DOMAIN_PROBES"]
