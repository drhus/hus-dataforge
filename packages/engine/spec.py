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
class SourceSpec:
    name: str
    type: Literal["paginated", "fixture", "list_detail"]
    record_selector: str
    fields: dict[str, FieldSpec]

    # paginated
    url_template: str | None = None
    page_range: tuple[int, int] | None = None
    rate_limit_sec: float = 1.0

    # fixture (relative to project dir)
    fixture_path: str | None = None

    # list_detail
    list_url: str | None = None
    list_link_selector: str | None = None
    link_attr: str = "href"
    base_url: str | None = None  # for resolving relative links
    max_records: int | None = None


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
        if stype not in ("paginated", "fixture", "list_detail"):
            raise SpecError(
                f"source {name!r}: type must be one of paginated|fixture|list_detail (got {stype!r})"
            )
        rec_sel = s.get("record_selector")
        if not rec_sel:
            raise SpecError(f"source {name!r}: record_selector is required")
        fields = {k: _field_from_raw(v) for k, v in (s.get("fields") or {}).items()}
        if not fields:
            raise SpecError(f"source {name!r}: at least one field is required")

        src = SourceSpec(name=name, type=stype, record_selector=rec_sel, fields=fields)

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
        else:  # list_detail
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

        sources.append(src)

    return ProjectSpec(
        slug=slug,
        template=data.get("template", "generic"),
        sources=sources,
        cleaning=data.get("cleaning") or {},
        export=data.get("export") or {"format": "jsonl"},
    )
