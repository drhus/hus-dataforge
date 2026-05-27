"""Web-search adapter — tries multiple backends in order until one returns
results. By default uses the locally-hosted SearXNG (free, unlimited,
multi-engine: Google + Bing + Brave + Qwant + DuckDuckGo). Falls back to
public DuckDuckGo HTML if the local instance is unavailable.

Future providers (Brave Search API, Serper, etc.) plug in here behind the
same `web_search(query)` signature."""
from __future__ import annotations

import logging
import os
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from selectolax.lexbor import LexborHTMLParser

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Local SearXNG — see /home/agent/searxng/settings.yml and the docker container
# `dataforge-search` (port 18080 on loopback).
SEARXNG_URL = os.environ.get("DATAFORGE_SEARXNG_URL", "http://127.0.0.1:18080")


def _searxng_results(query: str, *, timeout: float, max_results: int) -> list[dict]:
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout) as client:
            r = client.get(
                f"{SEARXNG_URL}/search",
                params={"q": query, "format": "json"},
                follow_redirects=True,
            )
            if r.status_code != 200:
                log.info("searxng status=%d for %r", r.status_code, query)
                return []
            data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.info("searxng unavailable for %r: %s", query, e)
        return []
    out: list[dict] = []
    for r in data.get("results", []):
        url = r.get("url")
        if not url:
            continue
        out.append(
            {
                "title": (r.get("title") or url)[:300],
                "url": url,
                "snippet": (r.get("content") or "")[:300],
                "_engine": r.get("engine") or "searxng",
            }
        )
        if len(out) >= max_results:
            break
    return out


def _decode_ddg_url(href: str) -> str:
    if not href:
        return href
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com" in href and "uddg=" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            target = qs.get("uddg", [None])[0]
            if target:
                return unquote(target)
        except Exception:
            pass
    return href


def _ddg_results(query: str, *, timeout: float, max_results: int) -> list[dict]:
    try:
        with httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ar,en;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            r = client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "kl": "wt-wt"},
            )
    except httpx.HTTPError as e:
        log.info("ddg request failed for %r: %s", query, e)
        return []
    if r.status_code != 200 or "result__" not in r.text:
        log.info("ddg status=%d empty/blocked for %r", r.status_code, query)
        return []
    tree = LexborHTMLParser(r.text)
    out: list[dict] = []
    for node in tree.css(".result"):
        a = node.css_first(".result__a")
        if a is None:
            continue
        href = a.attributes.get("href") or ""
        url = _decode_ddg_url(href)
        if not url.startswith("http"):
            continue
        snippet_el = node.css_first(".result__snippet")
        out.append(
            {
                "title": a.text(strip=True) or url,
                "url": url,
                "snippet": (snippet_el.text(strip=True)[:300] if snippet_el else ""),
                "_engine": "ddg",
            }
        )
        if len(out) >= max_results:
            break
    return out


def web_search(query: str, *, max_results: int = 30, timeout: float = 20.0) -> list[dict]:
    """Run one search query through the backend chain.

    Order:
      1. Local SearXNG (if configured / running)
      2. DuckDuckGo HTML (fallback when SearXNG returns empty)
    """
    if not query.strip():
        return []
    results = _searxng_results(query, timeout=timeout, max_results=max_results)
    if results:
        return results
    return _ddg_results(query, timeout=timeout, max_results=max_results)


def search_many(queries: list[str], *, per_query: int = 20, rate_sec: float = 0.5) -> list[dict]:
    """Run a batch of queries sequentially with a small delay. Returns a
    flattened, de-duplicated list of {title, url, snippet, _engine, _query} dicts.
    """
    seen_urls: set[str] = set()
    out: list[dict] = []
    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(rate_sec)
        for r in web_search(q, max_results=per_query):
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            out.append({**r, "_query": q})
    return out


__all__ = ["web_search", "search_many", "SEARXNG_URL"]
