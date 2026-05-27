from __future__ import annotations

import logging

from packages.engine.extract import extract_records
from packages.engine.http_client import RateLimitedClient
from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter, write_raw

log = logging.getLogger(__name__)


class PaginatedSpider:
    def run(self, slug: str, source: SourceSpec, progress: Progress, *, run_id: int | None = None) -> int:
        assert source.url_template and source.page_range, "paginated needs url_template + page_range"
        start, end = source.page_range
        client = RateLimitedClient(rate_limit_sec=source.rate_limit_sec)
        try:
            with RecordWriter(slug, source.name, run_id=run_id) as writer:
                for page in range(start, end + 1):
                    url = source.url_template.format(page=page)
                    try:
                        html = client.get(url)
                    except Exception as e:
                        log.warning("fetch failed %s: %s", url, e)
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
