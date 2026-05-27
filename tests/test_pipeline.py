"""Cleaning pipeline tests — fixture-driven, deterministic."""
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


def _write_raw(slug: str, source: str, records: list[dict], data_root: Path) -> None:
    p = data_root / slug / "raw" / f"{source}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_normalize_telegram_basic(env: Path):
    from packages.pipeline.normalize import normalize_record

    raw = {
        "post_id": 4345,
        "permalink": "https://t.me/el_arje/4345",
        "text": "قِفا نَبكِ مِن ذِكرى حَبيبٍ وَمَنزِلِ\nبِسِقطِ اللِوى بَينَ الدَخولِ فَحَومَلِ",
        "published_at": "2026-04-28T19:07:55+00:00",
        "_source_url": "https://t.me/el_arje/4345",
        "_channel": "el_arje",
    }
    r = normalize_record(raw, source_name="telegram-el-arje", source_kind="telegram", poet="hudhayfah-alarje")
    assert r is not None
    assert r["poet"] == "hudhayfah-alarje"
    assert r["lang"] == "ar"
    assert r["line_count"] == 2
    assert r["source_kind"] == "telegram"
    assert r["meta"]["post_id"] == 4345


def test_normalize_filters_links_only(env: Path):
    from packages.pipeline.normalize import normalize_record

    r = normalize_record(
        {"text": "https://example.com hi"}, source_name="s", source_kind="telegram", poet=None
    )
    assert r is None


def test_aldiwan_breadcrumb_stripped(env: Path):
    from packages.pipeline.normalize import normalize_record

    raw = {
        "title": "الديوان»سوريا»حذيفة العرجي»قصيدة النصر",
        "verses": "بيتٌ شعرٌ كاملٌ هنا\nوبيتٌ ثانٍ كذلكَ يا صديقي",
        "_source_url": "https://www.aldiwan.net/poem1.html",
    }
    r = normalize_record(raw, source_name="aldiwan-alarje", source_kind="aldiwan", poet="hudhayfah-alarje")
    assert r is not None
    assert r["title"] == "قصيدة النصر"


def test_chrome_markers_stripped(env: Path):
    from packages.pipeline.normalize import normalize_record

    raw = {
        "title": "اختبار",
        "verses": "البيتُ الأولُ من القصيدة\nالبيتُ الثاني من القصيدة\nالمزيد عن الشاعر\nأضف معلومة",
        "_source_url": "x",
    }
    r = normalize_record(raw, source_name="aldiwan-x", source_kind="aldiwan", poet="p")
    assert r is not None
    assert "المزيد" not in r["text"]
    assert "أضف" not in r["text"]
    assert "البيتُ الثاني" in r["text"]


def test_dedup_exact_and_near(env: Path):
    from packages.pipeline.dedup import Deduper

    d = Deduper(threshold=0.85)
    base = {"id": "a", "text": "البيت الأول من القصيدة\nالبيت الثاني من القصيدة"}
    near = {"id": "b", "text": "البيت الأول من القصيدة\nالبيت الثاني من القصيدةِ"}
    diff = {"id": "c", "text": "نص مختلف تماماً ليس قصيدة"}
    assert d.is_dup(base) is False
    assert d.is_dup({"id": "a", "text": base["text"]}) is True   # exact-hash dup
    assert d.is_dup(near) is True                                 # near-dup
    assert d.is_dup(diff) is False


def test_dedup_check_returns_survivor_id(env: Path):
    """check() returns the survivor's id when a dup arrives."""
    from packages.pipeline.dedup import Deduper

    d = Deduper(threshold=0.85)
    base = {"id": "aldiwan-1", "text": "بيت أول مفصّل\nبيت ثاني للقصيدة"}
    near = {"id": "telegram-1", "text": "بيت أول مفصّل\nبيت ثاني للقصيدةِ"}  # near-dup
    assert d.check(base) is None  # first occurrence registered
    survivor = d.check(near)
    assert survivor == "aldiwan-1"  # near-dup points back to base


