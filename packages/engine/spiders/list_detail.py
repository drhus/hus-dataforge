"""list_detail: fetch a listing page, follow N links, extract one record per detail page.

Incremental by default: detail URLs already fetched in any previous run
(tracked via `raw/_index.jsonl`) are skipped. The listing page itself is
always re-fetched so new URLs are discovered. Pass `force=True` to fetch
everything from scratch."""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from packages.engine.extract import extract_links, extract_records
from packages.engine.http_client import RateLimitedClient
from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter, load_seen_urls, write_raw

log = logging.getLogger(__name__)


class ListDetailSpider:
    def run(
        self,
        slug: str,
        source: SourceSpec,
        progress: Progress,
        *,
        run_id: int | None = None,
        force: bool = False,
    ) -> int:
        assert source.list_url and source.list_link_selector

        client = RateLimitedClient(rate_limit_sec=source.rate_limit_sec)
        try:
            log.info("list_detail: fetching listing %s", source.list_url)
            listing_html = client.get(source.list_url)
            write_raw(slug, listing_html, source.list_url)

            raw_links = extract_links(
                listing_html, source.list_link_selector, attr=source.link_attr
            )
            base = source.base_url or source.list_url
            urls = [urljoin(base, href) for href in raw_links]

            seen_urls: set[str] = set() if force else load_seen_urls(slug)
            new_urls = [u for u in urls if u not in seen_urls]
            log.info(
                "list_detail: %d total / %d already seen / %d new%s",
                len(urls),
                len(urls) - len(new_urls),
                len(new_urls),
                " (force)" if force else "",
            )
            urls = new_urls
            if source.max_records is not None:
                urls = urls[: source.max_records]

            with RecordWriter(slug, source.name, run_id=run_id) as writer:
                if not urls:
                    progress.page(source.list_url, 0)
                    return 0
                for url in urls:
                    try:
                        html = client.get(url)
                    except Exception as e:
                        log.warning("detail fetch failed %s: %s", url, e)
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
