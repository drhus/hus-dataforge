from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = Path(os.environ.get("DATAFORGE_PROJECTS_DIR", REPO_ROOT / "projects"))
DATA_DIR = Path(os.environ.get("DATAFORGE_DATA_DIR", REPO_ROOT / "data"))
DB_PATH = Path(os.environ.get("DATAFORGE_DB_PATH", REPO_ROOT / "data" / "dataforge.db"))
REDIS_URL = os.environ.get("DATAFORGE_REDIS_URL", "redis://localhost:6379/0")
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "DATAFORGE_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]


def ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
