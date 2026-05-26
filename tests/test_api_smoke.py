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