def test_clean_merges_provenance_across_sources(env: Path):
    """When the same poem is in aldiwan and a telegram source, the surviving
    clean record should list both in `sources`."""
    from packages.api import projects_store
    from packages.pipeline import run_clean

    projects_store.create_project(
        "prov",
        {
            "sources": [
                {
                    "name": "aldiwan-p",
                    "type": "list_detail",
                    "list_url": "https://x/cat-poet-p",
                    "list_link_selector": "a",
                    "record_selector": "body",
                    "fields": {"title": "h1"},
                    "poet": "p",
                },
                {
                    "name": "telegram-p",
                    "type": "telegram_web",
                    "channel": "p",
                    "poet": "p",
                },
            ]
        },
    )
    text = "بيت أول مفصّل بالعربية\nبيت ثاني للقصيدة"
    _write_raw(
        "prov",
        "aldiwan-p",
        [{"title": "T", "verses": text, "_source_url": "https://aldiwan/poem/1"}],
        env / "data",
    )
    _write_raw(
        "prov",
        "telegram-p",
        [
            {
                "text": text,
                "_channel": "p",
                "permalink": "https://t.me/p/100",
                "_source_url": "https://t.me/p/100",
            }
        ],
        env / "data",
    )
    result = run_clean("prov")
    assert result["dedup_dropped"] == 1

    out = env / "data" / "prov" / "clean" / "p.jsonl"
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    survivor = lines[0]
    # both sources should appear in the survivor's provenance list
    assert set(survivor["sources"]) == {"aldiwan-p", "telegram-p"}
    assert any("aldiwan" in u for u in survivor["source_urls"])
    assert any("t.me/p/100" in u for u in survivor["source_urls"])


def test_source_priority_mtproto_wins_dedup(env: Path):
    """When a poem appears in both telegram_mtproto and telegram_web for the
    same channel, the MTProto record (richer metadata) should be kept and the
    web-mirror one dropped as a duplicate."""
    from packages.api import projects_store
    from packages.pipeline import run_clean

    projects_store.create_project(
        "prio",
        {
            "sources": [
                {
                    "name": "telegram-x-mtproto",
                    "type": "telegram_mtproto",
                    "channel": "x",
                    "poet": "p",
                },
                {
                    "name": "telegram-x-web",
                    "type": "telegram_web",
                    "channel": "x",
                    "poet": "p",
                },
            ]
        },
    )
    data_root = env / "data"
    # Same poem in both sources; mtproto has extra metadata
    poem = "بيت من شعرٍ جميلٍ هنا\nوبيت آخر من نفس القصيدةِ"
    _write_raw(
        "prio",
        "telegram-x-mtproto",
        [
            {
                "post_id": 100,
                "text": poem,
                "edited_at": "2026-04-01T00:00:00Z",
                "views": 5000,
                "_channel": "x",
                "permalink": "https://t.me/x/100",
                "_source_url": "https://t.me/x/100",
            }
        ],
        data_root,
    )
    _write_raw(
        "prio",
        "telegram-x-web",
        [
            {
                "text": poem,
                "_channel": "x",
                "permalink": "https://t.me/x/100",
                "_source_url": "https://t.me/x/100",
            }
        ],
        data_root,
    )

    result = run_clean("prio")
    assert result["input_total"] == 2
    assert result["dedup_dropped"] == 1

    out = data_root / "prio" / "clean" / "p.jsonl"
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    # the surviving record came from MTProto (it has views in meta)
    assert lines[0]["source"] == "telegram-x-mtproto"
    assert lines[0]["meta"]["views"] == 5000


