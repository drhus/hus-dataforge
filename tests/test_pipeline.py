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
