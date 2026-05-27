"""Hus-DataForge scraping engine.

Public API:
    run_scrape(slug, *, progress=None) -> dict   # CLI + RQ worker entrypoint

Engine is config-driven: it reads projects/<slug>/config.yaml, resolves each
source to a Spider in the REGISTRY, runs it, and stores raw HTML + JSONL
records under data/<slug>/raw/."""
from __future__ import annotations

import inspect
import logging
import os
import time

from packages.api import projects_store
from packages.engine.progress import NullProgress, Progress
from packages.engine.spec import project_spec_from_dict
from packages.engine.spiders import REGISTRY

log = logging.getLogger(__name__)

# Inter-channel cooldown for Telegram MTProto: avoids back-to-back full-history
# pulls on the same account triggering session-level flood-waits.
TELEGRAM_INTER_CHANNEL_COOLDOWN_SEC = int(
    os.environ.get("DATAFORGE_TELEGRAM_COOLDOWN_SEC", "30")
)


def run_scrape(
    slug: str,
    *,
    progress: Progress | None = None,
    run_id: int | None = None,
    force: bool = False,
) -> dict:
    """Scrape all sources in the project.

    Default (force=False): incremental — list_detail skips URLs already
    in `_index.jsonl`, telegram_web stops at the prior max_post_id,
    telegram_mtproto uses min_id from its manifest.

    force=True: full re-fetch from scratch for every source."""
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
    last_was_mtproto = False
    for source in spec.sources:
        SpiderCls = REGISTRY.get(source.type)
        if SpiderCls is None:
            raise ValueError(f"unknown spider type: {source.type}")

        # cooldown between MTProto channels — protects the session from flood-wait
        if source.type == "telegram_mtproto" and last_was_mtproto:
            log.info(
                "telegram_mtproto inter-channel cooldown: sleeping %ds",
                TELEGRAM_INTER_CHANNEL_COOLDOWN_SEC,
            )
            time.sleep(TELEGRAM_INTER_CHANNEL_COOLDOWN_SEC)

        progress.start(source.name)
        log.info(
            "scrape: %s/%s (%s, run_id=%s, force=%s)",
            slug,
            source.name,
            source.type,
            run_id,
            force,
        )
        spider = SpiderCls()
        # Inspect the spider's actual signature so we only pass kwargs it
        # accepts — avoids try/except TypeError swallowing real spider errors.
        sig = inspect.signature(spider.run)
        kwargs: dict = {}
        if "run_id" in sig.parameters:
            kwargs["run_id"] = run_id
        if "force" in sig.parameters:
            kwargs["force"] = force
        totals_by_source[source.name] = spider.run(slug, source, progress, **kwargs)
        last_was_mtproto = source.type == "telegram_mtproto"

    progress.finish()
    return {
        "project": slug,
        "records_by_source": totals_by_source,
        "total_records": sum(totals_by_source.values()),
    }


__all__ = ["run_scrape"]
