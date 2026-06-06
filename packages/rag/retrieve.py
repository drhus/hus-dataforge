"""Top-k similarity search over a project's LanceDB index.

Filters use LanceDB's SQL-ish where-clause syntax — straight column names.
Examples:
    search("معنّى عن غربة", project="levant-zajal", top_k=10)
    search("...", where="bucket = 'khalil-roukoz'")
    search("...", where="bucket != '_unattributed' AND word_count > 80")

Returns the LanceDB rows with a `_distance` field (lower = more similar
for L2; higher = more similar for cosine). We expose `_score` as
`1 / (1 + distance)` so larger == better regardless of metric.
"""
from __future__ import annotations

import logging
from typing import Any

from packages.rag.index import DEFAULT_MODEL, TABLE_NAME, _index_dir

log = logging.getLogger(__name__)

_QUERY_PREFIX = "query: "


def search(
    query: str,
    project: str,
    *,
    top_k: int = 10,
    where: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Run a similarity search over the project's RAG index."""
    import lancedb
    from fastembed import TextEmbedding

    table_path = _index_dir(project)
    if not table_path.exists():
        raise FileNotFoundError(
            f"no rag index for {project!r}; run `dataforge rag-index {project}` first"
        )

    model_name = model or DEFAULT_MODEL
    embedder = TextEmbedding(model_name=model_name)
    q_text = _QUERY_PREFIX + (query or "").strip()
    q_vec = list(embedder.embed([q_text]))[0]
    q_vec = [float(x) for x in q_vec]

    db = lancedb.connect(str(table_path))
    table = db.open_table(TABLE_NAME)
    q = table.search(q_vec).limit(top_k)
    if where:
        q = q.where(where)
    hits = q.to_list()
    for h in hits:
        d = float(h.get("_distance") or 0.0)
        h["_score"] = round(1.0 / (1.0 + d), 4)
        # drop the heavy vector field — UI doesn't need it
        h.pop("vector", None)
    log.info(
        "rag.search: query=%r top_k=%d where=%r → %d hits",
        query[:60],
        top_k,
        where,
        len(hits),
    )
    return hits


__all__ = ["search"]
