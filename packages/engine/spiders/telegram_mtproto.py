"""Full-history Telegram scraper via the official MTProto API (Telethon).

**Preferred usage pattern: tail-extension.**
Run telegram_web first (anonymous, not tied to your account). Configure this
spider with `extend_below_source: telegram-<channel>` and it will *only* fetch
messages OLDER than what the web mirror already has. Public mirror covers the
recent ~thousands of messages on most channels; this fills in the deeper tail.

Safety rules (all enforced automatically):
1. **One run = one channel** — single RQ worker guarantees this.
2. **Telethon auto flood-wait** — sleeps when Telegram says to. We log it.
3. **Incremental after first backfill** — manifest stores max_post_id;
   subsequent runs use `min_id=max_post_id` so only new messages are fetched.
4. **Tail-only when extending** — `extend_below_source` reads min post_id from
   the named source's raw JSONL and passes `max_id=min-1`. Combined with the
   incremental min_id, this bounds the fetch to a precise window.
5. **Conservative cap.** Default 5000 per run; tune per source.
6. **Inter-channel cooldown.** Engine sleeps 30s between back-to-back
   telegram_mtproto sources (env var `DATAFORGE_TELEGRAM_COOLDOWN_SEC`).

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
from packages.engine.storage import RecordWriter, project_data_dir

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


def _min_post_id_in_source(slug: str, source_name: str) -> int | None:
    """Scan the named source's raw JSONL and return the minimum post_id seen,
    or None if the file doesn't exist or has no post_id field."""
    p = project_data_dir(slug) / "raw" / f"{source_name}.jsonl"
    if not p.exists():
        return None
    min_seen: int | None = None
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = r.get("post_id")
            if pid is None:
                continue
            try:
                pid_int = int(pid)
            except (TypeError, ValueError):
                continue
            if min_seen is None or pid_int < min_seen:
                min_seen = pid_int
    return min_seen


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

    def run(
        self,
        slug: str,
        source: SourceSpec,
        progress: Progress,
        *,
        run_id: int | None = None,
    ) -> int:
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

        # Forward-incremental: only fetch messages newer than our last max
        prev = _read_manifest(slug, source.name)
        min_id = int(prev.get("max_post_id") or 0)

        # Tail-extension: if configured, cap upper bound at the other source's
        # min post_id - 1, so we ONLY fetch messages OLDER than what the
        # (anonymous) web mirror already has
        max_id = 0  # 0 means "no upper bound" for Telethon
        extend_from = source.extend_below_source
        if extend_from:
            web_min = _min_post_id_in_source(slug, extend_from)
            if web_min is None:
                log.warning(
                    "telegram_mtproto: extend_below_source=%r exists in config "
                    "but has no records yet; running without max_id",
                    extend_from,
                )
            elif web_min <= 1:
                log.info(
                    "telegram_mtproto: %s — extend source already covers the "
                    "channel back to post_id=%d; nothing older to fetch",
                    channel,
                    web_min,
                )
                # write a no-op manifest entry so we don't keep retrying
                _write_manifest(
                    slug,
                    source.name,
                    {
                        "channel": channel,
                        "mode": "extend_exhausted",
                        "count_this_run": 0,
                        "count_total": prev.get("count_total") or 0,
                        "max_post_id": prev.get("max_post_id") or 0,
                        "extend_below_min_post_id": web_min,
                        "scraped_at": datetime.utcnow().isoformat() + "Z",
                    },
                )
                return 0
            else:
                max_id = web_min - 1
                log.info(
                    "telegram_mtproto: %s tail-extending below post_id=%d "
                    "(web mirror's min from %r)",
                    channel,
                    web_min,
                    extend_from,
                )

        mode = (
            "extend_tail"
            if max_id > 0
            else ("incremental" if min_id else "backfill")
        )
        log.info(
            "telegram_mtproto: %s %s (mode=%s, min_id=%s, max_id=%s, cap=%d)",
            slug,
            channel,
            mode,
            min_id,
            max_id,
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
            with RecordWriter(slug, source.name, run_id=run_id) as writer:
                last_url = None
                iter_kwargs = {"limit": cap}
                if min_id > 0:
                    iter_kwargs["min_id"] = min_id
                if max_id > 0:
                    iter_kwargs["max_id"] = max_id

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
