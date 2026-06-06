"""Retrieval-augmented generation over a dataforge project's exported corpus.

Three building blocks:
  - index.py    : embed the export Parquet(s) into a LanceDB store
  - retrieve.py : top-k similarity search with metadata filters
  - generate.py : Claude SDK call with retrieved samples as few-shot context

All three are project-scoped — each project gets its own LanceDB at
data/<project>/rag.lance/. Index once after every export, retrieve and
generate freely.

For now the canonical embedding model is `intfloat/multilingual-e5-large`
served via fastembed (ONNX runtime; no PyTorch dependency). E5 expects
documents prefixed with "passage:" and queries prefixed with "query:" —
the helpers in this package handle that automatically.
"""

from packages.rag.index import build_index
from packages.rag.retrieve import search

__all__ = ["build_index", "search"]
