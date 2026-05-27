"""Tests for the dry-run preview + cleanup-suggest heuristics."""
from __future__ import annotations

from packages.engine.cleanup_suggest import suggest_clean_rules
from packages.engine.preview import detect_source_type


def test_detect_telegram_web_mirror():
    r = detect_source_type("https://t.me/s/el_arje")
    assert r["type"] == "telegram_web"
    assert r["channel"] == "el_arje"
    assert r["confidence"] == "high"


def test_detect_telegram_permalink():
    r = detect_source_type("https://t.me/el_arje/4345")
    assert r["type"] == "telegram_web"
    assert r["channel"] == "el_arje"


def test_detect_x_profile():
    r = detect_source_type("https://x.com/al_arje")
    assert r["type"] == "x_syndication"
    assert r["handle"] == "al_arje"


def test_detect_aldiwan_poet_listing():
    r = detect_source_type("https://www.aldiwan.net/cat-poet-nizar-qabbani")
    assert r["type"] == "list_detail"
    assert "list_link_selector" in r


def test_detect_paginated():
    r = detect_source_type("https://example.com/poems?page=1")
    assert r["type"] == "paginated"
    assert "{page}" in r["url_template"]


def test_suggest_title_ops_split_last_when_majority_have_separator():
    samples = [
        {"title": "الديوان » سوريا » العرجي » قصيدة 1", "text": "بيت من شعر"},
        {"title": "الديوان » سوريا » العرجي » قصيدة 2", "text": "بيت آخر"},
        {"title": "الديوان » سوريا » العرجي » قصيدة 3", "text": "بيت ثالث"},
        {"title": "clean title with no separator", "text": "نص"},
    ]
    out = suggest_clean_rules(samples)
    assert any(op["op"] == "split_last" for op in out["title_ops"])
    split_op = next(op for op in out["title_ops"] if op["op"] == "split_last")
    assert split_op["separator"] == "»"
    assert split_op["if_starts_with"] == "الديوان"


def test_suggest_text_ops_detects_boilerplate_footer():
    boiler = "أضف معلومة او شرح"
    samples = [
        {"text": f"بيت\nبيت آخر\nالمزيد عن نزار قباني\n{boiler}"},
        {"text": f"قصيدة\nشيء\nالمزيد عن نزار قباني\n{boiler}"},
        {"text": f"نص\nنص\nالمزيد عن نزار قباني\n{boiler}"},
    ]
    out = suggest_clean_rules(samples)
    text_ops = out["text_ops"]
    assert text_ops, "should suggest at least one text op"
    op = text_ops[0]
    assert op["op"] == "truncate_before_first_of"
    assert any("المزيد" in m or "أضف" in m for m in op["markers"])


def test_suggest_filter_thresholds():
    samples = [{"text": "نص" * 100}, {"text": "نص" * 50}, {"text": "نص" * 200}]
    out = suggest_clean_rules(samples)
    assert out["filter_min_chars"] >= 20
    assert out["filter_min_arabic_ratio"] in (0.0, 0.4)


def test_suggest_returns_stats():
    samples = [{"title": "T1", "text": "نص قصيدة بالعربية كافية"}]
    out = suggest_clean_rules(samples)
    assert "_stats" in out
    assert out["_stats"]["samples"] == 1


def test_web_search_classifier_known_domains():
    from packages.engine.discovery_search import _classify_url

    c = _classify_url("https://www.aldiwan.net/cat-poet-x", [{"title": "x"}])
    assert c["confidence"] == "high"
    assert c["source_template"]["type"] == "list_detail"
    assert "div.bet-1" in str(c["source_template"]["fields"])


def test_web_search_classifier_telegram():
    from packages.engine.discovery_search import _classify_url

    c = _classify_url("https://t.me/s/el_arje", [{"title": "x"}])
    assert c["site"] == "telegram"
    assert c["source_template"]["channel"] == "el_arje"


def test_web_search_classifier_unknown_low_confidence():
    from packages.engine.discovery_search import _classify_url

    c = _classify_url("https://some-random-blog.example/poem/123", [{"title": "x"}])
    assert c["confidence"] == "low"
    assert c["source_template"]["type"] == "list_detail"


def test_web_search_classifier_excludes_search_engines():
    from packages.engine.discovery_search import _classify_url

    assert _classify_url("https://www.google.com/search?q=x", [{"title": "x"}]) is None
    assert _classify_url("https://duckduckgo.com/?q=x", [{"title": "x"}]) is None


def test_query_variants_for_poet_and_topic():
    from packages.engine.discovery_search import _query_variants

    poet_qs = _query_variants("نزار قباني", subject_type="poet")
    assert any("شعر" in q for q in poet_qs)
    assert any("ديوان" in q for q in poet_qs)
    topic_qs = _query_variants("زجل", subject_type="topic")
    assert any("ديوان قصائد" in q for q in topic_qs)
