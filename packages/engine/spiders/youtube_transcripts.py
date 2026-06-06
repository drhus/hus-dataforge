"""youtube_transcripts: zero-auth YouTube text pipeline.

The full youtube_channel spider (audio + Whisper) needs YouTube cookies
because Hetzner IPs are bot-flagged for per-video extracts. This spider
sidesteps that by:

  1. Enumerating channel/playlist videos via yt-dlp flat mode — that
     particular yt-dlp code path is NOT bot-blocked on data-center IPs.
  2. Pulling the YouTube auto-captions through notegpt.io's free public
     API, which fronts YouTube from its own residential infrastructure.

What you get: one record per video, with `text` = full concatenated
caption transcript, `segments` = per-line timestamps + text, plus the
usual video metadata. Quality is YouTube auto-caption quality (decent
for clear speech, weaker on heavily-musical zajal, but a strong baseline
that costs zero and runs in seconds per video — no model load, no audio
download).

When the higher-quality Whisper pipeline comes online (cookies dropped),
those records will dedup against these via fragment detection. This
spider's records get a `transcript_source: notegpt_auto` marker so we
can prefer Whisper transcripts later if both exist.

NOT a guarantee of stable behaviour: notegpt is a free third party.
If they rate-limit or shut the API, we fall back to other providers
in `_TRANSCRIPT_PROVIDERS` (one-line code change to swap).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import httpx
import yt_dlp

from packages.api.settings import DATA_DIR
from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter

log = logging.getLogger(__name__)

_TRANSCRIPTS_DIR_NAME = "raw_transcripts"


def _transcripts_dir(slug: str, source_name: str) -> Path:
    d = DATA_DIR / slug / _TRANSCRIPTS_DIR_NAME / source_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_seen_video_ids(d: Path) -> set[str]:
    """Already-fetched video_ids — used for incremental re-runs."""
    out: set[str] = set()
    for p in d.glob("*.json"):
        if p.stem != "_failed":
            out.add(p.stem)
    return out


# ---------- Transcript providers ----------
#
# Each provider takes a video_id and returns a dict:
#   {"text": str, "segments": [{"start": float, "end": float, "text": str}, ...]}
# or None if no transcript available. Raises on hard error.


def _notegpt_provider(video_id: str, *, lang: str = "ar") -> dict | None:
    """notegpt.io free transcript API. Returns ar_auto track if present.

    Response shape:
      {code:100000, message:"success", data:{
         videoInfo:{name, duration, author, ...},
         language_code:[{code:"ar_auto", ...}, ...],
         transcripts:{ar_auto:{custom:[{start,end,text}, ...]}}}}
    """
    r = httpx.get(
        "https://notegpt.io/api/v1/get-transcript-v2",
        params={"platform": "youtube", "video_id": video_id},
        timeout=30.0,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 100000:
        return None
    data = payload.get("data") or {}
    tracks = data.get("transcripts") or {}
    # Prefer manual over auto; prefer dialect-specific over generic ar.
    candidates = [
        f"{lang}_manual",
        f"{lang}-LB_auto",
        f"{lang}-SY_auto",
        f"{lang}-PS_auto",
        f"{lang}_auto",
    ]
    track_key = next((k for k in candidates if k in tracks), None)
    if not track_key:
        return None
    raw_segments = (tracks[track_key] or {}).get("custom") or []
    segments: list[dict] = []
    text_parts: list[str] = []
    for s in raw_segments:
        # notegpt times are "HH:MM:SS" strings
        start = _hms_to_sec(s.get("start", "00:00:00"))
        end = _hms_to_sec(s.get("end", "00:00:00"))
        txt = (s.get("text") or "").strip()
        if not txt:
            continue
        segments.append({"start": start, "end": end, "text": txt})
        text_parts.append(txt)
    return {
        "text": "\n".join(text_parts).strip(),
        "segments": segments,
        "track_key": track_key,
        "video_info": data.get("videoInfo") or {},
    }


def _hms_to_sec(s: str) -> float:
    try:
        parts = [float(p) for p in str(s).split(":")]
    except Exception:
        return 0.0
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, sec = parts[-3], parts[-2], parts[-1]
    return round(h * 3600 + m * 60 + sec, 3)


_TRANSCRIPT_PROVIDERS: dict[str, Callable[..., dict | None]] = {
    "notegpt": _notegpt_provider,
}


# ---------- Spider ----------


def enumerate_videos(
    *,
    channel_url: str | None = None,
    search_query: str | None = None,
    max_results: int = 25,
) -> list[dict]:
    """Return a flat list of video dicts for either a channel/playlist URL
    or a YouTube search query.

    Both modes use yt-dlp's `extract_flat='in_playlist'` mode, which is NOT
    bot-blocked on data-center IPs (unlike per-video extracts). The search
    mode uses yt-dlp's `ytsearch{N}:term` prefix.
    """
    if not channel_url and not search_query:
        raise ValueError("provide channel_url or search_query")
    target = channel_url or f"ytsearch{max_results}:{search_query}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "extractor_args": {"youtube": {"player_client": ["tv_embedded", "mweb"]}},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)
    entries = info.get("entries") or []
    out: list[dict] = []
    for e in entries:
        if not e:
            continue
        if e.get("_type") == "playlist":
            for sub in (e.get("entries") or []):
                if sub:
                    out.append(sub)
        else:
            out.append(e)
    return out


class YouTubeTranscriptsSpider:
    def run(
        self,
        slug: str,
        source: SourceSpec,
        progress: Progress,
        *,
        run_id: int | None = None,
        force: bool = False,
    ) -> int:
        if not source.channel_url and not source.search_query:
            raise AssertionError(
                "youtube_transcripts source needs channel_url or search_query"
            )

        source_dir = _transcripts_dir(slug, source.name)
        seen = set() if force else _load_seen_video_ids(source_dir)
        log.info(
            "youtube_transcripts: %s — mode=%s, already_indexed=%d",
            source.name,
            "search" if source.search_query else "channel",
            len(seen),
        )

        # Provider selection. SourceSpec doesn't have a dedicated field yet;
        # default to notegpt and read overrides from rate_limit_sec/etc later.
        provider_name = "notegpt"
        provider = _TRANSCRIPT_PROVIDERS[provider_name]

        # 1) Enumerate via yt-dlp flat mode (no auth needed).
        # In search mode the max_results cap goes INTO the ytsearchN prefix so
        # we don't waste an enumeration. The spider-level max_records still
        # applies for incremental + length-filtered pending list below.
        search_n = source.max_records or 25
        try:
            videos = enumerate_videos(
                channel_url=source.channel_url,
                search_query=source.search_query,
                max_results=search_n,
            )
        except yt_dlp.utils.DownloadError as e:
            raise RuntimeError(f"enumeration failed: {str(e)[:200]}") from e
        log.info("youtube_transcripts: enumerated %d videos", len(videos))

        # 2) Filter by length + already-fetched.
        pending: list[dict] = []
        for v in videos:
            vid = v.get("id")
            if not vid or vid in seen:
                continue
            dur = v.get("duration") or 0
            if source.min_duration_sec and dur and dur < source.min_duration_sec:
                continue
            if source.max_duration_sec and dur and dur > source.max_duration_sec:
                continue
            pending.append(v)
        if source.max_records is not None:
            pending = pending[: source.max_records]
        log.info("youtube_transcripts: %d new videos to transcribe", len(pending))

        # 3) For each video, fetch transcript and write a record.
        written = 0
        with RecordWriter(slug, source.name, run_id=run_id) as writer:
            for v in pending:
                vid = v["id"]
                url = f"https://www.youtube.com/watch?v={vid}"
                try:
                    transcript = provider(vid)
                except httpx.HTTPError as e:
                    log.warning("youtube_transcripts: %s provider HTTP error: %s", vid, e)
                    self._record_failure(source_dir, vid, f"http: {e}")
                    progress.page(url, 0)
                    continue
                except Exception as e:
                    log.warning("youtube_transcripts: %s unexpected: %s", vid, e)
                    self._record_failure(source_dir, vid, str(e)[:300])
                    progress.page(url, 0)
                    continue

                if not transcript or not transcript.get("text"):
                    self._record_failure(source_dir, vid, "no transcript available")
                    progress.page(url, 0)
                    continue

                # Persist raw transcript JSON for re-extract / re-clean cycles.
                (source_dir / f"{vid}.json").write_text(
                    json.dumps(
                        {
                            "video_id": vid,
                            "provider": provider_name,
                            "url": url,
                            "channel": source.name,
                            **transcript,
                            "flat_metadata": {
                                "title": v.get("title"),
                                "duration": v.get("duration"),
                                "view_count": v.get("view_count"),
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

                title = (transcript.get("video_info") or {}).get("name") or v.get("title")
                writer.write(
                    {
                        "channel": source.name,
                        "video_id": vid,
                        "title": title,
                        "text": transcript["text"],
                        "duration_sec": v.get("duration"),
                        "uploader": (transcript.get("video_info") or {}).get("author"),
                        "video_url": url,
                        "transcript_source": f"{provider_name}_auto",
                        "track": transcript.get("track_key"),
                        "segment_count": len(transcript.get("segments") or []),
                        "_source_url": url,
                    }
                )
                written += 1
                progress.page(url, 1)
        return written

    def _record_failure(self, source_dir: Path, video_id: str, reason: str) -> None:
        failed_log = source_dir / "_failed.jsonl"
        with failed_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"video_id": video_id, "reason": reason}, ensure_ascii=False) + "\n")
