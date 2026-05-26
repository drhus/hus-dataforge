"""Two-stage dedup: exact-hash + MinHash near-dup on a normalized signature.

`Deduper` is stateful per scope (typically one poet). Call .is_dup(record)
in stream order; first occurrence wins."""
from __future__ import annotations

import re

from datasketch import MinHash, MinHashLSH

# Tashkeel + tatweel + non-Arabic word chars — strip for the dedup signature
# while keeping the original text intact in the canonical record.
_DIACRITICS = re.compile(r"[ً-ٰٟـ]")
_NON_WORD = re.compile(r"[^\w؀-ۿ]+")


def signature(text: str) -> str:
    text = _DIACRITICS.sub("", text)
    text = text.lower()
    text = _NON_WORD.sub(" ", text).strip()
    return text


def _shingles(text: str, k: int = 5) -> list[str]:
    text = signature(text)
    if not text:
        return []
    if len(text) < k:
        return [text]
    return [text[i : i + k] for i in range(len(text) - k + 1)]


class Deduper:
    """Per-scope dedup. Threshold 0.85 = drop only true near-dups."""

    def __init__(self, threshold: float = 0.85, num_perm: int = 128):
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._exact_ids: set[str] = set()
        self._next_idx = 0

    def _minhash(self, text: str) -> MinHash | None:
        sh = _shingles(text)
        if not sh:
            return None
        m = MinHash(num_perm=self.num_perm)
        for s in sh:
            m.update(s.encode("utf-8"))
        return m

    def is_dup(self, record: dict) -> bool:
        # exact-hash gate first
        rid = record.get("id")
        if rid and rid in self._exact_ids:
            return True
        if rid:
            self._exact_ids.add(rid)

        # near-dup
        m = self._minhash(record.get("text") or "")
        if m is None:
            return False
        if self.lsh.query(m):
            return True
        key = f"r{self._next_idx}"
        self._next_idx += 1
        self.lsh.insert(key, m)
        return False
