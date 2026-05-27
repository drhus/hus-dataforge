"""Two-level list_detail: top URL → many intermediate listing pages → many detail pages.

Useful for sites organized as: poet → dewans (collections) → poems, or
category → subcategory → articles. Each level has its own link selector,
all share the same per-detail extraction spec.

Config keys (on a SourceSpec):
  list_url, list_link_selector       → top page → level-1 links
  sub_link_selector                  → level-1 page → detail links
  base_url                           → resolve relative links (defaults to list_url)
  record_selector, fields            → per-detail extraction (same as list_detail)
  rate_limit_sec, max_records        → standard limits"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from packages.engine.extract import extract_links, extract_records
from packages.engine.http_client import RateLimitedClient
from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter, write_raw

log = logging.getLogger(__name__)


class MultiLevelListDetailSpider:
    def run(
        self,
        slug: str,
        source: SourceSpec,
        progress: Progress,
        *,
        run_id: int | None = None,
        force: bool = False,
    ) -> int:
        from packages.engine.storage import load_seen_urls

        assert source.list_url and source.list_link_selector and source.sub_link_selector
        seen_urls = set() if force else load_seen_urls(slug)

        client = RateLimitedClient(rate_limit_sec=source.rate_limit_sec)
        base = source.base_url or source.list_url
        try:
            log.info("multi_level: top page %s", source.list_url)
            top_html = client.get(source.list_url)
            write_raw(slug, top_html, source.list_url)
            level1_links = [
                urljoin(base, h)
                for h in extract_links(top_html, source.list_link_selector, source.link_attr)
            ]
            log.info("multi_level: %d level-1 URLs", len(level1_links))

            detail_urls: list[str] = []
            for l1 in level1_links:
                try:
                    l1_html = client.get(l1)
                except Exception as e:
                    log.warning("L1 fetch failed %s: %s", l1, e)
                    continue
                write_raw(slug, l1_html, l1)
                detail_urls.extend(
                    urljoin(base, h)
                    for h in extract_links(l1_html, source.sub_link_selector, source.link_attr)
                )

            # dedup while preserving order; also skip URLs already fetched in
            # any previous run (project-wide _index.jsonl) unless force=True.
            seen: set[str] = set()
            ordered_details: list[str] = []
            for u in detail_urls:
                if u in seen or u in seen_urls:
                    continue
                seen.add(u)
                ordered_details.append(u)
            if source.max_records is not None:
                ordered_details = ordered_details[: source.max_records]
            log.info(
                "multi_level: %d new detail URLs to scrape%s",
                len(ordered_details),
                " (force)" if force else "",
            )

            with RecordWriter(slug, source.name, run_id=run_id) as writer:
                from packages.engine.storage import record_failed_url

                for url in ordered_details:
                    try:
                        html = client.get(url)
                    except Exception as e:
                        log.warning("detail fetch failed %s: %s", url, e)
                        record_failed_url(slug, url, str(e))
                        progress.page(url, 0)
                        continue
                    write_raw(slug, html, url)
                    records = extract_records(html, source.record_selector, source.fields)
                    for r in records:
                        r["_source_url"] = url
                        writer.write(r)
                    progress.page(url, len(records))
                return writer.count
        finally:
            client.close()
