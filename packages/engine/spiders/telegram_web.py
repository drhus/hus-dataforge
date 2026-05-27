"""Scrape a public Telegram channel via its server-rendered web mirror.

Endpoint: https://t.me/s/<channel>           — newest N messages
          https://t.me/s/<channel>?before=ID — older page (ID excluded)

Each message is a `.tgme_widget_message_wrap` containing:
  - permalink:  parent `.tgme_widget_message[data-post]` → "<channel>/<id>"
  - text body:  `.tgme_widget_message_text`
  - timestamp:  `.tgme_widget_message_date time[datetime]` (ISO 8601)
  - views:      `.tgme_widget_message_views`

We paginate backwards: take the smallest data-post id on the page, then
fetch `?before=<that_id>` until either the page returns no new messages or
max_records is reached."""
from __future__ import annotations

import logging
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser

from packages.engine.http_client import RateLimitedClient
from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter, write_raw

log = logging.getLogger(__name__)


def _page_url(channel: str, before: int | None) -> str:
    base = f"https://t.me/s/{channel}"
    return f"{base}?before={before}" if before else base


def _parse_messages(html: str, channel: str) -> list[dict]:
    tree = LexborHTMLParser(html)
    out: list[dict] = []
    for wrap in tree.css(".tgme_widget_message_wrap"):
        msg = wrap.css_first(".tgme_widget_message[data-post]")
        if msg is None:
            continue
        data_post = msg.attributes.get("data-post") or ""
        # data-post format: "<channel>/<id>"
        post_id_str = data_post.split("/", 1)[-1] if "/" in data_post else ""
        try:
            post_id = int(post_id_str)
        except ValueError:
            continue

        text_node = wrap.css_first(".tgme_widget_message_text")
        text = text_node.text(separator="\n", strip=True) if text_node else None

        time_node = wrap.css_first(".tgme_widget_message_date time")
        ts = time_node.attributes.get("datetime") if time_node else None

        views_node = wrap.css_first(".tgme_widget_message_views")
        views = views_node.text(strip=True) if views_node else None

        out.append(
            {
                "post_id": post_id,
                "permalink": f"https://t.me/{channel}/{post_id}",
                "text": text,
                "published_at": ts,
                "views": views,
            }
        )
    return out


class TelegramWebSpider:
    """Spider for a single public Telegram channel.

    Config (in SourceSpec extras passed via fields={}):
      The 'fields' dict is ignored — Telegram output schema is fixed.
      Use these keys on the source dict (passed through SourceSpec.fixture_path
      / list_url for now — see below).

    Conventions to pass channel + max_records:
      source.list_url       → "https://t.me/s/<channel>"  (we extract channel from URL)
      source.max_records    → cap on records (default 200)
      source.rate_limit_sec → between page fetches (default 1.0; t.me is permissive)
    """

    def run(
        self,
        slug: str,
        source: SourceSpec,
        progress: Progress,
        *,
        run_id: int | None = None,
    ) -> int:
        assert source.list_url, "telegram_web needs list_url set to https://t.me/s/<channel>"
        # extract channel from /s/<channel>
        parts = source.list_url.rstrip("/").split("/")
        try:
            channel = parts[parts.index("s") + 1].split("?")[0]
        except (ValueError, IndexError):
            raise ValueError(f"could not parse channel from list_url: {source.list_url}")

        cap = source.max_records or 200
        client = RateLimitedClient(rate_limit_sec=source.rate_limit_sec)
        seen_ids: set[int] = set()

        try:
            with RecordWriter(slug, source.name, run_id=run_id) as writer:
                before: int | None = None
                while writer.count < cap:
                    url = _page_url(channel, before)
                    html = client.get(url)
                    write_raw(slug, html, url)
                    msgs = _parse_messages(html, channel)
                    new_msgs = [m for m in msgs if m["post_id"] not in seen_ids]
                    if not new_msgs:
                        break
                    written_this_page = 0
                    for m in new_msgs:
                        seen_ids.add(m["post_id"])
                        m["_source_url"] = m["permalink"]
                        m["_channel"] = channel
                        m["_scraped_at"] = datetime.utcnow().isoformat() + "Z"
                        writer.write(m)
                        written_this_page += 1
                        if writer.count >= cap:
                            break
                    progress.page(url, written_this_page)
                    next_before = min(m["post_id"] for m in new_msgs)
                    if before is not None and next_before >= before:
                        # not making progress (older-page returned same or newer ids)
                        break
                    before = next_before
                return writer.count
        finally:
            client.close()
