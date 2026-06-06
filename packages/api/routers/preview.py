"""Preview endpoints — backing for the add-source wizards.

  POST /preview/detect          → detect spider type from a URL
  POST /preview/source          → dry-run a single source config, return samples
  POST /preview/suggest-cleanup → analyze samples, suggest CleanRules
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.engine.preview import (
    DEFAULT_SAMPLE_SIZE,
    detect_source_type,
    preview_source,
)

router = APIRouter(prefix="/preview", tags=["preview"])


class DetectIn(BaseModel):
    url: str


@router.post("/detect")
def detect(body: DetectIn):
    """Detect the most likely spider type from a URL — returns a partial
    source config the wizard can pre-fill."""
    if not body.url:
        raise HTTPException(status_code=400, detail="url is required")
    return detect_source_type(body.url)


class PreviewIn(BaseModel):
    project: str
    source: dict = Field(default_factory=dict)
    sample_size: int = DEFAULT_SAMPLE_SIZE


@router.post("/source")
def source(body: PreviewIn):
    """Dry-run a source config and return up to N sample records.

    Does not write to disk; safe to run repeatedly while the user tunes
    selectors."""
    return preview_source(
        body.project, body.source, sample_size=max(1, min(body.sample_size, 25))
    )


class SuggestCleanupIn(BaseModel):
    samples: list[dict]
    source_type: str | None = None


@router.post("/suggest-cleanup")
def suggest_cleanup(body: SuggestCleanupIn):
    """Look at the dry-run samples and propose cleanup rules.

    See packages.engine.cleanup_suggest for the heuristics."""
    from packages.engine.cleanup_suggest import suggest_clean_rules

    return suggest_clean_rules(body.samples, source_type=body.source_type)


class DiscoverIn(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    subject_type: str = "poet"


@router.post("/discover")
def discover(body: DiscoverIn):
    """Find candidate sources for a subject across known sites."""
    from packages.engine.discovery import discover_sources

    return {
        "name": body.name,
        "subject_type": body.subject_type,
        "candidates": discover_sources(
            body.name, aliases=body.aliases, subject_type=body.subject_type
        ),
    }


class YouTubeSearchIn(BaseModel):
    query: str
    max_results: int = Field(default=25, ge=1, le=100)


@router.post("/youtube-search")
def youtube_search(body: YouTubeSearchIn):
    """Enumerate top-N YouTube results for a search query.

    Used by the dashboard's "search + bulk add" widget. Returns flat video
    metadata (id, title, duration, channel, thumbnail) — no transcript fetch
    yet, that happens at scrape time once the user saves a youtube_transcripts
    source with this query."""
    from packages.engine.spiders.youtube_transcripts import enumerate_videos

    try:
        videos = enumerate_videos(search_query=body.query, max_results=body.max_results)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"youtube enumeration failed: {e!s}")
    out = []
    for v in videos:
        thumb = None
        thumbs = v.get("thumbnails") or []
        if thumbs:
            thumb = thumbs[-1].get("url")
        out.append(
            {
                "video_id": v.get("id"),
                "title": v.get("title"),
                "duration": v.get("duration"),
                "channel": v.get("channel") or v.get("uploader"),
                "channel_url": v.get("channel_url") or v.get("uploader_url"),
                "view_count": v.get("view_count"),
                "thumbnail": thumb,
                "url": f"https://www.youtube.com/watch?v={v.get('id')}" if v.get("id") else None,
            }
        )
    return {"query": body.query, "count": len(out), "results": out}
