"""End-to-end engine tests using the fixture spider."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def fresh_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATAFORGE_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATAFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATAFORGE_DB_PATH", str(tmp_path / "data" / "test.db"))

    for mod in list(sys.modules):
        if mod.startswith("packages."):
            del sys.modules[mod]

    yield tmp_path


def _write_fixture_project(env_root: Path, fixture_html: str) -> None:
    from packages.api import projects_store

    fixture_path = env_root / "fixture.html"
    fixture_path.write_text(fixture_html, encoding="utf-8")

    config = {
        "template": "poetry",
        "sources": [
            {
                "name": "test-fixture",
                "type": "fixture",
                "fixture_path": str(fixture_path),
                "record_selector": "article.poem",
                "fields": {
                    "title": {"selector": ".title", "attr": "text"},
                    "author": {"selector": ".author", "attr": "text"},
                    "text": {"selector": ".body", "attr": "text"},
                },
            }
        ],
    }
    projects_store.create_project("test-poems", config)


SAMPLE_HTML = (Path(__file__).parent / "fixtures" / "poems.html").read_text(encoding="utf-8")


def test_engine_extracts_fixture_records(fresh_env):
    _write_fixture_project(fresh_env, SAMPLE_HTML)

    from packages.engine import run_scrape

    result = run_scrape("test-poems")
    assert result["total_records"] == 3
    assert result["records_by_source"]["test-fixture"] == 3

    out = fresh_env / "data" / "test-poems" / "raw" / "test-fixture.jsonl"
    assert out.exists()
    lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert {r["author"] for r in lines} == {"امرؤ القيس", "كعب بن زهير", "عنترة بن شداد"}
    # raw HTML stored
    raw_index = fresh_env / "data" / "test-poems" / "raw" / "_index.jsonl"
    assert raw_index.exists()


def test_spec_rejects_invalid_source(fresh_env):
    from packages.api import projects_store
    from packages.engine import run_scrape

    projects_store.create_project(
        "broken",
        {
            "sources": [
                {"name": "bad", "type": "paginated", "record_selector": "div", "fields": {"x": "p"}}
            ]
        },
    )
    with pytest.raises(ValueError, match="paginated needs url_template"):
        run_scrape("broken")


def test_progress_is_called(fresh_env):
    _write_fixture_project(fresh_env, SAMPLE_HTML)

    from packages.engine import run_scrape
    from packages.engine.progress import NullProgress

    calls = []

    class Recording(NullProgress):
        def start(self, source):
            calls.append(("start", source))

        def page(self, url, n):
            calls.append(("page", url, n))

        def finish(self):
            calls.append(("finish",))

    run_scrape("test-poems", progress=Recording())
    kinds = [c[0] for c in calls]
    assert kinds == ["start", "page", "finish"]
