from __future__ import annotations

from pathlib import Path

from packages.api.settings import PROJECTS_DIR
from packages.engine.extract import extract_records
from packages.engine.progress import Progress
from packages.engine.spec import SourceSpec
from packages.engine.storage import RecordWriter, write_raw


class FixtureSpider:
    """Reads HTML from a local file under the project dir or repo root.
    Useful for tests and offline development against captured snapshots."""

    def run(self, slug: str, source: SourceSpec, progress: Progress) -> int:
        assert source.fixture_path, "fixture spider needs fixture_path"
        p = Path(source.fixture_path)
        if not p.is_absolute():
            # try project dir first, then repo root
            candidates = [PROJECTS_DIR / slug / source.fixture_path, p]
            for c in candidates:
                if c.exists():
                    p = c
                    break
        if not p.exists():
            raise FileNotFoundError(f"fixture not found: {source.fixture_path}")

        html = p.read_text(encoding="utf-8")
        write_raw(slug, html, f"fixture://{source.fixture_path}")
        records = extract_records(html, source.record_selector, source.fields)
        with RecordWriter(slug, source.name) as writer:
            for r in records:
                r["_source_url"] = f"fixture://{source.fixture_path}"
                writer.write(r)
            progress.page(f"fixture://{source.fixture_path}", len(records))
            return writer.count
