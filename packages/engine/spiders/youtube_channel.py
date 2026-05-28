"""youtube_channel: enumerate uploads of a YouTube channel or playlist, then
download audio + auto-captions for each video.

Two-stage by design:
  1. THIS spider (the `scrape` job kind) — discovers videos, downloads
     metadata + audio-only mp3 + auto-captions if available. Writes one
     raw record per video plus index entries to raw_audio/<channel>/.
  2. The `transcribe` job kind (packages.pipeline.transcribe) — runs
     faster-whisper over the downloaded audio and folds the transcript
     back into the raw record.

Separating them lets us:
  - cache audio once and re-transcribe later with a better whisper model
  - skip transcription for videos whose YouTube auto-captions already
    look usable (free win)
  - parallelize transcription against scraping

YouTube cookies: many data-center IPs (Hetzner included) are bot-flagged.
Set `YOUTUBE_COOKIES_FILE` in the environment to a path containing a
Netscape-format cookies.txt exported from a signed-in browser session.
Without cookies, this spider WILL fail with an explicit error rather
than silently producing nothing.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import yt_dlp

from packages.api.settings import DATA_DIR
from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter

log = logging.getLogger(__name__)

_AUDIO_DIR_NAME = "raw_audio"
_INDEX_NAME = "_index.jsonl"


def _audio_dir(slug: str, channel_slug: str) -> Path:
    d = DATA_DIR / slug / _AUDIO_DIR_NAME / channel_slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_index(audio_dir: Path) -> dict[str, dict]:
    """video_id → entry dict, indexed from the channel's _index.jsonl."""
    out: dict[str, dict] = {}
    p = audio_dir / _INDEX_NAME
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            vid = entry.get("video_id")
            if vid:
                out[vid] = entry  # later writes win — incremental
    return out


def _append_index(audio_dir: Path, entry: dict) -> None:
    with (audio_dir / _INDEX_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _cookies_path() -> str | None:
    p = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
    if not p:
        return None
    if not Path(p).exists():
        log.warning("YOUTUBE_COOKIES_FILE=%s does not exist; proceeding without", p)
        return None
    return p


def _base_ydl_opts() -> dict:
    """yt-dlp options common to every call.

    `tv_embedded` is the most-permissive player_client that survives bot
    detection on cold IPs as of 2026-05. We list a cascade so yt-dlp can
    try alternates if the first is rate-limited."""
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {
            "youtube": {"player_client": ["tv_embedded", "mweb", "web_safari"]}
        },
        # 1 retry then bail — bot-block looks like a permanent fail per video,
        # not something more retries fix.
        "retries": 1,
    }
    cookies = _cookies_path()
    if cookies:
        opts["cookiefile"] = cookies
    return opts


