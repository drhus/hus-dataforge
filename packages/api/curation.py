"""User-curation overlay — bulk actions taken in the records browser
persist here and survive re-cleaning.

curation.jsonl lives at `data/<slug>/curation.jsonl`. Each line is one
action keyed by record id:

  {"id": <hash>, "action": "discard", "by": "...", "at": "<iso>"}
  {"id": <hash>, "action": "undo_discard", ...}
  {"id": <hash>, "action": "set_category", "category": "poetry", ...}
  {"id": <hash>, "action": "set_subject", "subject": "...", ...}

The pipeline applies this overlay AFTER normalize + dedup. Re-running
clean re-applies the overlay deterministically."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from packages.api.settings import DATA_DIR

VALID_ACTIONS = {"discard", "undo_discard", "set_category", "set_subject"}


def _path(slug: str) -> Path:
    return DATA_DIR / slug / "curation.jsonl"


def append_actions(slug: str, actions: list[dict]) -> int:
    p = _path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).isoformat()
    n = 0
    with p.open("a", encoding="utf-8") as fh:
        for a in actions:
            if not isinstance(a, dict):
                continue
            if a.get("action") not in VALID_ACTIONS:
                continue
            if not a.get("id"):
                continue
            a = {**a, "at": a.get("at") or now}
            fh.write(json.dumps(a, ensure_ascii=False) + "\n")
            n += 1
    return n


def load_overlay(slug: str) -> dict[str, dict]:
    """Collapse all actions to a per-record final state.

    Returns {record_id: {"discarded": bool, "category": str|None, "subject": str|None}}.
    Later actions override earlier ones (last-write-wins per record)."""
    p = _path(slug)
    state: dict[str, dict] = {}
    if not p.exists():
        return state
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                a = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = a.get("id")
            if not rid:
                continue
            cur = state.setdefault(rid, {})
            act = a.get("action")
            if act == "discard":
                cur["discarded"] = True
            elif act == "undo_discard":
                cur["discarded"] = False
            elif act == "set_category":
                cur["category"] = a.get("category")
            elif act == "set_subject":
                cur["subject"] = a.get("subject")
    return state


def list_actions(slug: str, *, limit: int = 200) -> list[dict]:
    p = _path(slug)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    out: list[dict] = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


__all__ = ["append_actions", "load_overlay", "list_actions", "VALID_ACTIONS"]
