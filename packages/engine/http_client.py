"""Polite httpx fetcher with rate limiting + simple retries."""
from __future__ import annotations

import time

import httpx

USER_AGENT = "hus-dataforge/0.1 (+https://github.com/drhus/hus-dataforge)"


class RateLimitedClient:
    def __init__(self, rate_limit_sec: float = 1.0, timeout: float = 30.0):
        self.rate_limit_sec = rate_limit_sec
        self._last = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )

    def get(self, url: str) -> str:
        wait = self.rate_limit_sec - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            r = self._client.get(url)
        finally:
            self._last = time.monotonic()
        r.raise_for_status()
        return r.text

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
