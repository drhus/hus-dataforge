"""M4 export tests — small Parquet roundtrip + dataset card generation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATAFORGE_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATAFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATAFORGE_DB_PATH", str(tmp_path / "data" / "test.db"))
    for mod in list(sys.modules):
        if mod.startswith("packages."):
            del sys.modules[mod]
    yield tmp_path


def _write_clean(slug: str, poet: str, records: list[dict], data_root: Path) -> None:
    p = data_root / slug / "clean" / f"{poet}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_export_writes_parquet_and_card(env: Path):
    from packages.api import projects_store
    from packages.export import run_export

    projects_store.create_project("test", {"sources": []})
    data_root = env / "data"
    _write_clean(
        "test",
        "poet-a",
        [
            {"id": "h1", "poet": "poet-a", "title": "T1", "text": "نص ١", "lang": "ar", "source": "s1", "source_kind": "aldiwan", "source_url": "u1", "word_count": 2, "line_count": 1, "meta": {"x": 1}},
            {"id": "h2", "poet": "poet-a", "title": "T2", "text": "نص ٢", "lang": "ar", "source": "s1", "source_kind": "aldiwan", "source_url": "u2", "word_count": 2, "line_count": 1, "meta": {}},
        ],
        data_root,
    )
    _write_clean(
        "test",
        "poet-b",
        [
            {"id": "h3", "poet": "poet-b", "title": None, "text": "tg msg", "lang": "ar", "source": "tg", "source_kind": "telegram", "source_url": "u3", "word_count": 2, "line_count": 1, "meta": {"post_id": 42}},
        ],
        data_root,
    )

    result = run_export("test")
    assert result["total_rows"] == 3
    assert result["by_poet"]["poet-a"]["rows"] == 2
    assert result["by_poet"]["poet-b"]["rows"] == 1

    export_dir = data_root / "test" / "export"
    assert (export_dir / "poet-a.parquet").exists()
    assert (export_dir / "poet-b.parquet").exists()
    readme = (export_dir / "README.md").read_text(encoding="utf-8")
    assert "license: cc-by-4.0" in readme
    assert "poet-a" in readme
    assert "## Schema" in readme
    stats = json.loads((export_dir / "_stats.json").read_text(encoding="utf-8"))
    assert stats["total_rows"] == 3


def test_export_sidecar_split_separate_from_primary(env: Path):
    """Sidecar (e.g. <poet>__commentary.jsonl) exports to its own parquet
    and does not bleed into primary corpus stats or the subjects table."""
    from packages.api import projects_store
    from packages.export import run_export

    projects_store.create_project("side", {"sources": []})
    data_root = env / "data"
    _write_clean(
        "side",
        "poet-a",
        [
            {"id": "h1", "poet": "poet-a", "text": "primary poem", "word_count": 2, "line_count": 1},
        ],
        data_root,
    )
    _write_clean(
        "side",
        "poet-a__commentary",
        [
            {"id": "c1", "poet": "poet-a", "text": "commentary about a poem", "word_count": 4, "line_count": 1},
        ],
        data_root,
    )
    result = run_export("side")
    assert result["total_rows"] == 1, "sidecar must not count toward primary"
    assert result["sidecar_rows"] == 1
    assert "poet-a__commentary" in result["by_sidecar"]
    export_dir = data_root / "side" / "export"
    assert (export_dir / "poet-a.parquet").exists()
    assert (export_dir / "poet-a__commentary.parquet").exists()
    readme = (export_dir / "README.md").read_text(encoding="utf-8")
    assert "Sidecar splits" in readme
    assert "poet-a__commentary.parquet" in readme


def test_export_extras_collects_topics_meters_provenance(env: Path):
    """The dataset card extras pull topics/meters from meta and detect
    multi-source records via the sources list."""
    from packages.api import projects_store
    from packages.export import run_export

    projects_store.create_project("ex", {"sources": []})
    _write_clean(
        "ex",
        "poet-a",
        [
            {
                "id": "h1",
                "poet": "poet-a",
                "text": "x",
                "word_count": 5,
                "line_count": 1,
                "source": "src-1",
                "sources": ["src-1", "src-2"],
                "meta": {"topics": "love|sadness", "meter": "بحر البسيط"},
            },
            {
                "id": "h2",
                "poet": "poet-a",
                "text": "y",
                "word_count": 10,
                "line_count": 1,
                "source": "src-1",
                "sources": ["src-1"],
                "meta": {"topics": "love"},
            },
        ],
        env / "data",
    )
    result = run_export("ex")
    extras = result["extras"]
    topics = dict(extras["topics"])
    assert topics["love"] == 2
    assert topics["sadness"] == 1
    assert dict(extras["meters"])["بحر البسيط"] == 1
    assert extras["multi_source_records"] == 1
    sources = dict(extras["sources"])
    assert sources["src-1"] == 2
    assert sources["src-2"] == 1
    # Percentiles
    assert extras["len_p50"] in (5, 10)  # tiny sample, just sanity
    assert extras["total_words"] == 15


def test_parquet_roundtrip(env: Path):
    import pyarrow.parquet as pq

    from packages.api import projects_store
    from packages.export import run_export

    projects_store.create_project("rt", {"sources": []})
    _write_clean(
        "rt",
        "p",
        [{"id": "x", "poet": "p", "text": "محتوى", "meta": {"k": "v"}, "word_count": 1}],
        env / "data",
    )
    run_export("rt")
    tbl = pq.read_table(env / "data" / "rt" / "export" / "p.parquet")
    assert tbl.num_rows == 1
    cols = set(tbl.column_names)
    assert "text" in cols and "meta_json" in cols
    row = tbl.to_pylist()[0]
    assert row["text"] == "محتوى"
    assert json.loads(row["meta_json"]) == {"k": "v"}


def test_epub_build_round_trip(env: Path):
    """Build an EPUB from clean records — verify it's a valid zip with the
    right structure, embedded language, and Arabic content."""
    import zipfile
    from packages.api import projects_store
    from packages.epub import build_epub

    projects_store.create_project("ep", {"sources": []})
    # Drop a manifest (subjects/ dir)
    sdir = env / "projects" / "ep" / "subjects"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "poet-a.yaml").write_text(
        "name_ar: حذيفة\nname_en: Hudhayfah\ncountry: Syria\nborn: 1988\n",
        encoding="utf-8",
    )

    _write_clean(
        "ep",
        "poet-a",
        [
            {"id": "h1", "poet": "poet-a", "title": "قصيدة الأولى",
             "text": "بيت من شعر\nوبيت ثاني", "word_count": 4, "line_count": 2},
            {"id": "h2", "poet": "poet-a", "title": None,
             "text": "بيت من شعر بدون عنوان", "word_count": 4, "line_count": 1,
             "meta": {"date": "2026-05-01"}},
        ],
        env / "data",
    )

    out = build_epub("ep", "poet-a")
    assert out.exists()
    assert out.suffix == ".epub"

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        # Standard EPUB structure
        assert "mimetype" in names
        assert "META-INF/container.xml" in names
        assert any(n.endswith(".opf") for n in names)
        # Our content
        assert any("poem-0001" in n for n in names)
        assert any("poem-0002" in n for n in names)
        # First poem (titled) is sorted before untitled, so should contain the
        # title text
        first = z.read("EPUB/poem-0001.xhtml").decode("utf-8")
        assert "قصيدة الأولى" in first
        # Untitled one carries the date chip
        second = z.read("EPUB/poem-0002.xhtml").decode("utf-8")
        assert "2026-05-01" in second
        # Mimetype is byte-for-byte the EPUB magic
        assert z.read("mimetype") == b"application/epub+zip"


def test_epub_endpoint_builds_and_downloads(env: Path):
    """End-to-end via the API: POST to build, GET to download."""
    import sys, importlib
    for mod in list(sys.modules):
        if mod.startswith("packages."):
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from packages.api.app import create_app
    from packages.api import projects_store

    client = TestClient(create_app())
    client.post("/projects", json={"slug": "epi", "config": {"sources": []}})
    _write_clean(
        "epi",
        "p",
        [{"id": "x", "poet": "p", "title": "ت", "text": "بيت", "word_count": 1, "line_count": 1}],
        env / "data",
    )
    r = client.post("/data/epi/subjects/p/epub")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["out"].endswith(".epub")
    assert body["size"] > 0

    d = client.get(body["url"])
    assert d.status_code == 200
    assert d.headers["content-type"].startswith("application/epub+zip")
    assert int(d.headers.get("content-length", "0")) == body["size"]