def test_categorize_splits_into_primary_and_sidecar(env: Path):
    """Records matching the categorize rule go to the primary file;
    everything else falls back to a sidecar JSONL."""
    from packages.api import projects_store
    from packages.pipeline import run_clean

    projects_store.create_project(
        "cat-test",
        {
            "sources": [
                {
                    "name": "telegram-el-arje",
                    "type": "telegram_web",
                    "channel": "el_arje",
                    "poet": "hudhayfah-alarje",
                    "categorize": [
                        {
                            "text_contains_any": ["#حذيفة_العرجي", "#قصيدة_جديدة"],
                            "set_category": "poetry",
                        }
                    ],
                    "fallback_category": "commentary",
                }
            ]
        },
    )
    data_root = env / "data"
    _write_raw(
        "cat-test",
        "telegram-el-arje",
        [
            {
                "text": "بيت من شعر العرجي\nقصيدة كاملة هنا\n#حذيفة_العرجي",
                "_channel": "el_arje",
                "permalink": "https://t.me/el_arje/100",
                "_source_url": "https://t.me/el_arje/100",
            },
            {
                "text": "أبارك لصديقي على درجة الماجستير في اللغة العربية",
                "_channel": "el_arje",
                "permalink": "https://t.me/el_arje/101",
                "_source_url": "https://t.me/el_arje/101",
            },
            {
                "text": "قصيدة جديدة من ديواني\nبيت أول جميل\n#قصيدة_جديدة",
                "_channel": "el_arje",
                "permalink": "https://t.me/el_arje/102",
                "_source_url": "https://t.me/el_arje/102",
            },
        ],
        data_root,
    )

    result = run_clean("cat-test")
    assert result["input_total"] == 3
    assert result["by_category"].get("poetry") == 2
    assert result["by_category"].get("commentary") == 1

    primary = data_root / "cat-test" / "clean" / "hudhayfah-alarje.jsonl"
    sidecar = data_root / "cat-test" / "clean" / "hudhayfah-alarje__commentary.jsonl"
    assert primary.exists() and sidecar.exists()
    primary_lines = [json.loads(l) for l in primary.read_text().splitlines() if l.strip()]
    sidecar_lines = [json.loads(l) for l in sidecar.read_text().splitlines() if l.strip()]
    assert len(primary_lines) == 2
    assert len(sidecar_lines) == 1
    assert all(r["category"] == "poetry" for r in primary_lines)
    assert all(r["category"] == "commentary" for r in sidecar_lines)


def test_run_clean_end_to_end(env: Path):
    # set up a project with two sources for two poets
    sys.path  # ensure module reload triggered above
    from packages.api import projects_store
    from packages.pipeline import run_clean

    projects_store.create_project(
        "test-corpus",
        {
            "sources": [
                {
                    "name": "aldiwan-alarje",
                    "type": "list_detail",
                    "list_url": "https://example.test/cat-poet-alarje",
                    "list_link_selector": "a",
                    "record_selector": "body",
                    "fields": {"title": "h1"},
                    "poet": "hudhayfah-alarje",
                },
                {
                    "name": "telegram-el-arje",
                    "type": "telegram_web",
                    "channel": "el_arje",
                    "poet": "hudhayfah-alarje",
                },
            ]
        },
    )

    data_root = env / "data"
    _write_raw(
        "test-corpus",
        "aldiwan-alarje",
        [
            {
                "title": "الديوان»سوريا»العرجي»قصيدة 1",
                "verses": "بيت أول مفصّل\nبيت ثاني للقصيدة",
                "_source_url": "u1",
            },
            {
                "title": "قصيدة 2",
                "verses": "نص قصيدة ثانية بالعربية\nسطر آخر للقصيدة",
                "_source_url": "u2",
            },
        ],
        data_root,
    )
    _write_raw(
        "test-corpus",
        "telegram-el-arje",
        [
            {
                "text": "بيت أول مفصّل\nبيت ثاني للقصيدة",
                "_channel": "el_arje",
                "permalink": "https://t.me/el_arje/1",
                "_source_url": "https://t.me/el_arje/1",
            },
            {
                "text": "نص فريد لرسالة تلجرام أخرى\nباللغة العربية",
                "_channel": "el_arje",
                "permalink": "https://t.me/el_arje/2",
                "_source_url": "https://t.me/el_arje/2",
            },
            {"text": "https://example.com", "_channel": "el_arje"},  # filter out
        ],
        data_root,
    )

    result = run_clean("test-corpus")
    assert result["input_total"] == 5
    assert result["filtered_out"] == 1
    # poems-1 from aldiwan matches the telegram poem → dedup
    assert result["dedup_dropped"] >= 1
    # output exists at the right path
    out = data_root / "test-corpus" / "clean" / "hudhayfah-alarje.jsonl"
    assert out.exists()
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    # 2 aldiwan + 2 telegram - 1 filtered - >=1 dedup
    assert len(lines) <= 3
    assert all(r["poet"] == "hudhayfah-alarje" for r in lines)


