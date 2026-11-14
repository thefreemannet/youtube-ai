"""Record one human approval, then queue only the platforms that were selected.

This module does not talk to YouTube or Instagram directly. Uploads stay in the
existing private-YouTube and explicit-Instagram workers. An existing upload
record is never overwritten or retried.
"""

import json

from app.dashboard_publisher import enqueue
from app.publishing_workflow import inspect, prepare, save_metadata
from app.review_gate import JOBS, decide, review_report

# Already uploaded. Approval records and upload records for this job stay as they are.
LOCKED_JOBS = {"20261110-225615-919b89"}
PLATFORMS = ("youtube", "instagram")


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def _foreign_bodies(job_id):
    """Exact descriptions and captions that belong to a different video."""
    banned = set()
    if not JOBS.is_dir():
        return banned
    for folder in JOBS.iterdir():
        if not folder.is_dir() or folder.name == job_id:
            continue
        for name in ("youtube_publish_metadata.json", "instagram_publish_metadata.json"):
            data = _read_json(folder / name)
            for key in ("description", "caption"):
                text = str(data.get(key) or "").strip()
                if len(text) >= 40:
                    banned.add(text)
    return banned


def publishing_copy(job_id, title="", description="", caption=""):
    """Build YouTube and Instagram text from this job only."""
    folder = JOBS / job_id
    job = _read_json(folder / "job.json")
    topic = " ".join(str(job.get("topic") or "").split())
    if not topic:
        raise ValueError("This job has no topic to generate publishing text from")
    narration_path = folder / "narration_reviewed.txt"
    if not narration_path.is_file():
        narration_path = folder / "narration.txt"
    narration = ""
    if narration_path.is_file():
        narration = " ".join(narration_path.read_text(encoding="utf-8").split())
    generated = {
        "title": topic[:100],
        "description": (
            f"{topic}\n\n{narration}\n\n"
            "Educational HVAC explanation for technicians and beginners. "
            "This is not a substitute for equipment manuals or applicable codes."
        ).strip(),
        "caption": f"{topic}\n\n{narration}".strip()[:2200],
    }
    limits = {"title": 100, "description": 5000, "caption": 2200}
    supplied = {"title": title, "description": description, "caption": caption}
    chosen = {}
    for key, limit in limits.items():
        text = str(supplied[key] or "").strip() or generated[key]
        if "DRAFT:" in text.upper():
            raise ValueError("Remove draft notices from the publishing text before approval")
        if not 1 <= len(text) <= limit:
            raise ValueError(f"{key.title()} length is outside the allowed range")
        chosen[key] = text
    banned = _foreign_bodies(job_id)
    for key in ("description", "caption"):
        if chosen[key] in banned:
            raise ValueError("Publishing text matches another video. Write text for this video only")
    return chosen


def _open_platforms(info):
    open_platforms = []
    skipped = {}
    for platform in PLATFORMS:
        state = str(info["platform_states"].get(platform) or "")
        request_state = str(info["request_states"].get(platform) or "")
        if state == "NOT_UPLOADED" and request_state == "NOT_REQUESTED":
            open_platforms.append(platform)
            continue
        skipped[platform] = {
            "queued": False,
            "skipped": True,
            "state": state,
            "request_state": request_state,
            "message": "An upload record or request already exists. It was not retried.",
        }
    return open_platforms, skipped


def _ensure_prepared(job_id):
    info = inspect(job_id)
    ready = (
        info.get("export_ready") is True
        and info.get("metadata_ready", {}).get("youtube") is True
        and info.get("metadata_ready", {}).get("instagram") is True
    )
    if ready:
        return info
    if any(info.get("platform_states", {}).get(platform) != "NOT_UPLOADED" for platform in PLATFORMS):
        raise ValueError(
            "Publishing files are incomplete and an upload record already exists. "
            "Reconcile that record before another upload."
        )
    prepared = prepare(job_id)
    if "platform_states" in prepared:
        return prepared
    return inspect(job_id)


def approve_and_publish(
    job_id,
    *,
    watched_video,
    checked_technical_claims,
    checked_media_licenses,
    publish_youtube=False,
    publish_instagram=False,
    confirm_publish=False,
    title="",
    description="",
    caption="",
):
    """Approve the selected video and queue only the platforms named by the admin."""
    if job_id in LOCKED_JOBS:
        raise ValueError("This video was already uploaded and must not be published again")
    if not (watched_video is True and checked_technical_claims is True and checked_media_licenses is True):
        raise ValueError(
            "Confirm that you watched the video, checked the technical claims, and verified content rights"
        )
    selected = []
    if publish_youtube is True:
        selected.append("youtube")
    if publish_instagram is True:
        selected.append("instagram")
    if selected and confirm_publish is not True:
        raise ValueError("Confirm publishing before any upload is queued")
    copy = publishing_copy(job_id, title, description, caption) if selected else None

    report = review_report(job_id)
    if report.get("job_status") == "CHANGES_REQUESTED":
        raise ValueError("This job needs a revised preview before it can be approved")
    already = report.get("decision") == "APPROVED" and report.get("approval_current") is True
    if not already:
        decide(
            job_id,
            "APPROVED",
            confirmations={
                "watched_video": True,
                "checked_technical_claims": True,
                "checked_media_licenses": True,
            },
        )
    result = {
        "job_id": job_id,
        "video_approval": "already_current" if already else "recorded",
        "uploads": {},
        "published": False,
    }
    if not selected:
        result["message"] = "Video approval recorded. No platform was selected, so nothing was uploaded."
        return result

    info = _ensure_prepared(job_id)
    open_now, skipped = _open_platforms(info)
    for platform in selected:
        if platform in skipped:
            result["uploads"][platform] = skipped[platform]
            continue
        if platform not in open_now:
            result["uploads"][platform] = {
                "queued": False,
                "skipped": True,
                "message": "This platform is not open for a new upload.",
            }
            continue
        save_metadata(
            job_id,
            platform,
            title=copy["title"],
            description=copy["description"],
            caption=copy["caption"],
            confirm_technical=True,
            confirm_credits=True,
        )
        queued = enqueue(job_id, platform, job_id)
        result["uploads"][platform] = {
            "queued": True,
            "skipped": False,
            "request_state": queued.get("request_state", "QUEUED"),
            "message": "Upload queued.",
        }
    if any(item.get("queued") for item in result["uploads"].values()):
        result["message"] = (
            "Approval recorded and the selected uploads were queued. "
            "YouTube is private. Instagram is public only because it was selected."
        )
    else:
        result["message"] = "Nothing new was uploaded. Existing platform records were left unchanged."
    return result
