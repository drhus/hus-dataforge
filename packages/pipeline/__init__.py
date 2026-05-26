"""Hus-DataForge cleaning pipeline (Milestone 3).

Input:  data/<slug>/raw/<source>.jsonl       — raw scraped records
Output: data/<slug>/clean/<poet>.jsonl       — canonical, deduped, ar-only

Public API:
    run_clean(slug, *, progress=None) -> dict
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from packages.api import projects_store
from packages.api.settings import DATA_DIR, PROJECTS_DIR
from packages.engine.progress import NullProgress, Progress
from packages.engine.spec import project_spec_from_dict
from packages.pipeline.dedup import Deduper
from packages.pipeline.io import write_records
from packages.pipeline.normalize import normalize_record

log = logging.getLogger(__name__)


def _read_jsonl(path: Path):
    import json

    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                log.warning("skipping malformed jsonl line in %s: %s", path, e)


def _poet_manifests(slug: str) -> dict[str, dict]:
    """Load poet manifests from projects/<slug>/poets/*.yaml."""
    import yaml

    out: dict[str, dict] = {}
    pdir = PROJECTS_DIR / slug / "poets"
    if not pdir.exists():
        return out
    for f in pdir.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            out[f.stem] = data
        except Exception as e:
            log.warning("could not load %s: %s", f, e)
    return out


def run_clean(slug: str, *, progress: Progress | None = None) -> dict:
    progress = progress or NullProgress()

    raw_cfg = projects_store.get_project(slug).config
    if "_yaml" in raw_cfg and isinstance(raw_cfg["_yaml"], str):
        import yaml

        raw_cfg = yaml.safe_load(raw_cfg["_yaml"]) or {}
    spec = project_spec_from_dict(slug, raw_cfg)

    source_to_poet: dict[str, str] = {}
    source_kinds: dict[str, str] = {}
    for s in spec.sources:
        if s.poet:
            source_to_poet[s.name] = s.poet
        source_kinds[s.name] = s.type

    poets = _poet_manifests(slug)
    log.info("clean: loaded %d poet manifests", len(poets))

    raw_dir = DATA_DIR / slug / "raw"
    clean_dir = DATA_DIR / slug / "clean"
    clean_dir.mkdir(parents=True, exist_ok=True)

    per_poet: dict[str, list[dict]] = defaultdict(list)
    stats = {
        "input_total": 0,
        "filtered_out": 0,
        "dedup_dropped": 0,
        "output_total": 0,
        "by_poet": defaultdict(
            lambda: {"input": 0, "kept": 0, "dropped_filter": 0, "dropped_dedup": 0}
        ),
        "by_source": defaultdict(lambda: {"input": 0, "kept": 0}),
    }

    for source_jsonl in sorted(raw_dir.glob("*.jsonl")):
        if source_jsonl.name == "_index.jsonl":
            continue
        source_name = source_jsonl.stem
        poet = source_to_poet.get(source_name) or _guess_poet_from_source_name(source_name, poets)
        kind = _engine_type_to_kind(source_kinds.get(source_name) or _guess_kind_from_source_name(source_name))
        progress.start(f"clean:{source_name}")

        for raw in _read_jsonl(source_jsonl):
            stats["input_total"] += 1
            stats["by_source"][source_name]["input"] += 1
            if poet:
                stats["by_poet"][poet]["input"] += 1
            canonical = normalize_record(
                raw, source_name=source_name, source_kind=kind, poet=poet
            )
            if canonical is None:
                stats["filtered_out"] += 1
                if poet:
                    stats["by_poet"][poet]["dropped_filter"] += 1
                continue
            per_poet[canonical["poet"] or "_unattributed"].append(canonical)

        progress.page(str(source_jsonl), stats["by_source"][source_name]["input"])

    for poet_slug, records in per_poet.items():
        deduper = Deduper()
        kept: list[dict] = []
        for r in records:
            if deduper.is_dup(r):
                stats["dedup_dropped"] += 1
                stats["by_poet"][poet_slug]["dropped_dedup"] += 1
                continue
            kept.append(r)
            stats["by_poet"][poet_slug]["kept"] += 1
            stats["by_source"][r["source"]]["kept"] += 1
        out_path = clean_dir / f"{poet_slug}.jsonl"
        write_records(out_path, kept)
        log.info("clean: wrote %d records to %s", len(kept), out_path)
        stats["output_total"] += len(kept)

    progress.finish()

    stats["by_poet"] = {k: dict(v) for k, v in stats["by_poet"].items()}
    stats["by_source"] = {k: dict(v) for k, v in stats["by_source"].items()}
    return {"project": slug, **stats}


def _engine_type_to_kind(engine_type: str) -> str:
    """Map engine spider type → cleaning source_kind."""
    if engine_type in ("telegram_web", "telegram_mtproto"):
        return "telegram"
    if engine_type in ("list_detail", "multi_level_list_detail", "paginated"):
        return "aldiwan"  # all our list_detail sources are aldiwan-shaped for V1
    if engine_type == "fixture":
        return "fixture"
    if engine_type == "x_syndication":
        return "x"
    return engine_type or "unknown"


def _guess_poet_from_source_name(source_name: str, poets: dict[str, dict]) -> str | None:
    low = source_name.lower()
    for slug in poets:
        if slug in low or slug.replace("-", "") in low.replace("-", ""):
            return slug
    aliases = {
        "alarje": "hudhayfah-alarje",
        "el-arje": "hudhayfah-alarje",
        "el_arje": "hudhayfah-alarje",
        "eqbal-anas": "anas-aldaghim",
        "eqbalanas": "anas-aldaghim",
        "qabbani": "nizar-qabbani",
        "nizar": "nizar-qabbani",
    }
    for needle, slug in aliases.items():
        if needle in low and slug in poets:
            return slug
    return None


def _guess_kind_from_source_name(source_name: str) -> str:
    low = source_name.lower()
    if "aldiwan" in low:
        return "list_detail"
    if "telegram" in low:
        return "telegram_web"
    if low.startswith("x-") or "twitter" in low:
        return "x_syndication"
    if "fixture" in low:
        return "fixture"
    return "unknown"


__all__ = ["run_clean"]
