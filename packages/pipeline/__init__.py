"""Hus-DataForge cleaning pipeline (Milestone 3).

Input:  data/<slug>/raw/<source>.jsonl       — raw scraped records
Output: data/<slug>/clean/<poet>.jsonl       — primary-category (e.g. poetry)
        data/<slug>/clean/<poet>__<cat>.jsonl — sidecars per non-primary category

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
from packages.engine.spec import SourceSpec, project_spec_from_dict
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


def _categorize(record: dict, source: SourceSpec | None) -> str:
    """Return the category for this record under this source's rules.

    If no rules → primary_category. If rules but none match → fallback_category
    (which defaults to primary_category, keeping pre-feature behavior intact)."""
    if source is None:
        return "poetry"
    if not source.categorize:
        return source.primary_category
    text = record.get("text") or ""
    for rule in source.categorize:
        if any(needle in text for needle in rule.text_contains_any):
            return rule.set_category
    return source.fallback_category or source.primary_category


def run_clean(slug: str, *, progress: Progress | None = None) -> dict:
    progress = progress or NullProgress()

    raw_cfg = projects_store.get_project(slug).config
    if "_yaml" in raw_cfg and isinstance(raw_cfg["_yaml"], str):
        import yaml

        raw_cfg = yaml.safe_load(raw_cfg["_yaml"]) or {}
    spec = project_spec_from_dict(slug, raw_cfg)

    source_by_name: dict[str, SourceSpec] = {s.name: s for s in spec.sources}
    poets = _poet_manifests(slug)
    log.info("clean: loaded %d poet manifests", len(poets))

    raw_dir = DATA_DIR / slug / "raw"
    clean_dir = DATA_DIR / slug / "clean"
    clean_dir.mkdir(parents=True, exist_ok=True)

    # group by (poet, category) so dedup happens at that scope
    per_bucket: dict[tuple[str, str], list[dict]] = defaultdict(list)
    stats = {
        "input_total": 0,
        "filtered_out": 0,
        "dedup_dropped": 0,
        "output_total": 0,
        "by_poet": defaultdict(
            lambda: {"input": 0, "kept": 0, "dropped_filter": 0, "dropped_dedup": 0}
        ),
        "by_source": defaultdict(lambda: {"input": 0, "kept": 0}),
        "by_category": defaultdict(int),
    }

    for source_jsonl in sorted(raw_dir.glob("*.jsonl")):
        if source_jsonl.name == "_index.jsonl":
            continue
        source_name = source_jsonl.stem
        source = source_by_name.get(source_name)
        poet = (source.poet if source else None) or _guess_poet_from_source_name(
            source_name, poets
        )
        kind = _engine_type_to_kind(
            (source.type if source else None) or _guess_kind_from_source_name(source_name)
        )
        primary_cat = source.primary_category if source else "poetry"
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
            category = _categorize(canonical, source)
            canonical["category"] = category
            canonical["primary_category"] = primary_cat
            bucket = (canonical["poet"] or "_unattributed", category)
            per_bucket[bucket].append(canonical)

        progress.page(str(source_jsonl), stats["by_source"][source_name]["input"])

    # dedup per bucket (a poem and the same poem reposted as commentary should NOT dedup
    # against each other — they have different intent in the corpus)
    for (poet_slug, category), records in per_bucket.items():
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
            stats["by_category"][category] += 1

        # primary category → <poet>.jsonl (main bucket; what HF/training uses)
        # any other → <poet>__<category>.jsonl sidecar
        is_primary = any(
            s.primary_category == category for s in spec.sources if s.poet == poet_slug
        ) or (category == "poetry" and not any(s.poet == poet_slug for s in spec.sources))
        if is_primary:
            out_path = clean_dir / f"{poet_slug}.jsonl"
        else:
            out_path = clean_dir / f"{poet_slug}__{category}.jsonl"
        write_records(out_path, kept)
        log.info("clean: wrote %d records to %s", len(kept), out_path)
        stats["output_total"] += len(kept)

    progress.finish()

    stats["by_poet"] = {k: dict(v) for k, v in stats["by_poet"].items()}
    stats["by_source"] = {k: dict(v) for k, v in stats["by_source"].items()}
    stats["by_category"] = dict(stats["by_category"])
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
