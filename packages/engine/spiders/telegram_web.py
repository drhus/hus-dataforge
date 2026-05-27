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
        force: bool = False,
    ) -> int:
        from packages.engine.storage import load_source_checkpoint, save_source_checkpoint

        assert source.list_url, "telegram_web needs list_url set to https://t.me/s/<channel>"
        parts = source.list_url.rstrip("/").split("/")
        try:
            channel = parts[parts.index("s") + 1].split("?")[0]
        except (ValueError, IndexError):
            raise ValueError(f"could not parse channel from list_url: {source.list_url}")

        cap = source.max_records or 200
        client = RateLimitedClient(rate_limit_sec=source.rate_limit_sec)
        seen_ids: set[int] = set()

        # Incremental: stop pagination as soon as we hit any post_id we
        # already have from a previous run. If no checkpoint exists but the
        # JSONL file does (e.g. data scraped before incremental landed),
        # seed the floor from the highest post_id in that file.
        checkpoint = {} if force else load_source_checkpoint(slug, source.name)
        last_max = int(checkpoint.get("max_post_id") or 0)
        if not force and last_max == 0:
            from packages.engine.storage import project_data_dir

            jsonl = project_data_dir(slug) / "raw" / f"{source.name}.jsonl"
            if jsonl.exists():
                import json as _json

                for line in jsonl.open("r", encoding="utf-8"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue
                    pid = r.get("post_id")
                    if isinstance(pid, int) and pid > last_max:
                        last_max = pid
                if last_max:
                    log.info(
                        "telegram_web: %s seeded floor from existing jsonl: %d",
                        channel,
                        last_max,
                    )
        log.info(
            "telegram_web: %s incremental_floor=%d cap=%d%s",
            channel,
            last_max,
            cap,
            " (force)" if force else "",
        )

        new_max = last_max
        try:
            with RecordWriter(slug, source.name, run_id=run_id) as writer:
                before: int | None = None
                stop = False
                while writer.count < cap and not stop:
                    url = _page_url(channel, before)
                    html = client.get(url)
                    write_raw(slug, html, url)
                    msgs = _parse_messages(html, channel)
                    new_msgs = [m for m in msgs if m["post_id"] not in seen_ids]
                    if not new_msgs:
                        break
                    written_this_page = 0
                    for m in new_msgs:
                        if m["post_id"] <= last_max:
                            stop = True
                            break  # caught up to previous max — done
                        seen_ids.add(m["post_id"])
                        m["_source_url"] = m["permalink"]
                        m["_channel"] = channel
                        m["_scraped_at"] = datetime.utcnow().isoformat() + "Z"
                        writer.write(m)
                        written_this_page += 1
                        if m["post_id"] > new_max:
                            new_max = m["post_id"]
                        if writer.count >= cap:
                            stop = True
                            break
                    progress.page(url, written_this_page)
                    if stop:
                        break
                    next_before = min(m["post_id"] for m in new_msgs)
                    if before is not None and next_before >= before:
                        break  # not making progress
                    before = next_before

                save_source_checkpoint(
                    slug,
                    source.name,
                    {
                        "channel": channel,
                        "last_run_at": datetime.utcnow().isoformat() + "Z",
                        "mode": "incremental" if last_max else "backfill",
                        "max_post_id": new_max,
                        "previous_max_post_id": last_max,
                        "count_this_run": writer.count,
                        "count_total": (checkpoint.get("count_total") or 0) + writer.count,
                    },
                )
                return writer.count
        finally:
            client.close()
