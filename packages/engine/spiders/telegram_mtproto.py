"""Full-history Telegram scraper via the official MTProto API (Telethon).

What this gives you that telegram_web does not:
  - the entire channel history, not just whatever t.me/s/<channel> exposes
  - private channels you are a member of
  - structured message objects (edits, forwards, media descriptors)

Credentials live in /home/agent/.config/dataforge/telegram.env (mode 600):
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_PATH

The session file is created on first interactive login via:
    dataforge telegram-login
After that, this spider runs headlessly inside the RQ worker."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter, write_raw

log = logging.getLogger(__name__)

CREDS_PATH = Path("/home/agent/.config/dataforge/telegram.env")
PAGE_SIZE = 100  # Telegram caps per-request at ~100


class TelegramAuthError(RuntimeError):
    pass


def _load_creds() -> dict[str, str]:
    if not CREDS_PATH.exists():
        raise TelegramAuthError(
            f"telegram creds not found at {CREDS_PATH} — set TELEGRAM_API_ID/HASH"
        )
    env: dict[str, str] = {}
    for line in CREDS_PATH.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    # env-vars override file (useful for tests)
    for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_PATH"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


class TelegramMTProtoSpider:
    """Config:
        source.list_url    → ignored
        source.fixture_path → reused as channel username (e.g. 'el_arje').
                             Same pragmatic-reuse trick as x_syndication.
        source.max_records → cap (default 1000)
        source.rate_limit_sec → ignored — Telethon manages flood-wait itself.
    """

    def run(self, slug: str, source: SourceSpec, progress: Progress) -> int:
        from telethon import TelegramClient
        from telethon.tl.types import Message

        channel = source.fixture_path
        if not channel:
            raise TelegramAuthError("set `channel: <username>` on the source")

        creds = _load_creds()
        api_id_raw = creds.get("TELEGRAM_API_ID")
        api_hash = creds.get("TELEGRAM_API_HASH")
        session = creds.get("TELEGRAM_SESSION_PATH") or "/home/agent/.config/dataforge/telegram"
        if not api_id_raw or not api_hash or api_hash == "__SET_ME__":
            raise TelegramAuthError("TELEGRAM_API_ID / TELEGRAM_API_HASH not configured")
        if "__SET_ME__" in (api_hash or ""):
            raise TelegramAuthError("TELEGRAM_API_HASH still placeholder")

        cap = source.max_records or 1000

        # strip .session — Telethon adds it
        session_arg = session[:-8] if session.endswith(".session") else session

        client = TelegramClient(session_arg, int(api_id_raw), api_hash)
        client.connect()
        try:
            if not client.is_user_authorized():
                raise TelegramAuthError(
                    "session not authorized — run `dataforge telegram-login` once on the VPS"
                )

            entity = client.get_entity(channel)
            log.info("telegram_mtproto: scraping %s (max %d)", channel, cap)

            with RecordWriter(slug, source.name) as writer:
                last_url = None
                page = 0
                for msg in client.iter_messages(entity, limit=cap):
                    if not isinstance(msg, Message):
                        continue
                    text = msg.message or ""
                    permalink = f"https://t.me/{channel}/{msg.id}"
                    record = {
                        "post_id": msg.id,
                        "permalink": permalink,
                        "text": text or None,
                        "published_at": msg.date.isoformat() if msg.date else None,
                        "edited_at": msg.edit_date.isoformat() if msg.edit_date else None,
                        "views": msg.views,
                        "forwards": msg.forwards,
                        "is_forward": msg.fwd_from is not None,
                        "media_kind": type(msg.media).__name__ if msg.media else None,
                        "_source_url": permalink,
                        "_channel": channel,
                        "_scraped_at": datetime.utcnow().isoformat() + "Z",
                    }
                    writer.write(record)
                    last_url = permalink
                    if writer.count % PAGE_SIZE == 0:
                        page += 1
                        progress.page(last_url, PAGE_SIZE)
                # final partial page
                if writer.count % PAGE_SIZE != 0 and last_url:
                    progress.page(last_url, writer.count % PAGE_SIZE)

                # store a tiny "manifest" so we know what we crawled & where to resume
                _write_manifest(slug, source.name, channel, writer.count, last_url)
                return writer.count
        finally:
            client.disconnect()


def _write_manifest(slug: str, source_name: str, channel: str, count: int, last_url: str | None) -> None:
    import json
    from packages.engine.storage import project_data_dir

    p = project_data_dir(slug) / "raw" / f"{source_name}.manifest.json"
    p.write_text(
        json.dumps(
            {
                "channel": channel,
                "count": count,
                "last_url": last_url,
                "scraped_at": datetime.utcnow().isoformat() + "Z",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
