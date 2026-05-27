"""Two-stage dedup: exact-hash + MinHash near-dup on a normalized signature.

`Deduper` is stateful per scope (typically one poet). Call `check()` in
stream order; the first occurrence is kept, later duplicates return the
key of the survivor so the caller can attribute provenance back to it."""
from __future__ import annotations

import re

from datasketch import MinHash, MinHashLSH

# Tashkeel + tatweel + non-Arabic word chars — strip for the dedup signature
# while keeping the original text intact in the canonical record.
_DIACRITICS = re.compile(r"[ً-ٰٟـ]")
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
    """Per-scope dedup. Threshold 0.85 = drop only true near-dups.

    The internal key for each kept record is whatever the caller passes to
    `check()` (typically the record's `id`). When a duplicate comes in,
    `check()` returns the key of the EXISTING survivor — the pipeline uses
    this to merge provenance (sources, source_urls) into the survivor.
    """

    def __init__(self, threshold: float = 0.85, num_perm: int = 128):
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._exact_ids: set[str] = set()
        self._minhash_key_to_id: dict[str, str] = {}  # LSH key -> caller id
        self._next_idx = 0

    def _minhash(self, text: str) -> MinHash | None:
        sh = _shingles(text)
        if not sh:
            return None
        m = MinHash(num_perm=self.num_perm)
        for s in sh:
            m.update(s.encode("utf-8"))
        return m

    def check(self, record: dict) -> str | None:
        """Inspect record. If it's a duplicate, return the existing survivor's
        id. If it's new, register it and return None."""
        rid = record.get("id")
        # exact-hash gate first — exact id collision means same content
        if rid and rid in self._exact_ids:
            return rid
        if rid:
            self._exact_ids.add(rid)

        # near-dup via MinHash
        m = self._minhash(record.get("text") or "")
        if m is None:
            return None
        hits = self.lsh.query(m)
        if hits:
            # return the survivor's caller-id (first match)
            survivor_key = hits[0]
            return self._minhash_key_to_id.get(survivor_key, survivor_key)

        # New record — register it
        key = f"r{self._next_idx}"
        self._next_idx += 1
        self.lsh.insert(key, m)
        if rid:
            self._minhash_key_to_id[key] = rid
        return None

    # Backwards-compat shim — callers using is_dup() just see a bool.
    def is_dup(self, record: dict) -> bool:
        return self.check(record) is not None
