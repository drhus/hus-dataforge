"""Build a LanceDB index over a project's exported Parquet corpus.

One row per record. Embedding stored as a fixed-width float32 array — LanceDB
auto-builds an IVF index when the table grows past a few thousand rows; below
that brute-force search is fast enough.

Long records (>~500 tokens) are truncated by the model, which is a real
quality issue for transcript-bulk rows (~30K chars each). For now we accept
that. Chunking is the next iteration.

Public API:
    build_index(project, *, model=None, force=False) -> dict
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from packages.api.settings import DATA_DIR

log = logging.getLogger(__name__)

DEFAULT_MODEL = "intfloat/multilingual-e5-large"
DEFAULT_DIM = 1024
TABLE_NAME = "records"
# E5 convention: documents prefixed with "passage:", queries with "query:".
_PASSAGE_PREFIX = "passage: "


def _index_dir(project: str) -> Path:
    return DATA_DIR / project / "rag.lance"


def _passage_text(row: dict) -> str:
    """Build the text we actually embed for a record.

    Prepend title when it's distinct from the body — helps E5 disambiguate
    structurally similar records (many transcripts share opening phrases)."""
    title = (row.get("title") or "").strip()
    text = (row.get("text") or "").strip()
    if title and not text.startswith(title):
        return _PASSAGE_PREFIX + f"{title}\n\n{text}"
    return _PASSAGE_PREFIX + text


def _record_iter(project: str):
    """Walk export/*.parquet, yielding flat dicts with the columns we want
    to keep on each LanceDB row. Skips sidecar/manifest files."""
    export_dir = DATA_DIR / project / "export"
    if not export_dir.exists():
        raise FileNotFoundError(
            f"no export dir for project {project!r}; run `dataforge export {project}` first"
        )
    for pq_path in sorted(export_dir.glob("*.parquet")):
        # NOTE: keep `_unattributed.parquet` — it's a real bucket, not a sidecar.
        # The only true sidecars in export/ are non-parquet (_stats.json, README.md).
        bucket = pq_path.stem  # e.g. "khalil-roukoz" or "_unattributed"
        try:
            t = pq.read_table(pq_path)
        except Exception as e:
            log.warning("rag.index: skip %s — %s", pq_path.name, e)
            continue
        rows = t.to_pylist()
        for r in rows:
            yield {
                "bucket": bucket,
                "record_id": str(r.get("id") or ""),
                "title": (r.get("title") or "")[:240],
                "text": r.get("text") or "",
                "lang": r.get("lang") or "",
                "source": r.get("source") or "",
                "source_kind": r.get("source_kind") or "",
                "source_url": r.get("source_url") or "",
                "word_count": int(r.get("word_count") or 0),
                "category": r.get("category") or "",
                "primary_category": r.get("primary_category") or "",
                "meta_json": r.get("meta_json") or "",
            }


def build_index(
    project: str,
    *,
    model: str | None = None,
    force: bool = False,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Build (or rebuild) the RAG index for a project.

    Returns:
        {project, table, rows, model, dim, took_sec}
    """
    import time

    import lancedb
    from fastembed import TextEmbedding

    model_name = model or DEFAULT_MODEL
    table_path = _index_dir(project)
    if force and table_path.exists():
        shutil.rmtree(table_path)
    table_path.parent.mkdir(parents=True, exist_ok=True)

    # Stream records first (cheap) so we can crash early on a bad project.
    records = list(_record_iter(project))
    if not records:
        raise FileNotFoundError(
            f"project {project!r} has no records in export/ — nothing to index"
        )
    log.info("rag.index: %s — %d records, model=%s", project, len(records), model_name)

    started = time.time()
    embedder = TextEmbedding(model_name=model_name)
    # Embed in batches; pyarrow can swallow the full list at end.
    passages = [_passage_text(r) for r in records]
    vectors: list[list[float]] = []
    for i in range(0, len(passages), batch_size):
        chunk = passages[i : i + batch_size]
        emb_iter = embedder.embed(chunk, batch_size=batch_size)
        for emb in emb_iter:
            vectors.append([float(x) for x in emb])
        if (i // batch_size) % 10 == 0:
            log.info("rag.index: embedded %d/%d", min(i + batch_size, len(passages)), len(passages))

    # Compose final rows
    db = lancedb.connect(str(table_path))
    rows = []
    for r, v in zip(records, vectors):
        rows.append({**r, "vector": v})
    if TABLE_NAME in db.table_names():
        db.drop_table(TABLE_NAME)
    table = db.create_table(TABLE_NAME, rows)
    took = round(time.time() - started, 2)
    log.info("rag.index: wrote %d rows to %s in %.1fs", len(rows), table_path, took)
    return {
        "project": project,
        "table": str(table_path),
        "rows": len(rows),
        "model": model_name,
        "dim": DEFAULT_DIM,
        "took_sec": took,
        "table_count": table.count_rows(),
    }
