"""Generate text via Claude with retrieved corpus samples as few-shot context.

Uses the local Claude Code OAuth session (Pro/Max subscription) — zero API
credit spend. The SDK call is delegated to tools/claude-sdk/call.mjs via
subprocess, which mirrors the pattern in hus-poemaster/lib/arena/llm.ts.

Public API:
    generate_zajal(prompt, project, *, top_k=8, where=None, system=None,
                   temperature=None, model=None, retrieve=True) -> dict
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from packages.rag.retrieve import search

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CALLER_SCRIPT = REPO_ROOT / "tools" / "claude-sdk" / "call.mjs"

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_SYSTEM = """\
أنت شاعر زجل لبناني/سوري/فلسطيني محترف.
- اكتب باللهجة المحكية كما في الأمثلة المرفقة، لا بالفصحى.
- التزم بالقافية والوزن المطلوبين.
- اكتب فقط النص الشعري — لا مقدمة، لا شرح، لا تعليق على الأسلوب.
- إذا طُلب شكلٌ محدد (معنّى، قرّادي، شروقي، عتابا، ميجانا) اتبع بنيته.
"""


def _format_examples(hits: list[dict]) -> str:
    """Build the few-shot block from retrieved records."""
    blocks: list[str] = []
    for i, h in enumerate(hits, 1):
        bucket = h.get("bucket") or "?"
        title = (h.get("title") or "").strip()
        text = (h.get("text") or "").strip()
        # Trim very long transcript samples — keep the head as a stylistic anchor.
        if len(text) > 1200:
            text = text[:1200].rstrip() + " …"
        header = f"[مثال {i} — {bucket}{' · ' + title if title else ''}]"
        blocks.append(f"{header}\n{text}")
    return "\n\n".join(blocks)


def _build_prompt(user_prompt: str, hits: list[dict]) -> str:
    if not hits:
        return user_prompt.strip()
    examples = _format_examples(hits)
    return (
        "فيما يلي مقتطفات من زجل شعراء معروفين كأمثلة على الأسلوب المطلوب:\n\n"
        f"{examples}\n\n"
        "---\n\n"
        f"الطلب:\n{user_prompt.strip()}\n\n"
        "النص الشعري:"
    )


def _call_claude(prompt: str, system: str, model: str) -> str:
    """Spawn the Node bridge with a clean env (no ANTHROPIC_API_KEY)."""
    if not CALLER_SCRIPT.exists():
        raise FileNotFoundError(f"claude-sdk caller not built at {CALLER_SCRIPT}")
    env = dict(os.environ)
    # Per memory feedback_claude_sdk_arena: clear ANTHROPIC_API_KEY so the SDK
    # uses the OAuth session, not a paid API token.
    env.pop("ANTHROPIC_API_KEY", None)
    payload = json.dumps({"prompt": prompt, "system": system, "model": model})
    proc = subprocess.run(
        ["node", str(CALLER_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    if proc.returncode != 0:
        err = proc.stderr.strip() or "non-zero exit, no stderr"
        raise RuntimeError(f"claude SDK call failed (exit {proc.returncode}): {err[:400]}")
    return proc.stdout


def generate_zajal(
    prompt: str,
    project: str,
    *,
    top_k: int = 8,
    where: str | None = None,
    system: str | None = None,
    model: str | None = None,
    retrieve: bool = True,
) -> dict[str, Any]:
    """Generate zajal text guided by retrieved corpus samples."""
    hits: list[dict] = []
    if retrieve:
        try:
            hits = search(prompt, project, top_k=top_k, where=where)
        except FileNotFoundError as e:
            log.warning("rag.generate: %s — falling back to zero-shot", e)
    final_prompt = _build_prompt(prompt, hits)
    sys = (system or DEFAULT_SYSTEM).strip()
    model_name = model or DEFAULT_MODEL
    out = _call_claude(final_prompt, sys, model_name)
    return {
        "project": project,
        "model": model_name,
        "retrieve": bool(retrieve and hits),
        "retrieved_count": len(hits),
        "retrieved": [
            {"bucket": h.get("bucket"), "title": h.get("title"), "score": h.get("_score")}
            for h in hits
        ],
        "prompt": prompt,
        "where": where,
        "output": out.strip(),
    }


__all__ = ["generate_zajal"]
