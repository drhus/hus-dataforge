"""Two-stage dedup: exact-hash + MinHash near-dup on a normalized signature.

`Deduper` is stateful per scope (typically one poet). Call `check()` in
stream order; the first occurrence is kept, later duplicates return the
key of the survivor so the caller can attribute provenance back to it.

A separate post-pass — `find_fragments()` — sweeps the surviving records
to catch the asymmetric case MinHashLSH misses: when one record's text is
mostly *contained* in a larger record's text (Jaccard goes near zero, but
the fragment's coverage of the bigger set stays high). This is the
"Telegram excerpt of a longer aldiwan poem" case."""
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


def find_fragments(
    records: list[dict],
    *,
    containment_threshold: float = 0.75,
    min_length_ratio: float = 0.6,
    k: int = 5,
) -> list[tuple[int, int]]:
    """Detect records whose text is mostly contained in another, longer
    record's text — the asymmetric case MinHashLSH at threshold 0.85 misses.

    Returns a list of (fragment_idx, survivor_idx) pairs. The fragment is
    the smaller record; the survivor is the longer canonical version.

    Algorithm (O(n*m), where m = larger surviving records — fine for
    bucket sizes in the low thousands per poet):

    1. Process records longest-first so the canonical full version is
       always seen before any of its fragments.
    2. For each candidate, compute its shingle set.
    3. For each already-kept (larger) record, compute |A ∩ B| / |A| (the
       coverage of the candidate by the kept record).
    4. If coverage ≥ containment_threshold AND the candidate is meaningfully
       smaller (len ratio < min_length_ratio), mark it as a fragment of B.
    """
    # Pre-compute (idx, shingle-set, len) sorted by length desc
    indexed: list[tuple[int, set[str], int]] = []
    for idx, r in enumerate(records):
        text = r.get("text") or ""
        sh = set(_shingles(text, k=k))
        indexed.append((idx, sh, len(text)))
    indexed.sort(key=lambda t: t[2], reverse=True)

    kept: list[tuple[int, set[str], int]] = []
    pairs: list[tuple[int, int]] = []
    for idx, sh, length in indexed:
        if not sh:
            kept.append((idx, sh, length))
            continue
        # Compare against each already-kept (larger) record
        best_survivor: int | None = None
        best_coverage = 0.0
        for s_idx, s_sh, s_len in kept:
            if length >= s_len * min_length_ratio:
                # Too close in size — leave to normal MinHashLSH (or both keep)
                continue
            if not s_sh:
                continue
            # Quick reject: at most |sh| can overlap; need coverage >= thr
            inter = len(sh & s_sh)
            coverage = inter / len(sh)
            if coverage > best_coverage:
                best_coverage = coverage
                best_survivor = s_idx
                if coverage >= 0.99:
                    break  # near-perfect containment, stop searching
        if best_coverage >= containment_threshold and best_survivor is not None:
            pairs.append((idx, best_survivor))
        else:
            # Not a fragment — keep as a potential parent for smaller records
            kept.append((idx, sh, length))
    return pairs


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
