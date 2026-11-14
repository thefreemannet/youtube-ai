"""Prepare publishing metadata drafts. Never approves or uploads."""

import hashlib
import json
from pathlib import Path

from app.youtube_publish_gate import publishing_preflight

ROOT = Path("/opt/j3g-youtube-ai")
JOBS = ROOT / "data/jobs"


def file_hash(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def prepare_metadata(job_id):
    gate = publishing_preflight(job_id)

    if not gate["ready_for_oauth_upload"]:
        raise ValueError(
            "Video not approved: " +
            "; ".join(gate["blocking_reasons"])
        )

    folder = JOBS / job_id
    job = json.loads((folder / "job.json").read_text())
    preview = folder / "video_auto_preview.mp4"
    export = folder / "exports/shared_publish_ready.mp4"

    if not preview.is_file() or not export.is_file():
        raise ValueError("Approved video or shared export missing")

    youtube_file = folder / "youtube_publish_metadata.json"
    instagram_file = folder / "instagram_publish_metadata.json"

    if youtube_file.exists() or instagram_file.exists():
        raise FileExistsError(
            "Publishing metadata already exists; refusing overwrite"
        )

    reference = ROOT / "data/publisher/instagram_account.json"

    account = json.loads(reference.read_text(encoding="utf-8"))

    if (
        account.get("username") != "thefreemannet"
        or not str(account.get("account_id", "")).isdecimal()
    ):
        raise ValueError("Instagram account reference invalid")

    topic = str(job.get("topic", "")).strip()

    if not topic:
        raise ValueError("Missing video topic")

    note = (
        "DRAFT: Review technical accuracy and add required "
        "media credits before publication."
    )

    youtube = {
        "title": topic[:100],
        "description": f"{topic}\n\n{note}",
        "approved_video_sha256": file_hash(preview),
        "reviewed_by_admin": False,
    }

    instagram = {
        "platform": "instagram",
        "username": account["username"],
        "account_id": str(account["account_id"]),
        "media_type": "REELS",
        "video_path": str(export.resolve()),
        "video_sha256": file_hash(export),
        "caption": f"{topic}\n\n{note}",
        "reviewed_by_admin": False,
        "published": False,
    }

    created = []

    try:
        for path, data in (
            (youtube_file, youtube),
            (instagram_file, instagram),
        ):
            with path.open("x", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            path.chmod(0o600)
            created.append(path)
    except Exception:
        for path in created:
            path.unlink()
        raise

    return {
        "job_id": job_id,
        "youtube_metadata": str(youtube_file),
        "instagram_metadata": str(instagram_file),
        "review_required": True,
        "uploaded": False,
    }
