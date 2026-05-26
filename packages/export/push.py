"""HuggingFace Hub upload for a project's export directory.

Reads creds from /home/agent/.config/dataforge/huggingface.env (mode 600):
    HUGGINGFACE_TOKEN=hf_…
    HUGGINGFACE_USERNAME=drhus            # optional; falls back to whoami()
    HUGGINGFACE_REPO_VISIBILITY=private   # private | public, default private

Usage:
    dataforge push <slug> [--repo drhus/arabic-poetry]"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from packages.api.settings import DATA_DIR

log = logging.getLogger(__name__)

CREDS_PATH = Path("/home/agent/.config/dataforge/huggingface.env")


class HFPushError(RuntimeError):
    pass


def _load_creds() -> dict[str, str]:
    if not CREDS_PATH.exists():
        raise HFPushError(
            f"HF creds not found at {CREDS_PATH} — create it with "
            "HUGGINGFACE_TOKEN=hf_... (mode 600)"
        )
    env: dict[str, str] = {}
    for line in CREDS_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    for k in (
        "HUGGINGFACE_TOKEN",
        "HUGGINGFACE_USERNAME",
        "HUGGINGFACE_REPO_VISIBILITY",
    ):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def push_to_hub(
    slug: str,
    *,
    repo_id: str | None = None,
    private: bool | None = None,
) -> dict:
    """Upload data/<slug>/export/ to a HuggingFace dataset repo.

    repo_id defaults to "<username>/<slug>". private defaults to env var,
    then True if no env var (safer default)."""
    from huggingface_hub import HfApi, create_repo

    creds = _load_creds()
    token = creds.get("HUGGINGFACE_TOKEN")
    if not token:
        raise HFPushError("HUGGINGFACE_TOKEN missing in creds file or env")

    api = HfApi(token=token)
    if not repo_id:
        username = creds.get("HUGGINGFACE_USERNAME") or api.whoami()["name"]
        repo_id = f"{username}/{slug}"

    if private is None:
        vis = creds.get("HUGGINGFACE_REPO_VISIBILITY", "private").lower()
        private = vis != "public"

    export_dir = DATA_DIR / slug / "export"
    if not export_dir.exists():
        raise HFPushError(
            f"no export dir at {export_dir} — run `dataforge export {slug}` first"
        )

    log.info("creating/getting repo %s (private=%s)", repo_id, private)
    create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True, token=token)

    log.info("uploading %s to %s", export_dir, repo_id)
    api.upload_folder(
        folder_path=str(export_dir),
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=f"hus-dataforge: refresh {slug} corpus",
    )

    url = f"https://huggingface.co/datasets/{repo_id}"
    log.info("pushed to %s", url)
    return {"repo_id": repo_id, "private": private, "url": url}


__all__ = ["push_to_hub", "HFPushError"]
