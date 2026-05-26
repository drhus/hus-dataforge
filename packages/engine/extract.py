"""HTML extraction using selectolax (lexbor backend — very fast)."""
from __future__ import annotations

from selectolax.lexbor import LexborHTMLParser, LexborNode

from packages.engine.spec import FieldSpec


def parse(html: str) -> LexborHTMLParser:
    return LexborHTMLParser(html)


def _node_value(node: LexborNode, attr: str) -> str | None:
    if attr == "text":
        # Use \n as separator so <br> and block-level tags preserve line breaks —
        # critical for poetry, where each verse is on its own line. For single-line
        # h2/h3 elements this is a no-op.
        return node.text(separator="\n", strip=True) or None
    if attr == "html":
        return node.html
    return node.attributes.get(attr)


def _extract_field(root: LexborNode, spec: FieldSpec) -> str | None:
    if spec.multi:
        values = [_node_value(n, spec.attr) for n in root.css(spec.selector)]
        kept = [v for v in values if v]
        return spec.join_with.join(kept) if kept else None
    node = root.css_first(spec.selector)
    if node is None:
        return None
    return _node_value(node, spec.attr)


def extract_records(html: str, record_selector: str, fields: dict[str, FieldSpec]) -> list[dict]:
    tree = parse(html)
    out: list[dict] = []
    for node in tree.css(record_selector):
        record: dict[str, str | None] = {f: _extract_field(node, spec) for f, spec in fields.items()}
        if any(v for v in record.values()):
            out.append(record)
    return out


def extract_links(html: str, selector: str, attr: str = "href") -> list[str]:
    tree = parse(html)
    out: list[str] = []
    seen: set[str] = set()
    for node in tree.css(selector):
        val = node.attributes.get(attr)
        if val and val not in seen:
            seen.add(val)
            out.append(val)
    return out