def test_telegram_default_strips_hashtags_and_handles(env: Path):
    """The shipped telegram_web defaults strip hashtag lines, @handle lines,
    decorative emoji lines, and Unicode bidi marks."""
    from packages.api import projects_store
    from packages.pipeline import run_clean

    projects_store.create_project(
        "tg",
        {
            "sources": [
                {
                    "name": "telegram-x",
                    "type": "telegram_web",
                    "channel": "x",
                    "poet": "poet-a",
                }
            ]
        },
    )
    _write_raw(
        "tg",
        "telegram-x",
        [
            {
                "text": (
                    "بيت من شعري الجميل\n"
                    "وبيت آخر يكمل المعنى\n"
                    "وثالث يختم القصيدة\n"
                    "#الشاعر_فلان\n"
                    "⁩\n"
                    "@my_channel\n"
                    "💛\n"
                    "....."
                ),
                "_channel": "x",
                "_source_url": "https://t.me/x/1",
            }
        ],
        env / "data",
    )
    run_clean("tg")
    out = env / "data" / "tg" / "clean" / "poet-a.jsonl"
    rec = json.loads(out.read_text().splitlines()[0])
    text = rec["text"]
    assert "#الشاعر_فلان" not in text
    assert "@my_channel" not in text
    assert "💛" not in text
    assert "⁩" not in text
    assert "....." not in text
    # Poem body survives intact
    assert "بيت من شعري الجميل" in text
    assert "وبيت آخر يكمل المعنى" in text


def test_extract_to_meta_pulls_dmy_date_to_iso(env: Path):
    """extract_to_meta with `as: iso_date_dmy` lifts a d/m/yyyy date out of
    the body and onto meta.date as YYYY-MM-DD, while removing it from text."""
    from packages.api import projects_store
    from packages.pipeline import run_clean

    projects_store.create_project(
        "dx",
        {
            "sources": [
                {
                    "name": "telegram-dated",
                    "type": "telegram_web",
                    "channel": "dated",
                    "poet": "poet-a",
                    "clean_rules": {
                        "text_ops": [
                            {
                                "op": "extract_to_meta",
                                "pattern": r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b",
                                "meta_key": "date",
                                "as": "iso_date_dmy",
                                "strip": True,
                            }
                        ]
                    },
                }
            ]
        },
    )
    _write_raw(
        "dx",
        "telegram-dated",
        [
            {
                "text": "قصيدة جميلة كاملة الشكل\nببيتين أو ثلاثة من الشعر\n11/5/2026",
                "_channel": "dated",
                "_source_url": "https://t.me/dated/1",
            },
            {
                "text": "نص آخر بدون تاريخ\nببيتين كذلك من الشعر",
                "_channel": "dated",
                "_source_url": "https://t.me/dated/2",
            },
        ],
        env / "data",
    )
    run_clean("dx")
    out = env / "data" / "dx" / "clean" / "poet-a.jsonl"
    recs = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    by_url = {r["source_url"]: r for r in recs}
    r1 = by_url["https://t.me/dated/1"]
    assert r1["meta"]["date"] == "2026-05-11"
    assert "11/5/2026" not in r1["text"]
    r2 = by_url["https://t.me/dated/2"]
    assert "date" not in r2.get("meta", {}), "no-date records should not gain a date key"


def test_extract_to_meta_rejects_implausible_dates(env: Path):
    """Implausible dates (day=99) are left alone instead of polluting meta."""
    from packages.pipeline.normalize import _apply_extract_to_meta

    meta: dict = {}
    op = {
        "op": "extract_to_meta",
        "pattern": r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b",
        "meta_key": "date",
        "as": "iso_date_dmy",
        "strip": True,
    }
    text = "version 99/13/2030 of the doc"
    out = _apply_extract_to_meta(text, op, meta)
    assert "date" not in meta
    assert out == text  # text unchanged when extraction fails
