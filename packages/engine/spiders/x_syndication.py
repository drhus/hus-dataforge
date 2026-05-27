"""X (Twitter) public-timeline scraper via syndication.twitter.com.

Known limitations (2026):
  - Returns empty for accounts with fewer than ~10K followers (silent filter).
  - IP-level rate limits; running this repeatedly will get 429s.
  - Endpoint shape may change without notice (twittxr-style approach).

Use when the poet has a large following. Otherwise: paid X API or skip."""
from __future__ import annotations

import json
import logging
import re

from packages.engine.http_client import RateLimitedClient
from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter, write_raw

log = logging.getLogger(__name__)

SCRIPT_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>',
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/114.0.0.0"
)


class XSyndicationError(RuntimeError):
    pass


def _extract_tweets(html: str) -> list[dict]:
    m = SCRIPT_RE.search(html)
    if not m:
        raise XSyndicationError("no __NEXT_DATA__ found (timeline gated or empty)")
    data = json.loads(m.group(1))
    page_props = data.get("props", {}).get("pageProps", {}) or {}
    timeline = page_props.get("timeline", {}) or {}
    entries = timeline.get("entries") or []
    tweets: list[dict] = []
    for e in entries:
        t = (e.get("content") or {}).get("tweet")
        if not t:
            continue
        tweets.append(
            {
                "tweet_id": str(t.get("id_str") or t.get("id") or ""),
                "text": t.get("full_text") or t.get("text"),
                "created_at": t.get("created_at"),
                "lang": t.get("lang"),
                "user": (t.get("user") or {}).get("screen_name"),
                "permalink": (
                    f"https://x.com/{(t.get('user') or {}).get('screen_name', '')}/status/"
                    f"{t.get('id_str') or t.get('id') or ''}"
                ),
                "favorite_count": t.get("favorite_count"),
            }
        )
    return tweets


class XSyndicationSpider:
    """Config:
      source.list_url → ignored (we build from `handle`)
      source.fixture_path → reused as handle (e.g. 'al_arje') — pragmatic reuse
                            of the existing SourceSpec fields to avoid bloat.
                            See spec.py for a cleaner schema later.
      source.max_records → cap (defaults to whatever the endpoint returns, ~12)
    """

    def run(self, slug: str, source: SourceSpec, progress: Progress, *, run_id: int | None = None) -> int:
        handle = source.fixture_path or ""
        if not handle:
            raise XSyndicationError("set fixture_path to the X handle (e.g. al_arje)")

        url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
        client = RateLimitedClient(rate_limit_sec=source.rate_limit_sec or 5.0)

        client._client.headers["Origin"] = "https://publish.twitter.com"
        client._client.headers["User-Agent"] = USER_AGENT

        try:
            html = client.get(url)
            write_raw(slug, html, url)
            tweets = _extract_tweets(html)
            if not tweets:
                log.warning(
                    "x_syndication: timeline empty for @%s — likely sub-10K followers "
                    "or rate-limited. See poet-corpus-strategy.md.",
                    handle,
                )
            with RecordWriter(slug, source.name, run_id=run_id) as writer:
                cap = source.max_records or len(tweets)
                for t in tweets[:cap]:
                    t["_source_url"] = t.get("permalink") or url
                    t["_handle"] = handle
                    writer.write(t)
                progress.page(url, writer.count)
                return writer.count
        finally:
            client.close()
