"""Project spec types loaded from projects/<slug>/config.yaml.

Spec is intentionally small for V1 — paginated + fixture spider types only.
sitemap / api / js_rendered get added when we hit a site that needs them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class FieldSpec:
    selector: str
    attr: str = "text"  # "text" | "html" | any HTML attribute name
    multi: bool = False  # if True, collect all matching elements joined by `join_with`
    join_with: str = "\n"


@dataclass
class CategorizeRule:
    """A single rule: if any of `text_contains_any` appears in the record text,
    assign category `set_category`. Rules are checked in order; first match wins."""

    text_contains_any: list[str]
    set_category: str


# Per-source cleanup rules — applied during normalization.
# Each op is a {"op": <name>, ...args} dict for easy YAML/JSON serialization.
# Title ops, in order of application:
#   - {"op": "split_last", "separator": "»", "if_starts_with": "الديوان"}
#       Take the last segment after splitting on separator. The `if_starts_with`
#       guard skips titles that don't begin with the given prefix (so cleaner
#       titles pass through untouched).
#   - {"op": "regex_replace", "pattern": "...", "replacement": "..."}
#
# Text ops, in order of application:
#   - {"op": "truncate_before_first_of", "markers": ["a", "b", ...]}
#       Drop content from the first line containing any of these markers
#       onward — useful for stripping page chrome at the bottom.
#   - {"op": "strip_lines_matching", "pattern": "..."}
#       Remove every line matching the regex (multi-line, leaves rest intact).
#   - {"op": "regex_replace", "pattern": "...", "replacement": "..."}
#
# Filter (applied after text cleanup; record dropped if any check fails):
#   - min_chars: int        (default 20)
#   - min_lines: int        (default 0)
#   - min_arabic_ratio: float  (default 0.4 — set to 0 for non-Arabic corpora)
#   - drop_if_url_dominated: bool  (default True)


@dataclass
class CleanRules:
    title_ops: list[dict] = field(default_factory=list)
    text_ops: list[dict] = field(default_factory=list)
    filter_min_chars: int = 20
    filter_min_lines: int = 0
    filter_min_arabic_ratio: float = 0.4
    drop_if_url_dominated: bool = True


# Per-spider-type defaults. Used when the source has no explicit clean_rules.
# Existing aldiwan behavior preserved as the default for list_detail /
# multi_level_list_detail / paginated sources.
_ALDIWAN_DEFAULT_TITLE_OPS = [
    {"op": "split_last", "separator": "»", "if_starts_with": "الديوان"},
]
_ALDIWAN_DEFAULT_TEXT_OPS = [
    {
        "op": "truncate_before_first_of",
        "markers": [
            "المزيد عن",
            "أضف معلومة",
            "أضف تعليق",
            "اقتباسات",
            "تعليقات",
        ],
    },
]

# Telegram channels universally append: signature hashtags, @handles,
# decorative emoji, and Unicode bidi marks. Strip these by default so the
# poem text is clean before dedup. Date extraction is per-source (only some
# channels date-stamp every post — added on the source where it applies).
_TELEGRAM_DEFAULT_TEXT_OPS = [
    # Strip Unicode bidi / direction marks + ZWJ/ZWNJ + BOM. (ZWNJ in
    # particular is common as a "stealth space" before signature hashtags.)
    {
        "op": "regex_replace",
        "pattern": "[‌‍‎‏‪-‮⁦-⁩﻿]",
        "replacement": "",
    },
    # Strip decorative emoji / pictographs WHEREVER they appear (lots of
    # channels glue emoji onto the @handle line — e.g. "@x💛🌿" — so we strip
    # them inline before the line-level rules).
    {
        "op": "regex_replace",
        "pattern": "[☀-➿\U0001f000-\U0001fbff]+",
        "replacement": "",
    },
    # Drop lines that are JUST a hashtag (#author_tag, #قصيدة_جديدة, etc.)
    {"op": "strip_lines_matching", "pattern": r"^\s*#\S+\s*$"},
    # Drop lines that are JUST a Telegram @handle (now that emoji are gone,
    # the trailing junk is whitespace which the \s* tolerates).
    {"op": "strip_lines_matching", "pattern": r"^\s*@[A-Za-z0-9_]+\s*$"},
    # Drop lines that are just dots/dashes/equals/underscores (separators)
    {"op": "strip_lines_matching", "pattern": r"^[\s.\-_=•·]+$"},
]

_DEFAULT_CLEAN_RULES_BY_TYPE: dict[str, CleanRules] = {
    "list_detail": CleanRules(
        title_ops=list(_ALDIWAN_DEFAULT_TITLE_OPS),
        text_ops=list(_ALDIWAN_DEFAULT_TEXT_OPS),
    ),
    "multi_level_list_detail": CleanRules(
        title_ops=list(_ALDIWAN_DEFAULT_TITLE_OPS),
        text_ops=list(_ALDIWAN_DEFAULT_TEXT_OPS),
    ),
    "paginated": CleanRules(
        title_ops=list(_ALDIWAN_DEFAULT_TITLE_OPS),
        text_ops=list(_ALDIWAN_DEFAULT_TEXT_OPS),
    ),
    "telegram_web": CleanRules(text_ops=list(_TELEGRAM_DEFAULT_TEXT_OPS)),
    "telegram_mtproto": CleanRules(text_ops=list(_TELEGRAM_DEFAULT_TEXT_OPS)),
    "x_syndication": CleanRules(),
    "fixture": CleanRules(),
    # Transcribed audio is mostly clean already — no per-line markers
    # to strip. Tighten later if Whisper hallucinations turn out to
    # share signatures across recordings.
    "youtube_channel": CleanRules(filter_min_arabic_ratio=0.3),
    # Auto-captions can be noisy — long enough threshold to drop empty/garbled
    # records, but lower Arabic ratio because Whisper/notegpt sometimes
    # inject Latin punctuation or English bridge words.
    "youtube_transcripts": CleanRules(
        filter_min_chars=80,
        filter_min_arabic_ratio=0.3,
    ),
}


def default_clean_rules(source_type: str) -> CleanRules:
    """Return a fresh copy of the default rules for a source type."""
    base = _DEFAULT_CLEAN_RULES_BY_TYPE.get(source_type, CleanRules())
    return CleanRules(
        title_ops=list(base.title_ops),
        text_ops=list(base.text_ops),
        filter_min_chars=base.filter_min_chars,
        filter_min_lines=base.filter_min_lines,
        filter_min_arabic_ratio=base.filter_min_arabic_ratio,
        drop_if_url_dominated=base.drop_if_url_dominated,
    )


@dataclass
class SourceSpec:
    name: str
    type: Literal[
        "paginated",
        "fixture",
        "list_detail",
        "multi_level_list_detail",
        "telegram_web",
        "telegram_mtproto",
        "x_syndication",
        "youtube_channel",
        "youtube_transcripts",
    ]
    record_selector: str
    fields: dict[str, FieldSpec]
    # `subject` is the canonical name; `poet` is kept as a legacy alias.
    # When both are set, `subject` wins. Either field carries the slug of the
    # subject manifest this source contributes to.
    subject: str | None = None
    poet: str | None = None  # legacy alias for subject (type=poet)

    # paginated
    url_template: str | None = None
    page_range: tuple[int, int] | None = None
    rate_limit_sec: float = 1.0

    # fixture (relative to project dir)
    fixture_path: str | None = None

    # list_detail / multi_level_list_detail
    list_url: str | None = None
    list_link_selector: str | None = None
    sub_link_selector: str | None = None  # multi_level only
    link_attr: str = "href"
    base_url: str | None = None  # for resolving relative links
    max_records: int | None = None

    # youtube_channel — see packages/engine/spiders/youtube_channel.py
    # channel_url is the public URL of a channel (https://www.youtube.com/@handle)
    # or a playlist URL. Spider enumerates videos, downloads audio + tries
    # auto-subs. Cookies are read from $YOUTUBE_COOKIES_FILE if set.
    channel_url: str | None = None
    min_duration_sec: int | None = None  # skip videos shorter than this
    max_duration_sec: int | None = None  # skip videos longer than this
    write_subs: bool = True              # save auto-captions when available
    download_audio: bool = True          # download audio-only mp3 (for transcribe)
    audio_format: str = "mp3"
    audio_quality: str = "0"             # 0=best, 9=worst (yt-dlp scale)

    # categorization (cleaning-stage)
    # primary_category records flow into clean/<poet>.jsonl
    # non-primary records flow into clean/<poet>__<category>.jsonl (sidecars)
    primary_category: str = "poetry"
    categorize: list[CategorizeRule] = field(default_factory=list)
    fallback_category: str | None = None  # if no rule matches; defaults to primary_category

    # telegram_mtproto tail-extension
    # If set, the MTProto spider reads min post_id from the named source's
    # raw JSONL and uses max_id = (that_min - 1) — so we ONLY fetch messages
    # OLDER than what the (anonymous) web mirror already has. Web mirror stays
    # primary; MTProto only kicks in for the tail past the mirror's window.
    extend_below_source: str | None = None

    # Per-source cleanup rules (see CleanRules above). Populated with
    # type-appropriate defaults at spec-parse time; user can override
    # any/all fields via the project config.
    clean_rules: CleanRules = field(default_factory=CleanRules)


@dataclass
class ProjectSpec:
    slug: str
    template: str = "generic"
    sources: list[SourceSpec] = field(default_factory=list)
    cleaning: dict = field(default_factory=dict)
    export: dict = field(default_factory=lambda: {"format": "jsonl"})


class SpecError(ValueError):
    pass


def _field_from_raw(raw) -> FieldSpec:
    if isinstance(raw, str):
        return FieldSpec(selector=raw)
    if isinstance(raw, dict) and "selector" in raw:
        return FieldSpec(
            selector=raw["selector"],
            attr=raw.get("attr", "text"),
            multi=bool(raw.get("multi", False)),
            join_with=raw.get("join_with", "\n"),
        )
    raise SpecError(f"invalid field spec: {raw!r}")


def project_spec_from_dict(slug: str, data: dict) -> ProjectSpec:
    sources_raw = data.get("sources") or []
    sources: list[SourceSpec] = []
    for i, s in enumerate(sources_raw):
        if not isinstance(s, dict):
            # legacy minimal config like ["qafiyah.com"] — skip with no error,
            # but we need at least one real source to scrape
            continue
        name = s.get("name") or f"source-{i}"
        stype = s.get("type")
        if stype not in (
            "paginated",
            "fixture",
            "list_detail",
            "multi_level_list_detail",
            "telegram_web",
            "telegram_mtproto",
            "x_syndication",
            "youtube_channel",
            "youtube_transcripts",
        ):
            raise SpecError(
                f"source {name!r}: unknown spider type {stype!r}"
            )
        # social + media spiders have a fixed output schema — record_selector/fields not required
        social_types = (
            "telegram_web",
            "telegram_mtproto",
            "x_syndication",
            "youtube_channel",
            "youtube_transcripts",
        )
        rec_sel = s.get("record_selector") or ("" if stype in social_types else None)
        if rec_sel is None:
            raise SpecError(f"source {name!r}: record_selector is required")
        fields_raw = s.get("fields") or {}
        if not fields_raw and stype not in social_types:
            raise SpecError(f"source {name!r}: at least one field is required")
        fields = {k: _field_from_raw(v) for k, v in fields_raw.items()}

        # subject takes precedence; poet is the legacy alias
        subj = s.get("subject") or s.get("poet")
        src = SourceSpec(
            name=name,
            type=stype,
            record_selector=rec_sel,
            fields=fields,
            subject=subj,
            poet=s.get("poet"),  # preserved for older callers/tests
            clean_rules=default_clean_rules(stype),
        )

        # Per-source override of cleanup rules.
        #   - title_ops / text_ops  → REPLACE the per-type defaults entirely.
        #   - title_ops_extra / text_ops_extra → APPEND to the per-type defaults
        #     (use this when you want to add a rule without losing the
        #     channel-type baseline, e.g. Telegram hashtag/handle strip).
        cr_raw = s.get("clean_rules") or {}
        if cr_raw and not isinstance(cr_raw, dict):
            raise SpecError(f"source {name!r}: clean_rules must be an object")
        if "title_ops" in cr_raw:
            src.clean_rules.title_ops = list(cr_raw["title_ops"] or [])
        if "title_ops_extra" in cr_raw:
            src.clean_rules.title_ops = src.clean_rules.title_ops + list(
                cr_raw["title_ops_extra"] or []
            )
        if "text_ops" in cr_raw:
            src.clean_rules.text_ops = list(cr_raw["text_ops"] or [])
        if "text_ops_extra" in cr_raw:
            src.clean_rules.text_ops = src.clean_rules.text_ops + list(
                cr_raw["text_ops_extra"] or []
            )
        if "filter_min_chars" in cr_raw:
            src.clean_rules.filter_min_chars = int(cr_raw["filter_min_chars"])
        if "filter_min_lines" in cr_raw:
            src.clean_rules.filter_min_lines = int(cr_raw["filter_min_lines"])
        if "filter_min_arabic_ratio" in cr_raw:
            src.clean_rules.filter_min_arabic_ratio = float(cr_raw["filter_min_arabic_ratio"])
        if "drop_if_url_dominated" in cr_raw:
            src.clean_rules.drop_if_url_dominated = bool(cr_raw["drop_if_url_dominated"])

        # categorize block (applies in the cleaning stage)
        cat_raw = s.get("categorize") or []
        if cat_raw and not isinstance(cat_raw, list):
            raise SpecError(f"source {name!r}: categorize must be a list of rules")
        for rule in cat_raw:
            if not isinstance(rule, dict):
                raise SpecError(f"source {name!r}: each categorize rule must be a dict")
            needles = rule.get("text_contains_any") or []
            if isinstance(needles, str):
                needles = [needles]
            cat = rule.get("set_category")
            if not needles or not cat:
                raise SpecError(
                    f"source {name!r}: categorize rule needs text_contains_any + set_category"
                )
            src.categorize.append(CategorizeRule(text_contains_any=needles, set_category=cat))
        if s.get("primary_category"):
            src.primary_category = s["primary_category"]
        if "fallback_category" in s:
            src.fallback_category = s["fallback_category"]

        # youtube_channel + youtube_transcripts share the channel_url shape
        if stype in ("youtube_channel", "youtube_transcripts"):
            src.channel_url = s.get("channel_url") or s.get("list_url")
            if not src.channel_url:
                raise SpecError(
                    f"source {name!r}: youtube_channel needs channel_url"
                )
            src.min_duration_sec = s.get("min_duration_sec")
            src.max_duration_sec = s.get("max_duration_sec")
            if "write_subs" in s:
                src.write_subs = bool(s["write_subs"])
            if "download_audio" in s:
                src.download_audio = bool(s["download_audio"])
            if "audio_format" in s:
                src.audio_format = str(s["audio_format"])
            if "audio_quality" in s:
                src.audio_quality = str(s["audio_quality"])
            if "max_records" in s:
                src.max_records = s["max_records"]

        if stype == "paginated":
            src.url_template = s.get("url_template")
            pr = s.get("page_range")
            if not src.url_template or not pr or len(pr) != 2:
                raise SpecError(
                    f"source {name!r}: paginated needs url_template and page_range [start, end]"
                )
            src.page_range = (int(pr[0]), int(pr[1]))
            src.rate_limit_sec = float(s.get("rate_limit_sec", 1.0))
        elif stype == "fixture":
            src.fixture_path = s.get("fixture_path")
            if not src.fixture_path:
                raise SpecError(f"source {name!r}: fixture_path required for fixture type")
        elif stype == "list_detail":
            src.list_url = s.get("list_url")
            src.list_link_selector = s.get("list_link_selector")
            src.base_url = s.get("base_url") or src.list_url
            src.link_attr = s.get("link_attr", "href")
            src.rate_limit_sec = float(s.get("rate_limit_sec", 1.0))
            mr = s.get("max_records")
            src.max_records = int(mr) if mr is not None else None
            if not src.list_url or not src.list_link_selector:
                raise SpecError(
                    f"source {name!r}: list_detail needs list_url and list_link_selector"
                )
        elif stype == "multi_level_list_detail":
            src.list_url = s.get("list_url")
            src.list_link_selector = s.get("list_link_selector")
            src.sub_link_selector = s.get("sub_link_selector")
            src.base_url = s.get("base_url") or src.list_url
            src.link_attr = s.get("link_attr", "href")
            src.rate_limit_sec = float(s.get("rate_limit_sec", 1.0))
            mr = s.get("max_records")
            src.max_records = int(mr) if mr is not None else None
            if not (src.list_url and src.list_link_selector and src.sub_link_selector):
                raise SpecError(
                    f"source {name!r}: multi_level_list_detail needs list_url, "
                    "list_link_selector, and sub_link_selector"
                )
        elif stype == "telegram_web":
            channel = s.get("channel")
            src.list_url = s.get("list_url") or (f"https://t.me/s/{channel}" if channel else None)
            src.rate_limit_sec = float(s.get("rate_limit_sec", 1.0))
            mr = s.get("max_records")
            src.max_records = int(mr) if mr is not None else 200
            if not src.list_url:
                raise SpecError(
                    f"source {name!r}: telegram_web needs `channel: <name>` or list_url"
                )
        elif stype == "telegram_mtproto":
            channel = s.get("channel")
            if not channel:
                raise SpecError(f"source {name!r}: telegram_mtproto needs `channel: <username>`")
            src.fixture_path = channel
            src.rate_limit_sec = float(s.get("rate_limit_sec", 0.0))
            mr = s.get("max_records")
            src.max_records = int(mr) if mr is not None else 5000
            src.extend_below_source = s.get("extend_below_source")
        elif stype == "x_syndication":
            handle = s.get("handle")
            if not handle:
                raise SpecError(f"source {name!r}: x_syndication needs `handle: <screen_name>`")
            src.fixture_path = handle
            src.rate_limit_sec = float(s.get("rate_limit_sec", 5.0))
            mr = s.get("max_records")
            src.max_records = int(mr) if mr is not None else None

        sources.append(src)

    return ProjectSpec(
        slug=slug,
        template=data.get("template", "generic"),
        sources=sources,
        cleaning=data.get("cleaning") or {},
        export=data.get("export") or {"format": "jsonl"},
    )
