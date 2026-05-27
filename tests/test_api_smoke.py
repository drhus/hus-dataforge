from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATAFORGE_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("DATAFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATAFORGE_DB_PATH", str(tmp_path / "data" / "test.db"))

    # purge cached modules so settings env vars take effect
    import importlib
    import sys

    for mod in list(sys.modules):
        if mod.startswith("packages.api"):
            del sys.modules[mod]

    from fastapi.testclient import TestClient

    from packages.api.app import create_app

    return TestClient(create_app())


def test_root_and_health(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "hus-dataforge-api"

    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_projects_crud(client):
    assert client.get("/projects").json() == []

    r = client.post("/projects", json={"slug": "test-proj", "config": {"hello": "world"}})
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "test-proj"

    r = client.get("/projects/test-proj")
    assert r.status_code == 200
    assert r.json()["config"] == {"hello": "world"}

    r = client.put("/projects/test-proj", json={"config": {"hello": "updated"}})
    assert r.status_code == 200
    assert r.json()["config"] == {"hello": "updated"}

    r = client.delete("/projects/test-proj")
    assert r.status_code == 204
    assert client.get("/projects").json() == []


def test_invalid_slug_rejected(client):
    r = client.post("/projects", json={"slug": "Bad Slug!", "config": {}})
    assert r.status_code == 422


def test_facets_and_filtered_listing(client, tmp_path: Path):
    """End-to-end: write a clean JSONL with structured meta, then verify
    the /facets endpoint tallies correctly and topic/meter filters narrow
    the /data listing."""
    import json

    import yaml

    # Create project + clean records
    client.post("/projects", json={"slug": "p", "config": {"sources": []}})

    clean_path = tmp_path / "data" / "p" / "clean" / "poet-a.jsonl"
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"id": "1", "poet": "poet-a", "text": "a", "category": "poetry",
         "meta": {"topics": "love|sadness", "meter": "بحر البسيط"}},
        {"id": "2", "poet": "poet-a", "text": "b", "category": "poetry",
         "meta": {"topics": "love"}},
        {"id": "3", "poet": "poet-a", "text": "c", "category": "commentary",
         "meta": {"topics": "war"}},
    ]
    with clean_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    r = client.get("/data/p/clean/poet-a/facets")
    assert r.status_code == 200, r.text
    body = r.json()
    topics = dict(body["topics"])
    assert topics["love"] == 2
    assert topics["sadness"] == 1
    assert topics["war"] == 1
    assert dict(body["meters"])["بحر البسيط"] == 1
    cats = dict(body["categories"])
    assert cats["poetry"] == 2
    assert cats["commentary"] == 1

    # Filter by topic
    r = client.get("/data/p/clean/poet-a", params={"topic": "love"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {rec["id"] for rec in body["records"]} == {"1", "2"}

    # Filter by category
    r = client.get("/data/p/clean/poet-a", params={"category": "commentary"})
    assert r.json()["total"] == 1

    # Combined topic + category — empty set
    r = client.get(
        "/data/p/clean/poet-a", params={"topic": "love", "category": "commentary"}
    )
    assert r.json()["total"] == 0

    # Unknown source returns 404, not 500
    r = client.get("/data/p/clean/nonexistent/facets")
    assert r.status_code == 404


def test_pipeline_config_default_and_update(client):
    """auto_pipeline defaults to True; PUT updates it; GET reads it back."""
    client.post("/projects", json={"slug": "pchain", "config": {"sources": []}})

    r = client.get("/projects/pchain/pipeline")
    assert r.status_code == 200
    body = r.json()
    assert body["auto_pipeline"] is True
    assert body["last_run"] == {"scrape": None, "clean": None, "export": None}

    r = client.put("/projects/pchain/pipeline", json={"auto_pipeline": False})
    assert r.status_code == 200
    assert r.json()["auto_pipeline"] is False
    assert client.get("/projects/pchain/pipeline").json()["auto_pipeline"] is False

    r = client.put("/projects/pchain/pipeline", json={"auto_pipeline": ["clean"]})
    assert r.status_code == 200
    assert client.get("/projects/pchain/pipeline").json()["auto_pipeline"] == ["clean"]


def test_schedule_preset_creates_named_schedule(client):
    """Applying a preset upserts a schedule with the canonical id/kind/cron."""
    client.post("/projects", json={"slug": "presets", "config": {"sources": []}})

    r = client.get("/schedule-presets")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()["presets"]}
    assert "daily-scrape" in names

    r = client.post("/projects/presets/schedules/preset/daily-scrape")
    assert r.status_code == 200, r.text

    scheds = client.get("/projects/presets/schedules").json()["schedules"]
    assert any(s["id"] == "daily-scrape" and s["cron"] == "0 4 * * *" for s in scheds)

    # Re-apply is idempotent (no duplicates)
    client.post("/projects/presets/schedules/preset/daily-scrape")
    scheds = client.get("/projects/presets/schedules").json()["schedules"]
    assert sum(1 for s in scheds if s["id"] == "daily-scrape") == 1

    # Unknown preset → 404
    r = client.post("/projects/presets/schedules/preset/nope")
    assert r.status_code == 404




def test_chain_helpers_respect_config(client, monkeypatch, tmp_path: Path):
    """_auto_pipeline_includes follows the config: True/False/list."""
    client.post("/projects", json={"slug": "ch", "config": {}})
    # Import after the env-isolation fixture has wired DB/projects dirs
    from packages.api.jobs_runner import _auto_pipeline_includes

    assert _auto_pipeline_includes("ch", "clean") is True
    assert _auto_pipeline_includes("ch", "export") is True

    client.put("/projects/ch/pipeline", json={"auto_pipeline": False})
    assert _auto_pipeline_includes("ch", "clean") is False
    assert _auto_pipeline_includes("ch", "export") is False

    client.put("/projects/ch/pipeline", json={"auto_pipeline": ["clean"]})
    assert _auto_pipeline_includes("ch", "clean") is True
    assert _auto_pipeline_includes("ch", "export") is False

    # Missing project — chain refuses to advance
    assert _auto_pipeline_includes("does-not-exist", "clean") is False
