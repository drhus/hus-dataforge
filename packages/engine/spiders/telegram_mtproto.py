"""Full-history Telegram scraper via the official MTProto API (Telethon).

Safety rules (all enforced automatically):
1. **One run = one channel.** The single-RQ-worker model means we never run
   two MTProto pulls concurrently on the same account.
2. **Telethon's auto flood-wait.** When Telegram returns FLOOD_WAIT_X, Telethon
   sleeps the requested duration. We log it.
3. **Incremental after first backfill.** A checkpoint manifest at
   `data/<slug>/raw/<source>.manifest.json` stores the max post_id seen.
   Subsequent runs use `min_id=max_post_id` so we only fetch new messages.
4. **Conservative cap.** First pulls cap at `max_records` (default 5000) so
   even a runaway first-time fetch is bounded.
5. **Inter-channel cooldown.** When the engine processes multiple
   telegram_mtproto sources in one run, it sleeps `inter_channel_cooldown_sec`
   between them (default 30s) — enforced at the engine level, not here.

What this gives you that telegram_web does not:
  - the entire channel history, not just whatever t.me/s/<channel> exposes
  - private channels you are a member of
  - structured message objects (edits, forwards, media descriptors)

Credentials live in /home/agent/.config/dataforge/telegram.env (mode 600):
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_PATH"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter, project_data_dir, write_raw

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
    for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_PATH"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _manifest_path(slug: str, source_name: str) -> Path:
    return project_data_dir(slug) / "raw" / f"{source_name}.manifest.json"


def _read_manifest(slug: str, source_name: str) -> dict:
    p = _manifest_path(slug, source_name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_manifest(slug: str, source_name: str, manifest: dict) -> None:
    p = _manifest_path(slug, source_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


class TelegramMTProtoSpider:
    """Config:
      source.fixture_path → channel username (re-used field; see spec.py)
      source.max_records  → cap per run (default 5000)
      source.rate_limit_sec → ignored (Telethon manages flood-wait)
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
        if not api_id_raw or not api_hash or "__SET_ME__" in (api_hash or ""):
            raise TelegramAuthError("TELEGRAM_API_ID / TELEGRAM_API_HASH not configured")

        cap = source.max_records or 5000
        session_arg = session[:-8] if session.endswith(".session") else session

        # Incremental backfill — only fetch messages newer than the previous max
        prev = _read_manifest(slug, source.name)
        min_id = int(prev.get("max_post_id") or 0)
        mode = "incremental" if min_id else "backfill"
        log.info(
            "telegram_mtproto: %s %s (mode=%s, min_id=%s, cap=%d)",
            slug,
            channel,
            mode,
            min_id,
            cap,
        )

        client = TelegramClient(session_arg, int(api_id_raw), api_hash)
        client.connect()
        try:
            if not client.is_user_authorized():
                raise TelegramAuthError(
                    "session not authorized — run `dataforge telegram-login` once on the VPS"
                )

            entity = client.get_entity(channel)

            max_seen = min_id
            with RecordWriter(slug, source.name) as writer:
                last_url = None
                iter_kwargs = {"limit": cap}
                if min_id > 0:
                    iter_kwargs["min_id"] = min_id

                for msg in client.iter_messages(entity, **iter_kwargs):
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
                    if msg.id > max_seen:
                        max_seen = msg.id
                    if writer.count % PAGE_SIZE == 0:
                        progress.page(last_url, PAGE_SIZE)
                if writer.count % PAGE_SIZE != 0 and last_url:
                    progress.page(last_url, writer.count % PAGE_SIZE)

                _write_manifest(
                    slug,
                    source.name,
                    {
                        "channel": channel,
                        "mode": mode,
                        "count_this_run": writer.count,
                        "count_total": (prev.get("count_total") or 0) + writer.count,
                        "max_post_id": max_seen,
                        "previous_max_post_id": min_id,
                        "last_url": last_url,
                        "scraped_at": datetime.utcnow().isoformat() + "Z",
                    },
                )
                log.info(
                    "telegram_mtproto: %s done — wrote %d new messages (max_post_id=%d)",
                    channel,
                    writer.count,
                    max_seen,
                )
                return writer.count
        finally:
            client.disconnect()