class YouTubeChannelSpider:
    def run(
        self,
        slug: str,
        source: SourceSpec,
        progress: Progress,
        *,
        run_id: int | None = None,
        force: bool = False,
    ) -> int:
        assert source.channel_url, "youtube_channel source needs channel_url"

        channel_slug = source.name
        audio_dir = _audio_dir(slug, channel_slug)
        seen = {} if force else _load_index(audio_dir)
        log.info(
            "youtube_channel: %s — channel=%s, already_indexed=%d",
            source.name,
            source.channel_url,
            len(seen),
        )

        # 1) Flat enumerate the channel — fast, no per-video metadata yet.
        flat_opts = {**_base_ydl_opts(), "extract_flat": "in_playlist"}
        try:
            with yt_dlp.YoutubeDL(flat_opts) as ydl:
                channel_info = ydl.extract_info(source.channel_url, download=False)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "Sign in to confirm" in msg or "bot" in msg.lower():
                raise RuntimeError(
                    f"YouTube bot-blocked this IP. Set YOUTUBE_COOKIES_FILE to a "
                    f"signed-in cookies.txt and retry. Underlying error: {msg[:200]}"
                ) from e
            raise

        entries = channel_info.get("entries") or []
        # entries can be flat (id+title only) or nested playlists; flatten one
        # level so we always work with concrete videos.
        videos: list[dict] = []
        for e in entries:
            if not e:
                continue
            if e.get("_type") == "playlist":
                for sub in (e.get("entries") or []):
                    if sub:
                        videos.append(sub)
            else:
                videos.append(e)

        log.info("youtube_channel: enumerated %d videos", len(videos))

        # 2) Filter to ones we haven't downloaded yet, and that pass length filters.
        pending: list[dict] = []
        for v in videos:
            vid = v.get("id")
            if not vid:
                continue
            if vid in seen and seen[vid].get("status") in (
                "downloaded",
                "transcribed",
            ):
                continue
            pending.append(v)

        if source.max_records is not None:
            pending = pending[: source.max_records]

        log.info("youtube_channel: %d new videos to download", len(pending))

        # 3) For each pending video: pull metadata, optionally subs, optionally audio.
        downloaded = 0
        with RecordWriter(slug, source.name, run_id=run_id) as writer:
            for v in pending:
                vid = v["id"]
                url = f"https://www.youtube.com/watch?v={vid}"
                try:
                    entry = self._fetch_one(audio_dir, source, url, vid)
                except Exception as e:
                    log.warning("youtube_channel: %s failed: %s", vid, e)
                    _append_index(
                        audio_dir,
                        {"video_id": vid, "status": "failed", "error": str(e)[:300]},
                    )
                    progress.page(url, 0)
                    continue

                _append_index(audio_dir, entry)
                writer.write(
                    {
                        "channel": channel_slug,
                        "video_id": vid,
                        "title": entry.get("title"),
                        "duration_sec": entry.get("duration_sec"),
                        "upload_date": entry.get("upload_date"),
                        "view_count": entry.get("view_count"),
                        "audio_path": entry.get("audio_path"),
                        "captions_lang": entry.get("captions_lang"),
                        "captions_path": entry.get("captions_path"),
                        "audio_url": url,
                        "status": entry["status"],
                    }
                )
                downloaded += 1
                progress.page(url, 1)
        return downloaded

    def _fetch_one(
        self,
        audio_dir: Path,
        source: SourceSpec,
        url: str,
        vid: str,
    ) -> dict:
        # First pull full metadata so we can apply length filters before
        # spending bandwidth on audio.
        meta_opts = _base_ydl_opts()
        with yt_dlp.YoutubeDL(meta_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        duration = info.get("duration") or 0
        if source.min_duration_sec and duration < source.min_duration_sec:
            return {
                "video_id": vid,
                "status": "skipped_short",
                "duration_sec": duration,
                "title": info.get("title"),
            }
        if source.max_duration_sec and duration > source.max_duration_sec:
            return {
                "video_id": vid,
                "status": "skipped_long",
                "duration_sec": duration,
                "title": info.get("title"),
            }

        # Persist the full info.json next to the audio.
        info_path = audio_dir / f"{vid}.info.json"
        info_path.write_text(
            json.dumps(info, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        captions_path: Path | None = None
        captions_lang: str | None = None
        if source.write_subs:
            captions_path, captions_lang = self._download_captions(
                audio_dir, url, vid, info
            )

        audio_path: Path | None = None
        if source.download_audio:
            audio_path = self._download_audio(audio_dir, source, url, vid)

        return {
            "video_id": vid,
            "status": "downloaded",
            "title": info.get("title"),
            "duration_sec": duration,
            "upload_date": info.get("upload_date"),
            "view_count": info.get("view_count"),
            "channel_id": info.get("channel_id"),
            "uploader": info.get("uploader"),
            "audio_path": str(audio_path) if audio_path else None,
            "captions_path": str(captions_path) if captions_path else None,
            "captions_lang": captions_lang,
        }

    def _download_captions(
        self,
        audio_dir: Path,
        url: str,
        vid: str,
        info: dict,
    ) -> tuple[Path | None, str | None]:
        # Prefer manual subs (human-curated), fall back to auto.
        manual = (info.get("subtitles") or {})
        auto = (info.get("automatic_captions") or {})
        for tag in ("ar", "ar-LB", "ar-SY", "ar-PS", "ar-EG"):
            if tag in manual:
                lang = tag
                source_kind = "manual"
                break
            if tag in auto:
                lang = tag
                source_kind = "auto"
                break
        else:
            return (None, None)

        opts = {
            **_base_ydl_opts(),
            "skip_download": True,
            "writeautomaticsub": source_kind == "auto",
            "writesubtitles": source_kind == "manual",
            "subtitleslangs": [lang],
            "subtitlesformat": "vtt",
            "outtmpl": str(audio_dir / "%(id)s.%(ext)s"),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        # yt-dlp writes <id>.<lang>.vtt
        candidate = audio_dir / f"{vid}.{lang}.vtt"
        return (candidate if candidate.exists() else None, lang)

    def _download_audio(
        self,
        audio_dir: Path,
        source: SourceSpec,
        url: str,
        vid: str,
    ) -> Path | None:
        opts = {
            **_base_ydl_opts(),
            "format": "bestaudio/best",
            "outtmpl": str(audio_dir / "%(id)s.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": source.audio_format,
                    "preferredquality": source.audio_quality,
                }
            ],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        candidate = audio_dir / f"{vid}.{source.audio_format}"
        return candidate if candidate.exists() else None
