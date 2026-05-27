"""Per-subject book exporters — EPUB + Markdown + CSV, optionally zipped.

Each builder reads data/<slug>/clean/<subject>.jsonl and the matching
projects/<slug>/{subjects,poets}/<subject>.yaml manifest, then emits a
self-contained file under data/<slug>/export/:

  - build_epub     → <subject>.epub  (RTL Arabic e-book, ebooklib)
  - build_markdown → <subject>.md    (GitHub-flavored, two-space line
                                       breaks for verses)
  - build_csv      → <subject>.csv   (flat tabular dump for spreadsheets,
                                       UTF-8, all-field-quoted, RFC-4180)
  - build_bundle   → <subject>.zip   (all three together + README.txt)

All builders share sort order (titled first alphabetically, then untitled
by date) and the same metadata chips.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml
from ebooklib import epub

from packages.api.settings import DATA_DIR, PROJECTS_DIR

log = logging.getLogger(__name__)


_RTL_CSS = """
@charset "utf-8";
html { direction: rtl; }
body {
  direction: rtl;
  text-align: right;
  font-family: "Amiri", "Noto Naskh Arabic", "Scheherazade New", "Traditional Arabic", serif;
  line-height: 1.9;
  font-size: 1.05em;
  margin: 1em;
}
h1, h2, h3 { text-align: center; font-weight: normal; }
h1 { font-size: 2em; margin: 2em 0 1em; }
h2 { font-size: 1.4em; margin: 1.5em 0 0.75em; color: #2c2c2c; }
h3 { font-size: 1.1em; color: #555; }
.poem-meta {
  text-align: center;
  font-size: 0.85em;
  color: #888;
  margin-bottom: 1em;
}
.verses {
  white-space: pre-wrap;
  text-align: center;
  font-size: 1.1em;
  margin: 1em 0;
}
.cover {
  text-align: center;
  padding: 4em 1em;
}
.cover .title { font-size: 2.5em; margin-bottom: 0.5em; }
.cover .subtitle { font-size: 1.2em; color: #555; }
.cover .footer { margin-top: 4em; font-size: 0.9em; color: #888; }
.toc-section { margin-top: 2em; }
hr { border: none; border-top: 1px solid #ccc; margin: 2em 0; }
"""


_HTML_ESCAPE_RE = re.compile(r"[&<>\"']")
_ESC_MAP = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def _esc(s: str) -> str:
    return _HTML_ESCAPE_RE.sub(lambda m: _ESC_MAP[m.group(0)], s or "")


def _load_manifest(project_slug: str, subject_slug: str) -> dict:
    for dirname in ("subjects", "poets"):
        p = PROJECTS_DIR / project_slug / dirname / f"{subject_slug}.yaml"
        if p.exists():
            try:
                return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception as e:
                log.warning("manifest read failed for %s/%s: %s", project_slug, subject_slug, e)
    return {}


def _read_clean(project_slug: str, subject_slug: str) -> list[dict]:
    p = DATA_DIR / project_slug / "clean" / f"{subject_slug}.jsonl"
    if not p.exists():
        raise FileNotFoundError(
            f"no clean JSONL for {subject_slug!r} in {project_slug!r} "
            f"— run the clean stage first"
        )
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _author_display(manifest: dict, subject_slug: str) -> tuple[str, str]:
    """Return (display_name, secondary). Prefers Arabic for display."""
    ar = (manifest.get("name_ar") or "").strip()
    en = (manifest.get("name_en") or "").strip()
    if ar and en:
        return ar, en
    if ar:
        return ar, subject_slug
    if en:
        return en, subject_slug
    return subject_slug, ""


def _sort_records(records: list[dict]) -> list[dict]:
    """Titled poems first (alphabetically by title), then untitled (by published
    date if present, else stable order)."""
    def key(r: dict):
        title = (r.get("title") or "").strip()
        meta = r.get("meta") or {}
        date = meta.get("date") or meta.get("published_at") or ""
        # bucket 0 = titled, 1 = untitled-with-date, 2 = untitled-no-date
        if title:
            return (0, title, "")
        if date:
            return (1, date, "")
        return (2, "", r.get("id") or "")

    return sorted(records, key=key)


def build_epub(
    project_slug: str,
    subject_slug: str,
    *,
    out_path: Path | None = None,
) -> Path:
    """Build an EPUB file for a single subject. Returns the output path."""
    manifest = _load_manifest(project_slug, subject_slug)
    records = _read_clean(project_slug, subject_slug)
    if not records:
        raise RuntimeError(
            f"no records found in clean/{subject_slug}.jsonl — nothing to export"
        )

    display_name, secondary = _author_display(manifest, subject_slug)
    creator = secondary or display_name
    country = (manifest.get("country") or "").strip()
    born = manifest.get("born") or ""
    died = manifest.get("died") or ""

    title = f"ديوان {display_name}"
    if secondary:
        title = f"{title} — {secondary}"

    book = epub.EpubBook()
    book.set_identifier(f"urn:dataforge:{project_slug}:{subject_slug}:{uuid4()}")
    book.set_title(title)
    book.set_language("ar")
    book.add_author(display_name)
    if secondary and secondary != display_name:
        book.add_author(secondary)
    book.add_metadata(
        "DC", "description",
        f"A collection of {len(records)} poems / texts attributed to "
        f"{display_name}, compiled by hus-dataforge from multiple sources."
    )
    book.add_metadata("DC", "publisher", "hus-dataforge")
    book.add_metadata(
        "DC", "date", datetime.now(tz=timezone.utc).date().isoformat()
    )
    if country:
        book.add_metadata("DC", "coverage", country)

    # CSS resource
    css = epub.EpubItem(
        uid="style", file_name="style/main.css", media_type="text/css",
        content=_RTL_CSS.encode("utf-8"),
    )
    book.add_item(css)

    # Cover page
    born_died = ""
    if born and died:
        born_died = f"{born}–{died}"
    elif born:
        born_died = f"مواليد {born}"
    cover_body = f"""<div class="cover">
  <div class="title">{_esc(display_name)}</div>
  {f'<div class="subtitle">{_esc(secondary)}</div>' if secondary and secondary != display_name else ''}
  {f'<div class="subtitle">{_esc(country)} · {_esc(str(born_died))}</div>' if country or born_died else ''}
  <div class="footer">
    {len(records)} نص شعري<br/>
    تم التجميع بواسطة hus-dataforge<br/>
    {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')}
  </div>
</div>"""
    cover = epub.EpubHtml(
        title="Cover", file_name="cover.xhtml", lang="ar", content=cover_body,
    )
    cover.add_item(css)
    book.add_item(cover)

    # Chapters
    chapters: list[epub.EpubHtml] = []
    for i, r in enumerate(_sort_records(records), start=1):
        ch_title = (r.get("title") or "").strip() or f"قصيدة #{i}"
        text = (r.get("text") or "").strip()
        meta = r.get("meta") or {}
        meta_bits: list[str] = []
        if meta.get("date"):
            meta_bits.append(str(meta["date"]))
        if meta.get("topics"):
            top = str(meta["topics"]).split("|")[0].strip()
            if top:
                meta_bits.append(top)
        if r.get("category") and r.get("category") != "poetry":
            meta_bits.append(str(r["category"]))
        meta_html = ""
        if meta_bits:
            meta_html = f'<div class="poem-meta">{_esc(" · ".join(meta_bits))}</div>'

        body = (
            f"<h2>{_esc(ch_title)}</h2>"
            f"{meta_html}"
            f'<div class="verses">{_esc(text)}</div>'
        )
        ch = epub.EpubHtml(
            title=ch_title, file_name=f"poem-{i:04d}.xhtml", lang="ar", content=body,
        )
        ch.add_item(css)
        book.add_item(ch)
        chapters.append(ch)

    # Spine + TOC
    book.spine = ["nav", cover, *chapters]
    book.toc = [
        epub.Link("cover.xhtml", "الغلاف", "cover"),
        (epub.Section("القصائد"), tuple(chapters)),
    ]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    out_dir = DATA_DIR / project_slug / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_path or (out_dir / f"{subject_slug}.epub")
    epub.write_epub(str(out_path), book, {})
    log.info("epub: wrote %d chapters to %s", len(chapters), out_path)
    return out_path


def build_markdown(
    project_slug: str,
    subject_slug: str,
    *,
    out_path: Path | None = None,
) -> Path:
    """Build a single .md file for a subject. Verses use two-trailing-space
    line breaks so any markdown renderer keeps the poem layout intact.

    Output: data/<slug>/export/<subject>.md
    """
    manifest = _load_manifest(project_slug, subject_slug)
    records = _read_clean(project_slug, subject_slug)
    if not records:
        raise RuntimeError(
            f"no records found in clean/{subject_slug}.jsonl — nothing to export"
        )

    display_name, secondary = _author_display(manifest, subject_slug)
    country = (manifest.get("country") or "").strip()
    born = manifest.get("born") or ""
    died = manifest.get("died") or ""
    born_died = ""
    if born and died:
        born_died = f"{born}–{died}"
    elif born:
        born_died = f"b. {born}"

    today = datetime.now(tz=timezone.utc).date().isoformat()
    lines: list[str] = []
    lines.append(f"# {display_name}")
    if secondary and secondary != display_name:
        lines.append(f"*{secondary}*")
    facts = " · ".join(p for p in [country, born_died] if p)
    if facts:
        lines.append(facts)
    lines.append("")
    lines.append(
        f"> {len(records)} نص شعري · جُمعت بواسطة hus-dataforge · {today}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    sorted_records = _sort_records(records)
    # Table of contents — only for titled poems (untitled would just be a sea
    # of "قصيدة #N" links and add noise).
    titled = [
        (i, r) for i, r in enumerate(sorted_records, start=1) if (r.get("title") or "").strip()
    ]
    if titled:
        lines.append("## فهرس")
        lines.append("")
        for i, r in titled:
            anchor = _md_anchor(r.get("title") or "", i)
            lines.append(f"- [{r.get('title')}](#{anchor})")
        lines.append("")
        lines.append("---")
        lines.append("")

    for i, r in enumerate(sorted_records, start=1):
        ch_title = (r.get("title") or "").strip() or f"قصيدة #{i}"
        text = (r.get("text") or "").strip()
        meta = r.get("meta") or {}
        meta_bits: list[str] = []
        if meta.get("date"):
            meta_bits.append(str(meta["date"]))
        if meta.get("topics"):
            top = str(meta["topics"]).split("|")[0].strip()
            if top:
                meta_bits.append(top)
        if r.get("category") and r.get("category") != "poetry":
            meta_bits.append(str(r["category"]))

        lines.append(f"## {ch_title}")
        if meta_bits:
            lines.append(f"*{' · '.join(meta_bits)}*")
        lines.append("")
        # Each verse becomes its own line; two trailing spaces = <br> in
        # GitHub-flavored markdown so the poem keeps its shape.
        for ln in text.splitlines():
            if ln.strip():
                lines.append(ln + "  ")
            else:
                lines.append("")
        # Source URL footnote
        if r.get("source_url"):
            lines.append("")
            lines.append(f"<sup>المصدر: <{r['source_url']}></sup>")
        lines.append("")
        lines.append("---")
        lines.append("")

    out_dir = DATA_DIR / project_slug / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_path or (out_dir / f"{subject_slug}.md")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("md: wrote %d records to %s", len(records), out_path)
    return out_path


def _md_anchor(title: str, idx: int) -> str:
    """GitHub-style header anchor: lowercased, hyphenated, non-word stripped.
    Falls back to a stable index-based anchor if the title is empty."""
    if not title:
        return f"poem-{idx}"
    a = title.strip().lower()
    a = re.sub(r"[^\w؀-ۿݐ-ݿ-]+", "-", a, flags=re.UNICODE)
    a = a.strip("-")
    return a or f"poem-{idx}"


_CSV_COLUMNS = [
    "id",
    "title",
    "text",
    "date",
    "topics",
    "meter",
    "rhyme",
    "category",
    "source",
    "source_url",
    "sources",
    "source_urls",
    "word_count",
    "line_count",
    "lang",
    "scraped_at",
    "run_id",
]


def build_csv(
    project_slug: str,
    subject_slug: str,
    *,
    out_path: Path | None = None,
) -> Path:
    """Build a flat CSV dump of a subject's clean records. UTF-8, RFC-4180
    quoting, one row per poem. `sources` / `source_urls` arrays are
    pipe-joined for spreadsheet friendliness; `meta.date / topics / meter /
    rhyme` are lifted out as top-level columns.

    Output: data/<slug>/export/<subject>.csv
    """
    records = _read_clean(project_slug, subject_slug)
    if not records:
        raise RuntimeError(
            f"no records found in clean/{subject_slug}.jsonl — nothing to export"
        )

    out_dir = DATA_DIR / project_slug / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_path or (out_dir / f"{subject_slug}.csv")

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=_CSV_COLUMNS,
            extrasaction="ignore",
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        for r in _sort_records(records):
            meta = r.get("meta") or {}
            row = {
                "id": r.get("id"),
                "title": r.get("title") or "",
                "text": r.get("text") or "",
                "date": meta.get("date") or meta.get("published_at") or "",
                "topics": meta.get("topics") or "",
                "meter": meta.get("meter") or "",
                "rhyme": meta.get("rhyme") or "",
                "category": r.get("category") or "",
                "source": r.get("source") or "",
                "source_url": r.get("source_url") or "",
                "sources": "|".join(r.get("sources") or []) if r.get("sources") else "",
                "source_urls": "|".join(r.get("source_urls") or []) if r.get("source_urls") else "",
                "word_count": r.get("word_count") or "",
                "line_count": r.get("line_count") or "",
                "lang": r.get("lang") or "",
                "scraped_at": r.get("scraped_at") or "",
                "run_id": r.get("run_id") or r.get("_run_id") or "",
            }
            writer.writerow(row)
    log.info("csv: wrote %d rows to %s", len(records), out_path)
    return out_path


def build_bundle(
    project_slug: str,
    subject_slug: str,
    *,
    out_path: Path | None = None,
) -> Path:
    """Build .epub + .md + .csv and zip them into <subject>.zip.

    Output: data/<slug>/export/<subject>.zip
    """
    epub_path = build_epub(project_slug, subject_slug)
    md_path = build_markdown(project_slug, subject_slug)
    csv_path = build_csv(project_slug, subject_slug)

    out_dir = DATA_DIR / project_slug / "export"
    out_path = out_path or (out_dir / f"{subject_slug}.zip")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(epub_path, arcname=epub_path.name)
        zf.write(md_path, arcname=md_path.name)
        zf.write(csv_path, arcname=csv_path.name)
        # Tiny README so the recipient knows what they got
        zf.writestr(
            "README.txt",
            (
                f"{subject_slug} — hus-dataforge bundle\n"
                f"{'-' * 60}\n"
                f"{epub_path.name}\n"
                f"  Arabic EPUB, RTL, lang=ar. Open in Apple Books, Kindle\n"
                f"  (Send-to-Kindle), KOReader, Google Play Books, calibre.\n\n"
                f"{md_path.name}\n"
                f"  GitHub-flavored markdown with two-trailing-space line\n"
                f"  breaks so verses keep their shape. Renders correctly on\n"
                f"  GitHub, Obsidian, pandoc, mdBook.\n\n"
                f"{csv_path.name}\n"
                f"  Flat tabular dump (UTF-8, RFC-4180 quoted) — one row\n"
                f"  per poem. Open in Excel / Numbers / Google Sheets /\n"
                f"  Pandas. Pipe-joined sources/source_urls; meta.date,\n"
                f"  topics, meter, rhyme lifted into top-level columns.\n\n"
                f"Generated by hus-dataforge on "
                f"{datetime.now(tz=timezone.utc).date().isoformat()}.\n"
            ),
        )
    out_path.write_bytes(buf.getvalue())
    log.info(
        "bundle: wrote %s (%d bytes)", out_path, out_path.stat().st_size
    )
    return out_path


__all__ = ["build_epub", "build_markdown", "build_csv", "build_bundle"]
