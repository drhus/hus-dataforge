"""Hus-DataForge scraping engine.

Public API:
    run_scrape(slug, *, progress=None) -> dict   # CLI + RQ worker entrypoint

Engine is config-driven: it reads projects/<slug>/config.yaml, resolves each
source to a Spider in the REGISTRY, runs it, and stores raw HTML + JSONL
records under data/<slug>/raw/."""
from __future__ import annotations

import logging

from packages.api import projects_store
from packages.engine.progress import NullProgress, Progress
from packages.engine.spec import project_spec_from_dict
from packages.engine.spiders import REGISTRY

log = logging.getLogger(__name__)


def run_scrape(slug: str, *, progress: Progress | None = None) -> dict:
    progress = progress or NullProgress()
    raw_cfg = projects_store.get_project(slug).config
    if "_yaml" in raw_cfg and isinstance(raw_cfg["_yaml"], str):
        import yaml

        raw_cfg = yaml.safe_load(raw_cfg["_yaml"]) or {}

    spec = project_spec_from_dict(slug, raw_cfg)
    if not spec.sources:
        raise ValueError(
            f"project {slug!r} has no scrapable sources; add at least one source to config.yaml"
        )

    totals_by_source: dict[str, int] = {}
    for source in spec.sources:
        SpiderCls = REGISTRY.get(source.type)
        if SpiderCls is None:
            raise ValueError(f"unknown spider type: {source.type}")
        progress.start(source.name)
        log.info("scrape: %s/%s (%s)", slug, source.name, source.type)
        totals_by_source[source.name] = SpiderCls().run(slug, source, progress)

    progress.finish()
    return {
        "project": slug,
        "records_by_source": totals_by_source,
        "total_records": sum(totals_by_source.values()),
    }


__all__ = ["run_scrape"]
