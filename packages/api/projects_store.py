"""File-backed project store. Each project is a directory under projects/
containing a config.yaml. The store is intentionally thin — projects are
git-friendly YAML, not database rows."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import yaml

from packages.api.settings import PROJECTS_DIR

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class ProjectError(Exception):
    pass


@dataclass
class Project:
    slug: str
    config: dict
    updated_at: datetime

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "config": self.config,
            "updated_at": self.updated_at.isoformat(),
        }


def _project_dir(slug: str):
    if not SLUG_RE.match(slug):
        raise ProjectError(f"invalid slug: {slug!r}")
    return PROJECTS_DIR / slug


def _config_path(slug: str):
    return _project_dir(slug) / "config.yaml"


def list_projects() -> list[Project]:
    if not PROJECTS_DIR.exists():
        return []
    out: list[Project] = []
    for child in sorted(PROJECTS_DIR.iterdir()):
        if not child.is_dir():
            continue
        cfg = child / "config.yaml"
        if not cfg.exists():
            continue
        try:
            out.append(_load(child.name))
        except ProjectError:
            continue
    return out


def _load(slug: str) -> Project:
    path = _config_path(slug)
    if not path.exists():
        raise ProjectError(f"project not found: {slug}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return Project(slug=slug, config=data, updated_at=mtime)


def get_project(slug: str) -> Project:
    return _load(slug)


def create_project(slug: str, config: dict) -> Project:
    d = _project_dir(slug)
    if d.exists():
        raise ProjectError(f"project already exists: {slug}")
    d.mkdir(parents=True)
    _config_path(slug).write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return _load(slug)


def update_project(slug: str, config: dict) -> Project:
    _config_path(slug)  # validate slug
    if not _project_dir(slug).exists():
        raise ProjectError(f"project not found: {slug}")
    _config_path(slug).write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return _load(slug)


def delete_project(slug: str) -> None:
    d = _project_dir(slug)
    if not d.exists():
        raise ProjectError(f"project not found: {slug}")
    import shutil

    shutil.rmtree(d)
